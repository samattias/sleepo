"""Mail from Apple Mail's local store: the fast path for Sam's Exchange mailbox (no Graph app consent needed, no Claude).

Apple Mail keeps the whole mailbox on disk: an SQLite index (~/Library/Mail/V*/MailData/Envelope Index) and one .emlx file
per message. Reading them needs Full Disk Access for the process (System Settings › Privacy & Security). Read only: we never
write to Apple Mail's files.

  Inbox and Sent Items, every message since DEFAULT_SINCE: an envelope (sender, recipients, date, subject) for the governance
  index. Messages inside the mail retention window (30 days): the full body and attachment text, through mailsync.store().
  Messages are matched to what the connector pulls stored by Message-ID, so both paths converge on one record.
"""
import email
import email.policy
import glob
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db, mailsync
from . import profile
from .retention import RETENTION_DAYS

FOLDER_OF_SOURCE = {"outlook.inbox": "inbox", "outlook.sent": "sentitems"}
FOLDER_OF = {"Inbox": "inbox", "Sent%20Items": "sentitems", "Sent Items": "sentitems"}
TEXT_EXTS = {"pdf", "docx", "pptx", "xlsx", "doc", "rtf", "txt", "csv", "md", "html", "htm"}
MAX_ATTACH_BYTES = 25 * 1024 * 1024


class NoAccess(Exception):
    pass


def index_path():
    paths = sorted(glob.glob(os.path.expanduser("~/Library/Mail/V*/MailData/Envelope Index")))
    if not paths:
        try:
            os.listdir(os.path.expanduser("~/Library/Mail"))
        except PermissionError:
            raise NoAccess("no Full Disk Access to ~/Library/Mail (System Settings › Privacy & Security › Full Disk Access)")
        raise NoAccess("Apple Mail has no mail store on this Mac")
    return paths[-1]


def mail_running():
    return subprocess.run(["/usr/bin/pgrep", "-x", "Mail"], capture_output=True).returncode == 0


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if epoch else None


def _emlx_files(root):
    """ROWID -> .emlx path, and ROWID -> {file name: path} for attachments Apple Mail downloaded separately
    (a ".partial.emlx" leaves them out; they sit in .../Attachments/<ROWID>/<part>/<name>)."""
    out, att = {}, {}
    for mbox in ("Inbox.mbox", "Sent Items.mbox"):
        for p in glob.glob(os.path.join(root, "*", mbox, "**", "*.emlx"), recursive=True):
            m = re.match(r"(\d+)(\.partial)?\.emlx$", os.path.basename(p))
            if m:
                out[int(m.group(1))] = p
        for p in glob.glob(os.path.join(root, "*", mbox, "**", "Attachments", "*", "*", "*"), recursive=True):
            parts = Path(p).parts
            if parts[-3].isdigit() and os.path.isfile(p):
                att.setdefault(int(parts[-3]), {})[parts[-1]] = p
    return out, att


def _read_emlx(path):
    raw = Path(path).read_bytes()
    nl = raw.index(b"\n")
    n = int(raw[:nl].strip())
    return email.message_from_bytes(raw[nl + 1:nl + 1 + n], policy=email.policy.default)


def _body(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if not part:
        return "", ""
    try:
        content = part.get_content()
    except Exception:
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if part.get_content_subtype() == "html":
        return mailsync.to_text(content, "html"), content
    return content, None


def _attachments(msg, with_text, saved=None):
    from .localfiles import extract
    out = []
    for i, part in enumerate(msg.iter_attachments()):
        name = part.get_filename() or f"attachment-{i + 1}"
        inline = (part.get("Content-Disposition") or "").lower().startswith("inline") and part.get_content_maintype() == "image"
        if inline:
            continue
        data = part.get_payload(decode=True)   # empty when the attachment is not inside the .emlx
        if not data and saved and name in saved:
            try:
                data = Path(saved[name]).read_bytes() if os.path.getsize(saved[name]) <= MAX_ATTACH_BYTES else None
            except OSError:
                data = None
        text = None
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if with_text and data and ext in TEXT_EXTS and len(data) <= MAX_ATTACH_BYTES:
            # extraction needs a file; a private temp file, deleted at once
            fd, tmp = tempfile.mkstemp(suffix="." + ext)
            try:
                os.write(fd, data); os.close(fd)
                text = extract(Path(tmp), ext)
            finally:
                os.unlink(tmp)
        out.append({"id": f"am{i + 1}:{name}"[:200], "name": name, "content_type": part.get_content_type(),
                    "size": len(data) if data else None, "is_inline": False, "text": mailsync.mask(text, attachment=True) if text else None,
                    "downloaded": bool(data)})
    return out


def _noise(frm, subject, rc, folder):
    """Same rule as the envelope loader: automated senders, calendar responses, mail only addressed to a mailbox forwarded to the user (the profile)."""
    from .replies import AUTOMATED, NOTIFICATION
    rcpts = [(x.get("address") or "").lower() for x in rc.get(0, []) + rc.get(1, [])]
    return bool(AUTOMATED.search(frm.get("address") or "")) or bool(NOTIFICATION.search(subject or "")) \
        or (folder == "inbox" and profile.forwarded_only(rcpts))


def _known(con):
    """(folder, Message-ID) -> (item_id, Graph id or None) for everything already stored. Per folder: a message Sam sends
    himself is in Inbox and Sent Items with the same Message-ID, and those are two records."""
    known = {}
    for r in con.execute("SELECT m.item_id, m.graph_id, m.internet_message_id, i.source_id FROM mail_messages m JOIN items i ON i.id=m.item_id "
                         "WHERE m.internet_message_id IS NOT NULL"):
        g = r["graph_id"] if r["graph_id"] and not r["graph_id"].startswith("am:") else None
        known[(FOLDER_OF_SOURCE[r["source_id"]], r["internet_message_id"].strip())] = (r["item_id"], g)
    for r in con.execute("SELECT id, source_id, external_id, json_extract(payload, '$.internet_message_id') AS imid FROM items "
                         "WHERE source_id IN ('outlook.inbox', 'outlook.sent') AND json_extract(payload, '$.internet_message_id') IS NOT NULL"):
        ext = r["external_id"] or ""
        g = ext[5:] if ext.startswith("mail:") and not ext.startswith("mail:am:") else None
        known.setdefault((FOLDER_OF_SOURCE[r["source_id"]], r["imid"].strip()), (r["id"], g))
    return known


def left_inbox(con, seen, newest, since, listed):
    """Unread mail SleePO holds in the Inbox that Apple Mail's Inbox no longer has (deleted, archived or moved there, or an
    invitation Exchange removed once answered) stops counting as unread, so the Inbox's Unread matches Mail's. seen: the
    Message-IDs in Mail's Inbox now; newest: Mail's newest Inbox message (anything later, Mail has not synced yet); listed:
    how many Mail lists. Guarded: nothing changes when Mail lists nothing or would drop more than a few at once (its index
    may be rebuilding). Returns how many were marked read, or None when the guard held."""
    if not listed or not newest:
        return None
    ids = [r[0] for r in con.execute(
        "SELECT m.item_id, m.internet_message_id FROM mail_messages m JOIN items i ON i.id=m.item_id "
        "WHERE i.source_id='outlook.inbox' AND m.is_read=0 AND m.internet_message_id IS NOT NULL AND m.received_at >= ? AND m.received_at <= ?",
        (since, newest)) if r[1].strip() not in seen]
    if len(ids) > max(25, listed // 10):
        return None
    con.executemany("UPDATE mail_messages SET is_read=1 WHERE item_id=?", [(i,) for i in ids])
    return len(ids)


def read_elsewhere(con, days=30):
    """Unread mail SleePO holds in the Inbox that Apple Mail has read, or has moved out of its Inbox (Deleted Items, an
    archive folder: Outlook moves a meeting request or cancellation there once the calendar has taken it), stops counting
    as unread (Sam, 26 Oct 2026: a morning of work-trip invitations stayed unread). Direct evidence from Mail's index, so
    unlike left_inbox it needs no guard and no "newest" cut-off (those invitations arrived after the newest message left in
    the Inbox, which made left_inbox treat them as not synced yet). A message Mail does not know is left alone.
    Returns how many were marked read."""
    import sqlite3
    since = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute("SELECT m.item_id, m.internet_message_id FROM mail_messages m JOIN items i ON i.id=m.item_id "
                       "WHERE i.source_id='outlook.inbox' AND m.is_read=0 AND m.internet_message_id IS NOT NULL AND m.received_at >= ?",
                       (since,)).fetchall()
    if not rows:
        return 0
    try:
        ix = sqlite3.connect(f"file:{index_path()}?mode=ro", uri=True)
    except Exception:
        return 0
    seen = {}   # bare Message-ID -> [(mailbox url, read)]
    try:
        bare = [(r[1] or "").strip().strip("<>") for r in rows]
        for k in range(0, len(bare), 300):
            chunk = [x for b in bare[k:k + 300] if b for x in (b, f"<{b}>")]
            if not chunk:
                continue
            q = ",".join("?" * len(chunk))
            for mid, url, read in ix.execute(
                    "SELECT g.message_id_header, mb.url, m.read FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox "
                    f"JOIN message_global_data g ON g.ROWID = m.global_message_id WHERE m.deleted = 0 AND g.message_id_header IN ({q})", chunk):
                seen.setdefault((mid or "").strip("<>"), []).append((url or "", read))
    except sqlite3.Error:
        return 0
    finally:
        ix.close()
    inbox = re.compile(r"/inbox/?$", re.I)
    done = [iid for (iid, imid) in rows
            if any(read or not inbox.search(url) for url, read in seen.get((imid or "").strip().strip("<>"), []))]
    con.executemany("UPDATE mail_messages SET is_read=1 WHERE item_id=?", [(i,) for i in done])
    return len(done)


def _checked_path():
    return db.db_path().parent / "jobs" / "mail_checked"


def checked():
    """When Apple Mail was last read by a quiet run that found nothing to store (ISO), or None."""
    try:
        return _checked_path().read_text().strip() or None
    except OSError:
        return None


def sync(con, since=None, force=False, log=print, quiet=False):
    """quiet (the Inbox's Refresh mail, also every 2 minutes while it is on screen): when nothing new came in, nothing changed
    between read and unread and a pull was recorded within the hour, write nothing at all. Every database write makes every
    open tab reload all its data (/api/events), so a no-change check every 2 minutes reloaded the whole app (assist-c3,
    26 Oct 2026). The check's time goes in a small file instead (checked()). The quick sync and the full refresh record their
    pulls as before: the full refresh reads them to know Apple Mail delivered."""
    t0 = time.time()
    idx = index_path()
    root = str(Path(idx).parent.parent)
    days = RETENTION_DAYS
    full_from = _iso(time.time() - days * 86400) if days else "1970-01-01T00:00:00Z"
    since = since or mailsync.DEFAULT_SINCE
    ix = __import__("sqlite3").connect(f"file:{idx}?mode=ro", uri=True)
    ix.row_factory = __import__("sqlite3").Row
    rows = ix.execute("""
        SELECT m.ROWID AS rid, mb.url AS mailbox, s.subject AS subject, COALESCE(m.subject_prefix, '') AS prefix, a.address AS from_address, a.comment AS from_name,
               m.date_sent, m.date_received, m.read, m.flagged, m.deleted, g.message_id_header AS imid, m.conversation_id
        FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox
        LEFT JOIN subjects s ON s.ROWID = m.subject LEFT JOIN addresses a ON a.ROWID = m.sender
        LEFT JOIN message_global_data g ON g.ROWID = m.global_message_id
        WHERE (mb.url LIKE '%/Inbox' OR mb.url LIKE '%/Sent\\%20Items' ESCAPE '\\') AND m.deleted = 0 AND m.date_received >= ?""",
        (datetime.strptime(since[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp(),)).fetchall()
    rcpt = {}
    for r in ix.execute("SELECT r.message, r.type, a.address, a.comment FROM recipients r JOIN addresses a ON a.ROWID = r.address ORDER BY r.message, r.position"):
        rcpt.setdefault(r["message"], {0: [], 1: [], 2: []}).setdefault(r["type"], []).append({"name": r["comment"] or "", "address": r["address"] or ""})
    newest = {k: _iso(v) for k, v in ix.execute("SELECT CASE WHEN mb.url LIKE '%/Inbox' THEN 'inbox' ELSE 'sentitems' END, MAX(m.date_received) FROM messages m "
                                                  "JOIN mailboxes mb ON mb.ROWID=m.mailbox WHERE mb.url LIKE '%/Inbox' OR mb.url LIKE '%/Sent\\%20Items' ESCAPE '\\' GROUP BY 1")}
    ix.close()
    files, saved = _emlx_files(root)
    known = _known(con)
    # already stored in full (an empty body is real: calendar replies and similar); --force re-reads them
    have_body = {r["item_id"] for r in con.execute("SELECT item_id FROM mail_messages")}
    running = mail_running()
    pulls = {f: db.start_pull(con, src, "assist mail-local", since, None, "Apple Mail local store (envelope index; full text inside retention)")
             for f, src in mailsync.FOLDERS.items()}
    stats = {f: {"listed": 0, "full": 0, "envelope": 0, "skipped": 0, "no_file": 0, "attachments_text": 0, "read_changed": 0} for f in mailsync.FOLDERS}
    seen = set()   # Message-IDs in Mail's Inbox now
    for r in rows:
        folder = FOLDER_OF.get(r["mailbox"].rsplit("/", 1)[-1])
        if not folder or not r["imid"]:
            continue
        st = stats[folder]; st["listed"] += 1
        imid = r["imid"].strip()
        if folder == "inbox":
            seen.add(imid)
        prev = known.get((folder, imid))
        gid = (prev[1] if prev and prev[1] else None) or "am:" + ("sent:" if folder == "sentitems" else "") + imid.strip("<>")
        rc = rcpt.get(r["rid"], {0: [], 1: [], 2: []})
        received, sent = _iso(r["date_received"]), _iso(r["date_sent"])
        ts = received if folder == "inbox" else (sent or received)
        subject = (r["prefix"] + (r["subject"] or "")).strip()
        frm = {"name": r["from_name"] or "", "address": r["from_address"] or ""}
        link = "message://%3c" + imid.strip("<>") + "%3e"
        if ts >= full_from:
            if prev and prev[0] in have_body and not force:
                # the read state changes after the first import: keep it in step with Mail (no write when unchanged)
                st["read_changed"] += con.execute("UPDATE mail_messages SET is_read=? WHERE item_id=? AND is_read IS NOT ?",
                                                  (int(bool(r["read"])), prev[0], int(bool(r["read"])))).rowcount
                st["skipped"] += 1; continue
            path = files.get(r["rid"])
            if not path:
                st["no_file"] += 1; continue
            msg = _read_emlx(path)
            text, _ = _body(msg)
            atts = _attachments(msg, with_text=True, saved=saved.get(r["rid"]))
            st["attachments_text"] += sum(1 for a in atts if a["text"])
            iid = mailsync.store_record(con, {"graph_id": gid, "folder": folder, "subject": subject, "from": frm, "to": rc.get(0, []), "cc": rc.get(1, []),
                                              "bcc": rc.get(2, []), "received_at": received, "sent_at": sent, "conversation_id": str(r["conversation_id"] or "") or None,
                                              "internet_message_id": imid, "web_link": link, "is_read": bool(r["read"]), "body_text": text,
                                              "attachments": atts}, pull_id=pulls[folder])
            if not prev and _noise(frm, subject, rc, folder):   # a message new to the database
                con.execute("UPDATE items SET noise=1 WHERE id=?", (iid,))
            known[(folder, imid)] = (iid, gid if not gid.startswith("am:") else None)
            have_body.add(iid)
            st["full"] += 1
        else:
            if prev:   # never rewrite a stored record from the envelope (it may carry triage, noise or an HR/legal retention flag)
                st["skipped"] += 1; continue
            src = mailsync.FOLDERS[folder]
            env = {"envelope": True, "folder": "inbox" if folder == "inbox" else "sent", "sender": frm["address"],
                   "recipients": [x["address"] for x in rc.get(0, []) + rc.get(1, [])], "received": received, "sent": sent,
                   "internet_message_id": imid, "source": "apple-mail"}
            iid, _ = db.upsert_item(con, src, "mail:" + gid, "mail" if folder == "inbox" else "sent", ts, pull_id=pulls[folder],
                                    from_name=frm["name"] or frm["address"], subject=subject or "(no subject)", text=None, url=link, payload=env,
                                    retention="envelope", noise=_noise(frm, subject, rc, folder), from_person_id=db.resolve_person(con, frm["address"]) or db.resolve_person(con, frm["name"]))
            known[(folder, imid)] = (iid, None)
            st["envelope"] += 1
        if (st["full"] + st["envelope"]) % 100 == 0:
            con.commit()
    # only while Mail runs: otherwise its store may be hours behind and "not in the Inbox" may just mean "not synced yet"
    gone = left_inbox(con, seen, newest.get("inbox"), datetime.strptime(since[:10], "%Y-%m-%d").strftime("%Y-%m-%dT00:00:00Z"),
                      stats["inbox"]["listed"]) if running else None
    if gone is None and running:
        log("!! Apple Mail lists too few Inbox messages to trust: read state of mail that left its Inbox left as it was")
    stats["inbox"]["left_inbox"] = (gone or 0) + read_elsewhere(con)   # and what Mail has read or moved out of its Inbox
    changed = any(st["full"] or st["envelope"] or st["read_changed"] or st.get("left_inbox") for st in stats.values())
    last = con.execute("SELECT MAX(finished_at) FROM pulls WHERE agent='assist mail-local'").fetchone()[0]
    if quiet and not changed and last and last > _iso(time.time() - 3600):
        con.rollback()   # the pull rows started above go too: no write
        _checked_path().parent.mkdir(parents=True, exist_ok=True)
        _checked_path().write_text(db.now())
        log(f"apple mail: nothing new ({stats['inbox']['listed']} in the Inbox, {stats['sentitems']['listed']} sent); nothing written; {time.time() - t0:.1f}s")
        return {"stats": stats, "newest": newest, "running": running, "secs": round(time.time() - t0, 1), "quiet": True}
    for f, pid in pulls.items():
        st = stats[f]
        stored = st["full"] + st["envelope"] + st["skipped"]
        # only "complete" when Apple Mail is running (otherwise its store may be hours behind the server)
        db.finish_pull(con, pid, available=st["listed"], pulled=st["full"] + st["envelope"], noise=None,
                       complete=1 if running and stored + st["no_file"] == st["listed"] else 0)
        con.execute("UPDATE pulls SET note=? WHERE id=?", (f"Apple Mail: {st['listed']} listed, {st['full']} full, {st['envelope']} envelope, {st['skipped']} unchanged"
                                                           + (f", {st['no_file']} without a local file" if st["no_file"] else "")
                                                           + (f", {st['read_changed']} read state updated" if st["read_changed"] else "")
                                                           + (f", {st['left_inbox']} no longer in Mail's Inbox (no longer unread)" if st.get("left_inbox") else "")
                                                           + f"; newest {newest.get(f)}" + ("" if running else "; Apple Mail is not running, so this may be behind"), pid))
    mailsync.purge(con, days, log)
    con.commit()
    for f, st in stats.items():
        log(f"{f}: {st['listed']} listed · {st['full']} full · {st['envelope']} envelope · {st['skipped']} unchanged · {st['no_file']} no file · "
            f"{st['attachments_text']} attachments with text · {st['read_changed']} read state updated"
            + (f" · {st['left_inbox']} left Mail's Inbox" if st.get("left_inbox") else "") + f" · newest {newest.get(f)}")
    if not running:
        log("!! Apple Mail is not running: open it so it keeps syncing, or this mail may be behind")
    log(f"apple mail: done in {time.time() - t0:.1f}s")
    return {"stats": stats, "newest": newest, "running": running, "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- the formatted original, read on demand
# The database keeps each message's text (inside the retention window). For reading, the app asks for the HTML part and
# its inline images straight from Apple Mail's .emlx, per view: they are served, never stored.
_FILES = {"at": 0.0, "files": {}, "saved": {}}


def _files(fresh=False):
    """_emlx_files, kept for five minutes so a page view does not walk the whole store."""
    if fresh or time.time() - _FILES["at"] > 300:
        _FILES["files"], _FILES["saved"] = _emlx_files(str(Path(index_path()).parent.parent))
        _FILES["at"] = time.time()
    return _FILES["files"], _FILES["saved"]


def _message(imid):
    """(parsed message, {attachment name: path}) for a Message-ID in Inbox or Sent Items, or (None, {})."""
    imid = (imid or "").strip()
    if not imid:
        return None, {}
    bare = imid.strip("<>")
    ix = __import__("sqlite3").connect(f"file:{index_path()}?mode=ro", uri=True)
    try:
        rids = [r[0] for r in ix.execute(
            "SELECT m.ROWID FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox JOIN message_global_data g ON g.ROWID = m.global_message_id "
            "WHERE g.message_id_header IN (?, ?, ?) AND m.deleted = 0 AND (mb.url LIKE '%/Inbox' OR mb.url LIKE '%/Sent\\%20Items' ESCAPE '\\')",
            (imid, bare, f"<{bare}>"))]
    finally:
        ix.close()
    if not rids:
        return None, {}
    for fresh in (False, True):   # a message newer than the cached file map: look again once
        files, saved = _files(fresh)
        for rid in rids:
            if rid in files:
                return _read_emlx(files[rid]), saved.get(rid) or {}
    return None, {}


def draft_link(remote_id):
    """Outlook on the web, opened on one item of Sam's Exchange mailbox: Apple Mail keeps the item's EWS id as remote_id."""
    from urllib.parse import quote
    return "https://outlook.office365.com/owa/?ItemID=" + quote(remote_id, safe="") + "&exvsurl=1&viewmodel=ReadMessageItem" if remote_id else ""


def drafts(con, limit=60):
    """Sam's drafts as Outlook keeps them (the Drafts folder Apple Mail syncs; Sam, 26 Oct 2026: the Inbox's Drafts folder
    mirrors it), newest first: [{key, subject, to, cc, ts, body, quoted, reply_to_item, reply_subject, web_link, attachments}].
    Read from Mail's store each time and never stored. body is Sam's own text (the quoted email under a reply is in quoted);
    reply_to_item is the email it answers when SleePO holds it. [] when Mail's store cannot be read."""
    import sqlite3
    from .replies import _own_text
    try:
        idx = index_path()
    except NoAccess:
        return []
    ix = sqlite3.connect(f"file:{idx}?mode=ro", uri=True)
    ix.row_factory = sqlite3.Row
    try:
        rows = ix.execute(
            "SELECT m.ROWID AS rid, s.subject AS subject, COALESCE(m.subject_prefix, '') AS prefix, m.date_received, m.date_sent, m.remote_id, "
            "mb.url AS mailbox FROM messages m JOIN mailboxes mb ON mb.ROWID = m.mailbox LEFT JOIN subjects s ON s.ROWID = m.subject "
            "WHERE mb.url LIKE '%/Drafts' AND m.deleted = 0 ORDER BY m.date_received DESC LIMIT ?", (limit,)).fetchall()
        rcpt = {}
        if rows:
            q = ",".join("?" * len(rows))
            for r in ix.execute(f"SELECT r.message, r.type, a.address, a.comment FROM recipients r JOIN addresses a ON a.ROWID = r.address "
                                f"WHERE r.message IN ({q}) ORDER BY r.message, r.position", [r["rid"] for r in rows]):
                rcpt.setdefault(r["message"], {0: [], 1: [], 2: []}).setdefault(r["type"], []).append({"name": r["comment"] or "", "address": r["address"] or ""})
    finally:
        ix.close()
    root = str(Path(idx).parent.parent)
    files = {}
    for p in glob.glob(os.path.join(root, "*", "Drafts.mbox", "**", "*.emlx"), recursive=True):
        m = re.match(r"(\d+)(\.partial)?\.emlx$", os.path.basename(p))
        if m:
            files[int(m.group(1))] = p
    by_imid = {}
    out = []
    for r in rows:
        text, irt, atts = "", "", []
        if r["rid"] in files:
            try:
                msg = _read_emlx(files[r["rid"]])
                text, _ = _body(msg)
                irt = (msg.get("In-Reply-To") or "").strip()
                atts = [part.get_filename() for part in msg.iter_attachments() if part.get_filename()
                        and not ((part.get("Content-Disposition") or "").lower().startswith("inline") and part.get_content_maintype() == "image")]
            except Exception:
                pass
        own = _own_text(text or "")
        at = (text or "").find(own) if own else -1
        rest = text[at + len(own):] if at >= 0 else ""
        rc = rcpt.get(r["rid"], {0: [], 1: []})
        d = {"key": f"am-{r['rid']}", "subject": (r["prefix"] + (r["subject"] or "")).strip(), "to": rc.get(0, []), "cc": rc.get(1, []),
             "ts": _iso(r["date_received"] or r["date_sent"]), "body": mailsync.mask(own.strip()),
             "quoted": mailsync.mask(rest.strip()) if len(rest.strip()) > 20 else "",
             "reply_to_item": None, "reply_subject": None, "web_link": draft_link(r["remote_id"]), "attachments": atts[:10]}
        if irt:
            by_imid.setdefault(irt, []).append(d)
        out.append(d)
    if by_imid:   # the email a draft answers, when SleePO holds it: the draft can be finished in its thread
        q = ",".join("?" * len(by_imid))
        for m in con.execute(f"SELECT item_id, subject, internet_message_id FROM mail_messages WHERE internet_message_id IN ({q}) "
                             "ORDER BY folder='inbox' DESC", list(by_imid)):
            for d in by_imid.get(m["internet_message_id"], []):
                if not d["reply_to_item"]:
                    d["reply_to_item"], d["reply_subject"] = m["item_id"], m["subject"]
    return out


def html_body(imid):
    """The message's HTML part as sent (masked like the stored text), or None when it is plain text or not in Apple Mail."""
    msg, _ = _message(imid)
    part = msg.get_body(preferencelist=("html",)) if msg else None
    if not part:
        return None
    try:
        content = part.get_content()
    except Exception:
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    return mailsync.mask(content)


def inline_part(imid, cid):
    """(bytes, content type) of the part with this Content-ID (an image inside the body), or None."""
    msg, saved = _message(imid)
    if not msg:
        return None
    for part in msg.walk():
        if (part.get("Content-ID") or "").strip().strip("<>") != cid or part.get_content_maintype() == "multipart":
            continue
        data = part.get_payload(decode=True)
        name = part.get_filename()
        if not data and name and name in saved and os.path.getsize(saved[name]) <= MAX_ATTACH_BYTES:
            data = Path(saved[name]).read_bytes()
        return (data, part.get_content_type()) if data else None
    return None
