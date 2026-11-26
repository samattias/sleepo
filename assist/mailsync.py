"""Full Outlook mail sync over Microsoft Graph, with Sam's own delegated sign-in (read-only, Mail.Read).

  assist mail-login              one-time device-code sign-in; the token cache lives in the macOS Keychain (service "assist-graph")
  assist mail-sync [--since D]   Inbox + Sent Items: exact bodies, all recipients, attachments saved to disk.
                                 First run backfills from --since (default 2026-07-01); later runs are incremental (Graph delta).

Each message lands as an item (outlook.inbox / outlook.sent) plus a mail_messages row; existing gist rows written by
Claude are matched and kept, so triage notes and noise flags survive. Nothing is ever sent or changed in the mailbox.
"""
import base64
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import db, entities
from . import profile
from .retention import RETENTION_DAYS

CLIENT_ID = os.environ.get("ASSIST_GRAPH_CLIENT_ID", "78d54dbb-520b-2b5a-d3a4-336c38ccf41b")  # Microsoft Graph Command Line Tools (public client)
AUTHORITY = "https://login.microsoftonline.com/" + os.environ.get("ASSIST_TENANT", "organizations")
SCOPES = ["Mail.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"
FOLDERS = {"inbox": "outlook.inbox", "sentitems": "outlook.sent"}
SELECT = ("subject,from,sender,toRecipients,ccRecipients,bccRecipients,replyTo,receivedDateTime,sentDateTime,body,bodyPreview,"
          "hasAttachments,importance,isRead,flag,categories,conversationId,internetMessageId,webLink,parentFolderId")
DEFAULT_SINCE = profile.get()["mail_since"] or datetime.fromtimestamp(time.time() - 90 * 86400, timezone.utc).strftime("%Y-%m-%d")   # the profile
# Full messages older than RETENTION_DAYS (assist/retention.py) are purged after every sync.
MAX_ATTACHMENT = 150 * 1024 * 1024


def home():
    return db.db_path().parent


def attachments_dir():
    d = home() / "mail" / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- auth
KEYCHAIN = ("assist-graph", db.keychain_account())


def _app():
    import keyring
    import msal
    cache = msal.SerializableTokenCache()
    blob = keyring.get_password(*KEYCHAIN)
    if blob:
        cache.deserialize(blob)
    return msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache), cache, None


def _save(cache, _=None):
    import keyring
    if cache.has_state_changed:
        keyring.set_password(*KEYCHAIN, cache.serialize())


def login():
    app, cache, f = _app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise SystemExit("could not start sign-in: " + json.dumps(flow, indent=2))
    print(flow["message"], flush=True)
    res = app.acquire_token_by_device_flow(flow)
    _save(cache, f)
    if "access_token" not in res:
        raise SystemExit("sign-in failed: " + (res.get("error_description") or json.dumps(res)))
    who = (res.get("id_token_claims") or {}).get("preferred_username", "")
    print(f"signed in{(' as ' + who) if who else ''}; mail sync is ready")


def signed_in():
    app, _, _ = _app()
    return bool(app.get_accounts())


def token():
    app, cache, f = _app()
    acc = app.get_accounts()
    res = app.acquire_token_silent(SCOPES, account=acc[0]) if acc else None
    _save(cache, f)
    if not res or "access_token" not in res:
        raise SystemExit("not signed in to Microsoft Graph: run  ~/.assist/venv/bin/python -m assist.cli mail-login")
    return res["access_token"]


class Graph:
    def __init__(self):
        import requests
        self.s = requests.Session()
        self.tok = token()

    def get(self, url, raw=False, params=None):
        for attempt in range(6):
            r = self.s.get(url if url.startswith("http") else GRAPH + url, params=params,
                           headers={"Authorization": "Bearer " + self.tok, "Prefer": 'outlook.body-content-type="html"'}, timeout=120)
            if r.status_code == 401 and attempt == 0:
                self.tok = token(); continue
            if r.status_code in (429, 503, 504):
                time.sleep(int(r.headers.get("Retry-After", 2 ** attempt))); continue
            r.raise_for_status()
            return r.content if raw else r.json()
        r.raise_for_status()


# ---------------------------------------------------------------- helpers
class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"): self.skip += 1
        if tag in self.BLOCK: self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"): self.skip = max(0, self.skip - 1)
        if tag in self.BLOCK: self.out.append("\n")

    def handle_data(self, d):
        if not self.skip: self.out.append(d)


def to_text(body, kind):
    if kind != "html":
        return body or ""
    p = _Text(); p.feed(body or "")
    t = html.unescape("".join(p.out)).replace("\xa0", " ")
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", t)).strip()


def _people(lst):
    return [{"name": (x.get("emailAddress") or {}).get("name") or "", "address": (x.get("emailAddress") or {}).get("address") or ""} for x in (lst or [])]


def _safe(name):
    return re.sub(r"[^\w.\- ()&+]", "_", name or "attachment").strip()[:120] or "attachment"


def _ts(s):
    return (s or "").replace(".000Z", "Z").replace("+00:00", "Z")


# ---------------------------------------------------------------- store
def _find_item(con, source_id, m):
    ext = "mail:" + m["id"]
    row = con.execute("SELECT id FROM items WHERE source_id=? AND external_id=?", (source_id, ext)).fetchone()
    if row:
        return row["id"]
    # the same message stored by the other path (Apple Mail by Message-ID, the connector by Graph id): one record
    imid = (m.get("internetMessageId") or "").strip()
    if imid:
        row = con.execute("SELECT m.item_id AS id FROM mail_messages m JOIN items i ON i.id=m.item_id WHERE m.internet_message_id=? AND i.source_id=?",
                          (imid, source_id)).fetchone() \
            or con.execute("SELECT id FROM items WHERE source_id=? AND json_extract(payload, '$.internet_message_id')=?", (source_id, imid)).fetchone()
        if row:
            return row["id"]
    # gist rows written by Claude without the Graph id: same folder, same subject (Claude often appends " — note"),
    # within three minutes or exactly one hour off (older gists stored London time labelled as UTC)
    ts = _ts(m.get("receivedDateTime") if source_id == "outlook.inbox" else m.get("sentDateTime"))
    subj = (m.get("subject") or "").strip()
    if not ts or not subj:
        return None
    norm = lambda x: re.sub(r"^((re|fw|fwd|aw|tr|wg)\s+)+", "", re.sub(r"\W+", " ", re.split(r"\s+[—–]\s+", x or "")[0].lower()).strip())
    t = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    best = None
    for r in con.execute("SELECT id, ts, subject FROM items WHERE source_id=? AND ts BETWEEN ? AND ? AND id NOT IN (SELECT item_id FROM mail_messages)",
                         (source_id, datetime.fromtimestamp(t - 3900, timezone.utc).strftime("%Y-%m-%dT%H:%M"), datetime.fromtimestamp(t + 3900, timezone.utc).strftime("%Y-%m-%dT%H:%M:59Z"))):
        a, b = norm(r["subject"]), norm(subj)
        if not a or not (a == b or a.startswith(b[:30]) or b.startswith(a[:30])):
            continue
        d = abs(datetime.strptime(r["ts"][:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp() - t) / 60
        if d <= 3 or 57 <= d <= 63:
            if best is None or d < best[0]:
                best = (d, r["id"])
    return best[1] if best else None


def store(con, g, folder, m, pull_id):
    source_id = FOLDERS[folder]
    frm = (m.get("from") or m.get("sender") or {}).get("emailAddress") or {}
    ts = _ts(m.get("receivedDateTime") if folder == "inbox" else (m.get("sentDateTime") or m.get("receivedDateTime")))
    body = m.get("body") or {}
    kind = "html" if (body.get("contentType") or "").lower() == "html" else "text"
    text = to_text(body.get("content"), kind)
    to, cc, bcc = _people(m.get("toRecipients")), _people(m.get("ccRecipients")), _people(m.get("bccRecipients"))
    sender_name = frm.get("name") or frm.get("address") or ""

    pat = any(f.lower() in (p.get("address") or p.get("name") or "").lower() for p in to + cc for f in profile.get()["forwarded_mailboxes"] if f)   # a forwarded mailbox (the profile)
    iid = _find_item(con, source_id, m)
    if iid:  # keep the gist / triage note and noise flag Claude wrote; fill what was missing
        con.execute("UPDATE items SET external_id=?, url=COALESCE(url, ?), from_name=COALESCE(NULLIF(from_name,''), ?), subject=COALESCE(NULLIF(subject,''), ?), "
                    "thread=COALESCE(thread, ?), pull_id=COALESCE(pull_id, ?) WHERE id=?",
                    ("mail:" + m["id"], m.get("webLink"), sender_name, m.get("subject"), m.get("conversationId"), pull_id, iid))
    else:
        iid, _ = db.upsert_item(con, source_id, "mail:" + m["id"], "mail" if folder == "inbox" else "sent", ts, pull_id=pull_id,
                                from_name=sender_name, subject=m.get("subject"), text=None, thread=m.get("conversationId"),
                                url=m.get("webLink"), noise=pat, from_person_id=db.resolve_person(con, frm.get("address")) or db.resolve_person(con, frm.get("name")))
    # every address seen becomes an alias of a known person with the same name
    for p in [{"name": frm.get("name"), "address": frm.get("address")}] + to + cc:
        if p.get("address") and p.get("name") and entities.personal_address(p["address"]):   # not jira@ "from" whoever acted
            pid = db.resolve_person(con, p["name"])
            if pid:
                con.execute("INSERT OR IGNORE INTO people_aliases (alias, person_id) VALUES (?, ?)", (p["address"].lower(), pid))

    con.execute("INSERT INTO mail_messages (item_id, graph_id, folder, internet_message_id, conversation_id, from_name, from_address, to_json, cc_json, bcc_json, "
                "reply_to_json, subject, received_at, sent_at, body_type, body, body_text, preview, has_attachments, importance, is_read, flag, categories_json, web_link, synced_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET graph_id=excluded.graph_id, folder=excluded.folder, "
                "to_json=excluded.to_json, cc_json=excluded.cc_json, bcc_json=excluded.bcc_json, body=excluded.body, body_text=excluded.body_text, preview=excluded.preview, "
                "has_attachments=excluded.has_attachments, is_read=excluded.is_read, flag=excluded.flag, categories_json=excluded.categories_json, web_link=excluded.web_link, synced_at=excluded.synced_at",
                (iid, m["id"], folder, m.get("internetMessageId"), m.get("conversationId"), frm.get("name"), frm.get("address"),
                 json.dumps(to), json.dumps(cc), json.dumps(bcc), json.dumps(_people(m.get("replyTo"))), m.get("subject"),
                 _ts(m.get("receivedDateTime")), _ts(m.get("sentDateTime")), kind, body.get("content"), text, m.get("bodyPreview"),
                 1 if m.get("hasAttachments") else 0, m.get("importance"), 1 if m.get("isRead") else 0,
                 ((m.get("flag") or {}).get("flagStatus")), json.dumps(m.get("categories") or []), m.get("webLink"), db.now()))
    con.execute("DELETE FROM mail_fts WHERE rowid=?", (iid,))
    con.execute("INSERT INTO mail_fts (rowid, subject, body_text, people) VALUES (?,?,?,?)",
                (iid, m.get("subject") or "", text, " ".join(f"{p['name']} {p['address']}" for p in [{"name": frm.get("name") or "", "address": frm.get("address") or ""}] + to + cc)))

    n = 0
    if g and (m.get("hasAttachments") or (kind == "html" and "cid:" in (body.get("content") or ""))):
        n = attachments(con, g, iid, m["id"])
    return iid, n


def attachments(con, g, iid, mid):
    n = 0
    url = f"/me/messages/{mid}/attachments"
    while url:
        page = g.get(url)
        for a in page.get("value", []):
            typ = (a.get("@odata.type") or "").split(".")[-1]
            kind = {"fileAttachment": "file", "itemAttachment": "item", "referenceAttachment": "reference"}.get(typ, typ)
            path, sha = None, None
            data = None
            if kind == "file" and (a.get("size") or 0) <= MAX_ATTACHMENT:
                data = base64.b64decode(a["contentBytes"]) if a.get("contentBytes") else g.get(f"/me/messages/{mid}/attachments/{a['id']}/$value", raw=True)
            elif kind == "item":  # an attached email or event: keep it as .eml
                try:
                    data = g.get(f"/me/messages/{mid}/attachments/{a['id']}/$value", raw=True)
                except Exception:
                    data = None
            if data is not None:
                sha = hashlib.sha256(data).hexdigest()
                name = _safe(a.get("name")) + (".eml" if kind == "item" and not (a.get("name") or "").lower().endswith(".eml") else "")
                rel = f"{sha[:2]}/{sha[:16]}-{name}"
                f = attachments_dir() / rel
                if not f.exists():
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                path = rel
            con.execute("INSERT INTO mail_attachments (item_id, graph_id, name, content_type, size, is_inline, content_id, kind, path, sha256) VALUES (?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(item_id, graph_id) DO UPDATE SET path=COALESCE(excluded.path, path), sha256=COALESCE(excluded.sha256, sha256)",
                        (iid, a["id"], a.get("name"), a.get("contentType"), a.get("size"), 1 if a.get("isInline") else 0, a.get("contentId"), kind, path, sha))
            n += 1
        url = page.get("@odata.nextLink")
    return n


# ---------------------------------------------------------------- sync
def purge(con, days, log=print):
    """Delete full messages (body, recipients, attachments) received more than `days` ago. Gist rows in items stay."""
    if not days:
        return 0
    cutoff = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = [r["item_id"] for r in con.execute("SELECT item_id FROM mail_messages WHERE COALESCE(received_at, sent_at) < ?", (cutoff,))]
    for iid in old:
        for a in con.execute("SELECT path FROM mail_attachments WHERE item_id=?", (iid,)).fetchall():
            if a["path"] and not con.execute("SELECT 1 FROM mail_attachments WHERE path=? AND item_id<>?", (a["path"], iid)).fetchone():
                f = attachments_dir() / a["path"]
                if f.exists():
                    f.unlink()
        con.execute("DELETE FROM mail_attachments WHERE item_id=?", (iid,))
        con.execute("DELETE FROM mail_fts WHERE rowid=?", (iid,))
        con.execute("DELETE FROM mail_messages WHERE item_id=?", (iid,))
    con.commit()
    if old:
        log(f"retention: purged {len(old)} full messages older than {days} days")
    return len(old)


def sync(con, since=None, log=print):
    days = RETENTION_DAYS
    if days and not since:  # never fetch what retention would delete straight away
        since = max(DEFAULT_SINCE, datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).strftime("%Y-%m-%d"))
    g = Graph()
    total = {}
    for folder, source_id in FOLDERS.items():
        key = f"mail_delta:{folder}"
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        start = since or DEFAULT_SINCE
        url = row["value"] if row and not since else f"/me/mailFolders/{folder}/messages/delta?$select={SELECT}&$filter=receivedDateTime+ge+{start}T00:00:00Z"
        pull = db.start_pull(con, source_id, "assist mail-sync", None if row and not since else start, None, "Microsoft Graph delta: full bodies, recipients, attachments")
        seen = files = removed = 0
        while url:
            page = g.get(url)
            for m in page.get("value", []):
                if "@removed" in m:
                    removed += 1
                    continue
                if "body" not in m:  # delta can return a stub; fetch the whole message
                    m = g.get(f"/me/messages/{m['id']}", params={"$select": SELECT})
                _, n = store(con, g, folder, m, pull)
                seen += 1; files += n
                if seen % 50 == 0:
                    con.commit(); log(f"  {folder}: {seen} messages, {files} attachments")
            if page.get("@odata.deltaLink"):
                con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, page["@odata.deltaLink"]))
            url = page.get("@odata.nextLink")
        db.finish_pull(con, pull, available=seen, pulled=seen, noise=None, complete=1)
        con.execute("UPDATE sources SET health='ok', note=? WHERE id=?", (f"full messages via Graph · last sync {db.now()[:16].replace('T', ' ')}", source_id))
        con.commit()
        total[folder] = {"messages": seen, "attachments": files, "removed_in_outlook": removed}
        log(f"{folder}: {seen} messages, {files} attachments" + (f", {removed} removed in Outlook (kept here)" if removed else ""))
    total["purged"] = purge(con, days, log)
    return total


# ---------------------------------------------------------------- connector path
# Sam's choice (2026-10-06): mask national identifiers and home addresses; everything else is stored as written.
# The look-arounds keep Teams meeting links (/meet/<digits>) and long decimals in spreadsheets out of the match.
NIR = re.compile(r"(?<![\d./=#-])[12][\s.]?\d{2}[\s.]?(?:0[1-9]|1[0-2]|[2-9]\d)[\s.]?(?:\d{2}|2[AB])[\s.]?\d{3}[\s.]?\d{3}(?:[\s.]?\d{2})?(?![\d.])")
HOME = re.compile(r"\b\d{1,4}(?:\s?(?:bis|ter))?,?\s+(?:rue|avenue|av\.|boulevard|bd|chemin|allée|allee|impasse|place|route|quai|cours|square|résidence|residence|lieu[- ]dit)\b[^\n,]{2,60},?\s*(?:\n\s*)?\d{5}\s+[A-ZÉÈa-zéèêàç' -]{2,40}", re.I)


def mask(text, attachment=False):
    if not text:
        return text
    text = NIR.sub("[social security number redacted]", text)
    return HOME.sub("[home address redacted]", text) if attachment else text


def store_record(con, r, pull_id=None):
    """One message pulled through the Claude Microsoft 365 connector (ingest bundle "mail_messages").
    The body arrives as plain text and attachments as extracted text, so nothing is downloaded here."""
    addr = lambda x: {"emailAddress": {"name": (x or {}).get("name") or "", "address": (x or {}).get("address") or ""}}
    folder = "sentitems" if r.get("folder") in ("sent", "sentitems", "outlook.sent") else "inbox"
    m = {"id": r["graph_id"], "subject": r.get("subject"), "from": addr(r.get("from")),
         "toRecipients": [addr(x) for x in r.get("to") or []], "ccRecipients": [addr(x) for x in r.get("cc") or []],
         "bccRecipients": [addr(x) for x in r.get("bcc") or []], "receivedDateTime": r.get("received_at"), "sentDateTime": r.get("sent_at"),
         "body": {"contentType": "text", "content": mask(r.get("body_text")) or ""}, "bodyPreview": (mask(r.get("body_text")) or "")[:255],
         "hasAttachments": bool(r.get("attachments")), "importance": r.get("importance"), "isRead": r.get("is_read", True),
         "conversationId": r.get("conversation_id"), "internetMessageId": r.get("internet_message_id"), "webLink": r.get("web_link")}
    iid, _ = store(con, None, folder, m, pull_id)
    for a in r.get("attachments") or []:
        con.execute("INSERT INTO mail_attachments (item_id, graph_id, name, content_type, size, is_inline, kind, text) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(item_id, graph_id) DO UPDATE SET text=COALESCE(excluded.text, text)",
                    (iid, a.get("id") or a.get("name"), a.get("name"), a.get("content_type"), a.get("size"), 1 if a.get("is_inline") else 0, "file", mask(a.get("text"), attachment=True)))
    return iid


def window(con):
    """Where the next connector pull should start, per folder: last stored message minus one hour, never older than retention."""
    floor = time.time() - RETENTION_DAYS * 86400
    out = {}
    for folder, name in (("inbox", "inbox"), ("sentitems", "sent")):
        row = con.execute("SELECT MAX(COALESCE(received_at, sent_at)) FROM mail_messages WHERE folder=?", (folder,)).fetchone()[0]
        last = datetime.strptime(row[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() - 3600 if row else floor
        out[name] = datetime.fromtimestamp(max(last, floor), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out
