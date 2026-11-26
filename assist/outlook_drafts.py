"""Reply drafts saved into Sam's Outlook, inside the email's own thread (Sam, 22 Oct 2026; this reverses the 7 Oct
"copy and paste only" rule for the Inbox's draft card, at his request). Nothing is ever sent.

SleePO holds Apple Mail's ids, so the email is first found in the mailbox through Microsoft Graph by its Message-ID.
Then Graph creates the reply (createReply / createReplyAll / createForward), which threads it and quotes the email; the
draft's text goes in above the quote, people added go in Cc (or To for a forward), and the draft's Outlook link comes
back for the app to open. Saving again updates the same draft while it is still a draft, instead of making another.

Sign-in: SleePO's own Graph sign-in (assist/mailsync.py: the Microsoft Graph Command Line Tools public client, token
cache in the Keychain), with Mail.ReadWrite on top of Mail.Read: `assist.cli outlook-login`, which Sam runs once.
"""
import html
import json
import re
import urllib.parse

from . import db, mailsync
from .retention import RETENTION_DAYS

SCOPES = ["Mail.ReadWrite"]
GRAPH = mailsync.GRAPH


class NotSignedIn(Exception):
    pass


def login():
    app, cache, f = mailsync._app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise SystemExit("could not start sign-in: " + json.dumps(flow, indent=2))
    print(flow["message"], flush=True)
    res = app.acquire_token_by_device_flow(flow)
    mailsync._save(cache, f)
    if "access_token" not in res:
        raise SystemExit("sign-in failed: " + (res.get("error_description") or json.dumps(res)))
    print("signed in; SleePO can now save reply drafts into your Outlook threads (it never sends)")


def token():
    app, cache, f = mailsync._app()
    acc = app.get_accounts()
    res = app.acquire_token_silent(SCOPES, account=acc[0]) if acc else None
    mailsync._save(cache, f)
    if not res or "access_token" not in res:
        raise NotSignedIn()
    return res["access_token"]


def _call(method, path, tok, body=None, params=None):
    import requests
    r = requests.request(method, path if path.startswith("http") else GRAPH + path, params=params, json=body, timeout=60,
                         headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "Prefer": 'outlook.body-content-type="html"'})
    if r.status_code == 401:
        raise NotSignedIn()
    if r.status_code >= 400:
        raise RuntimeError(f"Outlook said {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def message_ids(graph_id):
    """The Message-ID forms to look for: SleePO stores Apple Mail's 'am:<Message-ID without brackets>'."""
    raw = (graph_id or "").strip()
    if raw.startswith("am:"):
        raw = raw[3:]
    raw = raw.strip("<>")
    return [f"<{raw}>", raw] if raw else []


def find(tok, graph_id):
    """The mailbox message for a SleePO email: (id, webLink), or (None, None)."""
    for mid in message_ids(graph_id):
        q = "internetMessageId eq '" + mid.replace("'", "''") + "'"
        got = _call("GET", "/me/messages", tok, params={"$filter": q, "$select": "id,webLink,conversationId,parentFolderId", "$top": "5"}).get("value") or []
        if got:
            return got[0]["id"], got[0].get("webLink")
    return None, None


def to_html(text):
    """Plain draft text as simple HTML paragraphs (blank line = new paragraph)."""
    paras = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paras)


def _with_text(existing, text_html):
    """Put the draft's text at the top of the reply Outlook made (which holds the quoted email)."""
    m = re.search(r"<body[^>]*>", existing or "", re.I)
    block = f'<div data-sleepo="draft">{text_html}</div>'
    return existing[:m.end()] + block + existing[m.end():] if m else block + (existing or "")


def _recipients(addrs):
    return [{"emailAddress": {"address": a}} for a in addrs if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a or "")]


def save(con, item_id, body, mode="reply", add=None):
    """Create (or update) the reply draft in Outlook. Returns {"web_link", "updated"}."""
    m = con.execute("SELECT graph_id, subject FROM mail_messages WHERE item_id=?", (item_id,)).fetchone()
    if not m:
        raise ValueError("unknown email")
    tok = token()
    html_text = to_html(body)
    con.execute("DELETE FROM outlook_drafts WHERE created_at < datetime('now', ?)", (f"-{RETENTION_DAYS} days",))   # the quote is email text
    prev = con.execute("SELECT draft_id, quote FROM outlook_drafts WHERE item_id=? AND mode=?", (item_id, mode)).fetchone()
    if prev:   # update the same draft while it is still one (it may have been sent or deleted since): new text over the same quote
        try:
            d = _call("GET", f"/me/messages/{urllib.parse.quote(prev[0], safe='')}", tok, params={"$select": "id,isDraft,webLink"})
            if d.get("isDraft"):
                _call("PATCH", f"/me/messages/{urllib.parse.quote(prev[0], safe='')}", tok,
                      body={"body": {"contentType": "html", "content": _with_text(prev[1] or "", html_text)}})
                con.execute("UPDATE outlook_drafts SET updated_at=? WHERE item_id=? AND mode=?", (db.now(), item_id, mode))
                con.commit()
                return {"web_link": d.get("webLink"), "updated": True}
        except (RuntimeError, KeyError):
            pass
    mid, _ = find(tok, m["graph_id"])
    if not mid:
        raise LookupError("This email was not found in your Outlook mailbox (it may have been moved or deleted).")
    action = {"reply": "createReply", "replyall": "createReplyAll", "followup": "createReplyAll", "forward": "createForward"}.get(mode, "createReply")
    extra = _recipients(add or [])
    if mode == "forward" and not extra:
        raise ValueError("Add who to forward it to (email addresses).")
    d = _call("POST", f"/me/messages/{urllib.parse.quote(mid, safe='')}/{action}", tok, body={})
    quote = (d.get("body") or {}).get("content", "")
    patch = {"body": {"contentType": "html", "content": _with_text(quote, html_text)}}
    if mode == "forward":
        patch["toRecipients"] = extra
    elif extra:
        patch["ccRecipients"] = (d.get("ccRecipients") or []) + extra
    d2 = _call("PATCH", f"/me/messages/{urllib.parse.quote(d['id'], safe='')}", tok, body=patch)
    con.execute("INSERT OR REPLACE INTO outlook_drafts (item_id, mode, draft_id, web_link, quote, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (item_id, mode, d["id"], d2.get("webLink") or d.get("webLink"), quote, db.now(), db.now()))
    con.commit()
    return {"web_link": d2.get("webLink") or d.get("webLink"), "updated": False}


def link(con, item_id):
    """The original email's Outlook link (to open the thread in Outlook), found by its Message-ID."""
    m = con.execute("SELECT graph_id FROM mail_messages WHERE item_id=?", (item_id,)).fetchone()
    if not m:
        raise ValueError("unknown email")
    _, web = find(token(), m["graph_id"])
    if not web:
        raise LookupError("This email was not found in your Outlook mailbox.")
    return web


def save_new(con, to, cc, subject, body, draft_id=None):
    """A new email (not a reply) as a draft in Sam's Outlook Drafts, for a task's email step (assist/tasks.py to_outlook;
    Sam, 22 Oct 2026). Saving again updates the same draft while it is still one. Never sends. Returns {"id", "web_link"}."""
    tok = token()
    msg = {"subject": (subject or "").strip()[:250], "body": {"contentType": "html", "content": to_html(body)},
           "toRecipients": _recipients(to or []), "ccRecipients": _recipients(cc or [])}
    if draft_id:
        try:
            d = _call("GET", f"/me/messages/{urllib.parse.quote(draft_id, safe='')}", tok, params={"$select": "id,isDraft,webLink"})
            if d.get("isDraft"):
                d2 = _call("PATCH", f"/me/messages/{urllib.parse.quote(draft_id, safe='')}", tok, body=msg)
                return {"id": draft_id, "web_link": d2.get("webLink") or d.get("webLink")}
        except (RuntimeError, KeyError):
            pass
    d = _call("POST", "/me/messages", tok, body=msg)   # lands in Drafts
    return {"id": d["id"], "web_link": d.get("webLink")}
