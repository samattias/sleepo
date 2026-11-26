"""Links in an email: the documents it points to, read like attachments by the reply writer, the document planner and the
briefing (replies.context, action_context._mail_block, briefing.pack), and listed in the composer's "Can draw on".

Mail text keeps a link as `label<url>` (Outlook) or a bare URL. Signature icons, social links, images, mailto and meeting
joins are not documents and are left out. A SharePoint or OneDrive link is matched to what SleePO already holds by its
address or its file name: a SharePoint file the documents pull read, a local file, an attachment of the same name, or a
file Sam added to the email himself (Inbox: Add a file). SleePO never fetches a link: a GET can confirm a read or trigger
an action (unsubscribe, approve), and a new sharing link cannot be opened without Microsoft Graph. A link it cannot match
is named as not read, so the writer says so instead of guessing, and Sam can add the file.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from . import org

URL = re.compile(r"https?://[^\s<>\"'\]\)]+")
LABELLED = re.compile(r"<(https?://[^>\s]+)>")
ZW = re.compile(r"[​-‏⁠﻿]")
FILE_EXT = re.compile(r"\.(pptx?|docx?|xlsx?|xlsm|pdf|html?|txt|md|csv|rtf|odt|vsdx?|png|jpe?g|zip)$", re.I)
# not documents: signatures, social, images, tracking, meeting joins, mail
SKIP_HOST = re.compile(r"(^|\.)(linkedin|instagram|twitter|x|facebook|youtube|t|bit|aka)\.(com|ms|ly|co)$|onecdn\.static\.microsoft|"
                       r"teams\.microsoft\.com|zoom\.us|safelinks\.protection\.outlook\.com$|aka\.ms$", re.I)
SKIP_PATH = re.compile(r"\.(svg|png|jpe?g|gif|ico)(\?|$)|unsubscribe|optout|opt-out|/track|/click|utm_", re.I)
SKIP_LABEL = re.compile(r"^\[?(image|photo|icon|logo|linkedin icon|instagram icon|employee photo|cid:)", re.I)
SITE_HOME = org.site_home()   # the company's own home page (the org pack)
SHARE_KIND = {"u": "file", "w": "Word file", "x": "Excel file", "p": "PowerPoint file", "b": "PDF", "t": "text file", "v": "video", "f": "folder", "i": "image"}
MIN_TEXT = 400   # a SharePoint row with less text is a search snippet, not the document
DOWNLOADS = Path.home() / "Downloads"   # where a linked file lands when Sam opens its link and downloads it
DOWNLOAD_DAYS = 30


def _unwrap(url):
    """Outlook Safe Links wrap the real address in ?url=."""
    p = urlparse(url)
    if p.netloc.endswith("safelinks.protection.outlook.com"):
        real = parse_qs(p.query).get("url")
        if real:
            return real[0]
    return url


def _kind(url):
    """(kind, name from the address): sharepoint | onedrive | confluence | jira | web."""
    p = urlparse(url)
    host = p.netloc.lower()
    path = unquote(p.path)
    if host.endswith("sharepoint.com") or host == "1drv.ms" or host.endswith("onedrive.live.com"):
        m = re.match(r"^/:(\w):/", path)
        name = "" if m else path.rstrip("/").rsplit("/", 1)[-1]
        if not name or name.lower().endswith(".aspx"):   # …/_layouts/15/Doc.aspx?sourcedoc=…&file=Deck.pptx
            name = (parse_qs(p.query).get("file") or [""])[0]
        return ("onedrive" if "-my.sharepoint.com" in host or host == "1drv.ms" else "sharepoint"), (m.group(1) if m else ""), name
    if host.endswith("atlassian.net"):
        return ("jira" if "/browse/" in path else "confluence"), "", ""
    return "web", "", path.rstrip("/").rsplit("/", 1)[-1]


def _label(before):
    """The label of a `label<url>` link from the text before it on its line. Outlook puts the file-type icon first
    ("[https://…/pptx.svg]2006 contoso LIVE - Acme EN.pptx<link>"); a file name keeps its spaces, up to the end of the
    sentence or clause before it ("The deck: Q4 plan.pptx"); any other label is the word touching the link."""
    before = before.rsplit("]", 1)[-1]
    if FILE_EXT.search(before.strip()):
        return re.split(r"[\[\]()>]|[.:;,!?]\s", before)[-1].strip()
    return re.search(r"\S*$", before).group(0)


def find(text):
    """The links in an email body that may point to something to read: [{label, url, kind, share, name}], in order, once each."""
    out, seen = [], set()
    text = ZW.sub("", text or "")
    spans, covered, end = [], [], 0
    for m in LABELLED.finditer(text):
        line = max(end, text.rfind("\n", 0, m.start()) + 1, m.start() - 200)   # the label: before it on its line, after the last link
        before = text[line:m.start()]
        before = before[before.rfind(">") + 1:]
        spans.append((m.start(1), _label(before).strip("[]() :"), m.group(1)))
        covered.append((m.start(), m.end()))
        end = m.end()
    labelled = {u for _, _, u in spans}
    for m in URL.finditer(text):
        if m.group(0) not in labelled and not any(a <= m.start() < b for a, b in covered):
            spans.append((m.start(), "", m.group(0)))
    for _, label, url in sorted(spans):
        url = _unwrap(url.rstrip(".,;"))
        p = urlparse(url)
        if not p.netloc or SKIP_HOST.search(p.netloc) or SKIP_PATH.search(url) or SITE_HOME.match(url) or SKIP_LABEL.match(label or ""):
            continue
        key = url.split("?")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        kind, share, name = _kind(url)
        if not name and (FILE_EXT.search(label or "") or share):   # a sharing link names nothing: its label does
            name = label
        out.append({"label": label or name or p.netloc, "url": url, "kind": kind, "share": SHARE_KIND.get(share, ""), "name": name})
    return out


def resolve(con, link, item_ids=()):
    """The document SleePO holds for a link: {doc, name, text} or None. By address first (a SharePoint path), then by file
    name: a file Sam added to the email or an attachment on the thread, a SharePoint or local file of that name."""
    name = (link.get("name") or "").strip()
    url = link["url"]
    if link["kind"] in ("sharepoint", "onedrive"):
        path = unquote(urlparse(url).path)
        if not path.startswith("/:"):
            for r in con.execute("SELECT id, source_id, subject, text FROM items WHERE source_id IN ('sharepoint', 'local') AND url IS NOT NULL "
                                 "AND (url = ? OR replace(url, '%20', ' ') LIKE ?) ORDER BY length(text) DESC LIMIT 1", (url, f"%{path}%")):
                return {"doc": f"{'lf' if r['source_id'] == 'local' else 'sp'}-{r['id']}", "name": r["subject"], "text": r["text"] or ""}
    if not name or not FILE_EXT.search(name):
        return None
    if item_ids:
        q = ",".join("?" * len(item_ids))
        r = con.execute(f"SELECT id, name, text FROM mail_attachments WHERE item_id IN ({q}) AND is_inline=0 AND lower(name)=lower(?) "
                        "ORDER BY text IS NULL, id DESC LIMIT 1", (*item_ids, name)).fetchone()
        if r:
            return {"doc": f"ma-{r['id']}", "name": r["name"], "text": r["text"] or ""}
    r = con.execute("SELECT id, source_id, subject, text FROM items WHERE source_id IN ('sharepoint', 'local') AND lower(subject)=lower(?) "
                    "ORDER BY length(text) DESC, ts DESC LIMIT 1", (name,)).fetchone()
    if r and len(r["text"] or "") >= MIN_TEXT:
        return {"doc": f"{'lf' if r['source_id'] == 'local' else 'sp'}-{r['id']}", "name": r["subject"], "text": r["text"] or ""}
    got = downloaded(name) if link["kind"] in ("sharepoint", "onedrive") else None
    if got:
        return got
    if r:
        return {"doc": f"{'lf' if r['source_id'] == 'local' else 'sp'}-{r['id']}", "name": r["subject"], "text": r["text"] or ""}
    return None


def downloaded(name):
    """A linked file Sam downloaded from its link: ~/Downloads/<that exact name> (or Safari's "name (2).ext"), from the last
    30 days. Read on demand, nothing stored: {doc: None, name, text, where: "Downloads"} or None."""
    from .localfiles import extract
    stem, _, ext = name.rpartition(".")
    if not stem or "/" in name or name.startswith("."):
        return None
    try:
        cands = [p for p in DOWNLOADS.glob(f"{glob_escape(stem)}*.{glob_escape(ext)}")
                 if p.name.lower() == name.lower() or re.fullmatch(re.escape(stem) + r" \(\d+\)\." + re.escape(ext), p.name, re.I)]
        cands = [p for p in cands if p.is_file() and time.time() - p.stat().st_mtime < DOWNLOAD_DAYS * 86400 and p.stat().st_size <= MAX_ADD]
    except OSError:
        return None
    for p in sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True):
        text = extract(p, ext.lower())
        if (text or "").strip():
            from . import mailsync
            return {"doc": None, "name": name, "text": mailsync.mask(text, attachment=True), "where": "Downloads"}
    return None


def glob_escape(s):
    return re.sub(r"([*?\[\]])", r"[\1]", s)


def thread_ids(con, item_id):
    """The email and the rest of its thread (same conversation id), newest first."""
    m = con.execute("SELECT conversation_id FROM mail_messages WHERE item_id=?", (item_id,)).fetchone()
    if not m or not m["conversation_id"]:
        return [item_id]
    return [item_id] + [r[0] for r in con.execute("SELECT item_id FROM mail_messages WHERE conversation_id=? AND item_id<>? "
                                                  "ORDER BY COALESCE(received_at, sent_at) DESC", (m["conversation_id"], item_id))]


def for_email(con, item_id, thread=True):
    """Every document-like link in the email (and, with thread, the earlier messages of its thread), resolved:
    [{label, url, kind, share, name, this_email, doc, text, readable}]. readable: SleePO holds its text."""
    ids = thread_ids(con, item_id) if thread else [item_id]
    out, seen = [], set()
    for iid in ids:
        r = con.execute("SELECT body_text, folder FROM mail_messages WHERE item_id=?", (iid,)).fetchone()
        if not r:
            continue
        body = r["body_text"] or ""
        if iid != item_id:   # an earlier message: its own words, not the history it quotes (already read from the newer one)
            body = re.split(r"\n(?:From|De|Von)\s*:", body)[0]
        for link in find(body):
            key = link["url"].split("?")[0].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(_resolved(con, link, ids, iid == item_id))
    return out


def _resolved(con, link, ids, this):
    hit = resolve(con, link, ids)
    text = (hit or {}).get("text") or ""
    return {**link, "this_email": this, "doc": (hit or {}).get("doc"), "name": (hit or {}).get("name") or link["name"] or link["label"],
            "text": text, "where": (hit or {}).get("where"),
            "readable": len(text) >= MIN_TEXT or bool(hit and text and (hit.get("where") or (hit["doc"] or "").startswith("ma-")))}


def chat_link(name, url):
    """A Teams or Slack attachment (or a link in the message) as a link: {label, url, kind, share, name}."""
    kind, share, from_url = _kind(url)
    name = name or from_url
    return {"label": name or urlparse(url).netloc, "url": url, "kind": kind, "share": SHARE_KIND.get(share, ""), "name": name}


def for_chat(con, item_ids, newest=None):
    """The files attached to Teams/Slack messages and the documents their text links to, resolved like an email's links (the
    chat pull reads an attached SharePoint/OneDrive file into a SharePoint item, so it matches by address): the same shape as
    for_email, this_email meaning "in the newest message". item_ids oldest first."""
    ids = list(item_ids)
    newest = newest if newest is not None else (ids[-1] if ids else None)
    out, seen = [], set()
    for iid in reversed(ids):
        found = [chat_link(a["name"], a["url"]) for a in con.execute("SELECT name, url FROM chat_attachments WHERE item_id=? AND url IS NOT NULL "
                                                                       "AND url != '' ORDER BY id", (iid,))]
        r = con.execute("SELECT links_json FROM chat_messages WHERE item_id=?", (iid,)).fetchone()
        for x in json.loads((r["links_json"] if r else None) or "[]"):
            u = _unwrap(x.get("url") or "")
            p = urlparse(u)
            if p.netloc and not (SKIP_HOST.search(p.netloc) or SKIP_PATH.search(u) or SITE_HOME.match(u)):
                found.append(chat_link(x.get("title") if FILE_EXT.search(x.get("title") or "") else "", u))
        for link in found:
            key = link["url"].split("?")[0].lower()
            if key not in seen:
                seen.add(key)
                out.append(_resolved(con, link, (), iid == newest))
    return out


def held(con):
    """The address paths (lower case) of the SharePoint/OneDrive files whose text SleePO holds: marks an attachment as read
    without resolving each one. By address only, so a file of the same name elsewhere does not count."""
    return {unquote(urlparse(r["url"]).path).lower()
            for r in con.execute("SELECT url FROM items WHERE source_id='sharepoint' AND url IS NOT NULL AND length(text) >= ?", (MIN_TEXT,))}


def is_held(paths, url):
    return bool(url) and unquote(urlparse(url).path).lower() in paths


def context_lines(links, budget=12000, per=6000, noun="email"):
    """Markdown for a prompt: the linked documents SleePO holds, in full up to the budget, then the links it could not open."""
    L, gone = [], []
    for x in links:
        where = f"in this {noun}" if x["this_email"] else ("earlier in the thread" if noun == "email" else "earlier in the conversation")
        if x["readable"] and budget > 0:
            t = x["text"][:min(per, budget)]
            budget -= len(t)
            L += [f"# Linked document ({where}): {x['name']}", t, ""]
        elif x["kind"] in ("sharepoint", "onedrive", "confluence") or x["share"] or FILE_EXT.search(x["name"] or ""):
            gone.append(f"- {x['name']}" + (f" ({x['share']})" if x["share"] else "") + f" · {where}")
    if gone:
        L += [f"# Linked in the {noun}, but SleePO could not open them (do not guess what they say; if the reply depends on one, "
              f"say in notes that {USER.first} should check it or add the file)"] + gone + [""]
    return L


# ------------------------------------------------------------------------------------------------ a file Sam adds
ADD_EXTS = {"pdf", "docx", "pptx", "xlsx", "txt", "csv", "md", "html", "htm", "rtf", "doc", "odt"}
MAX_ADD = 25 * 1024 * 1024


def add_file(con, item_id, name, data):
    """A file Sam adds to an email himself (Inbox: Add a file), typically a linked document SleePO cannot open. Kept as the
    email's attachment, text only (the file itself is not stored), so the reply, the document plan and the briefing read it
    and the link it stands for counts as read. Returns the attachment id."""
    import hashlib
    import os
    import tempfile
    from pathlib import Path
    from . import mailsync
    from .localfiles import extract
    if not con.execute("SELECT 1 FROM mail_messages WHERE item_id=?", (item_id,)).fetchone():
        raise ValueError("No such email.")
    name = os.path.basename((name or "").replace("\\", "/")).strip()[:200] or "file"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ADD_EXTS:
        raise ValueError(f"SleePO cannot read {('.' + ext) if ext else 'this kind of'} file. Add a PDF, Word, PowerPoint, Excel, HTML or text file.")
    if not data or len(data) > MAX_ADD:
        raise ValueError("The file is empty or larger than 25 MB.")
    fd, tmp = tempfile.mkstemp(suffix="." + ext)   # extraction needs a file: a private temp file, deleted at once
    try:
        os.write(fd, data)
        os.close(fd)
        text = extract(Path(tmp), ext)
    finally:
        os.unlink(tmp)
    if not (text or "").strip():
        raise ValueError("No text could be read from this file.")
    sha = hashlib.sha256(data).hexdigest()
    con.execute("INSERT INTO mail_attachments (item_id, graph_id, name, size, is_inline, kind, sha256, text) VALUES (?,?,?,?,0,'added',?,?) "
                "ON CONFLICT(item_id, graph_id) DO UPDATE SET name=excluded.name, text=excluded.text",
                (item_id, f"sam:{sha[:32]}", name, len(data), sha, mailsync.mask(text, attachment=True)))
    con.commit()
    return con.execute("SELECT id FROM mail_attachments WHERE item_id=? AND graph_id=?", (item_id, f"sam:{sha[:32]}")).fetchone()[0]


def remove_file(con, item_id, att_id):
    """Take back a file Sam added (only those: real attachments stay)."""
    n = con.execute("DELETE FROM mail_attachments WHERE id=? AND item_id=? AND kind='added'", (att_id, item_id)).rowcount
    con.commit()
    return n
