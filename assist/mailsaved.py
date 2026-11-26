"""Oversized mail for /mail-full: when read_resource saves a message to a file instead of showing it, turn the saved Graph
message into a mail-full record here, so the headless pull never needs an ad-hoc script (which its permissions block).

  assist mail-saved <inbox|sent> <saved-file>...   -> inbox/queue/mailfull-<date>-<folder>-saved-<NN>.json, then ingest it

Bodies are converted, never summarised; the caps match the skill. The saved files are deleted after a successful write."""
import json
import re
from datetime import date
from pathlib import Path

from . import db
from . import org
from .chatsync import html_to_text

AUTOMATED = re.compile(r"no-?reply|notifications?@|gitlab|jira|atlassian|sharepoint|teams@|slack" + org.alt("noise_senders"), re.I)


def _addr(x):
    e = (x or {}).get("emailAddress") or x or {}
    return {"name": e.get("name") or "", "address": e.get("address") or ""}


def _load(path):
    raw = Path(path).read_text(errors="replace")
    try:
        d = json.loads(raw)
    except ValueError:
        i = raw.find("{")
        d = json.loads(raw[i:]) if i >= 0 else {}
    if isinstance(d, list):   # [{"type":"text","text":"{...}"}]
        d = json.loads(next((c.get("text") for c in d if isinstance(c, dict) and c.get("text")), "{}"))
    return d


def record(msg, folder):
    body = msg.get("body") or {}
    text = body.get("content") or ""
    if (body.get("contentType") or "").lower() == "html":
        text = re.sub(r"<(style|script|head)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
        text = html_to_text(text)
    sender = _addr(msg.get("from") or msg.get("sender"))
    cap = 2000 if AUTOMATED.search(sender["address"] + " " + sender["name"]) else 15000
    if len(text) > cap:
        text = text[:cap] + "\n[truncated — open in Outlook for the rest]"
    atts = [{"id": a.get("id"), "name": a.get("name"), "content_type": a.get("contentType"), "size": a.get("size"),
             "is_inline": bool(a.get("isInline")), "text": None} for a in (msg.get("attachments") or []) if not a.get("isInline")]
    return {"graph_id": msg["id"], "folder": folder, "subject": msg.get("subject") or "", "from": sender,
            "to": [_addr(x) for x in msg.get("toRecipients") or []], "cc": [_addr(x) for x in msg.get("ccRecipients") or []],
            "bcc": [_addr(x) for x in msg.get("bccRecipients") or []], "received_at": msg.get("receivedDateTime"),
            "sent_at": msg.get("sentDateTime"), "conversation_id": msg.get("conversationId"),
            "internet_message_id": msg.get("internetMessageId"), "web_link": msg.get("webLink"),
            "importance": msg.get("importance"), "is_read": msg.get("isRead"), "body_text": text, "attachments": atts}


def build(folder, paths):
    if folder not in ("inbox", "sent"):
        raise SystemExit("folder must be inbox or sent")
    recs, bad = [], []
    for p in paths:
        try:
            m = _load(p)
            recs.append(record(m, folder))
        except (OSError, ValueError, KeyError) as e:
            bad.append(f"{Path(p).name}: {e}")
    q = db.ASSIST / "inbox" / "queue"
    q.mkdir(parents=True, exist_ok=True)
    n = 1
    while (q / f"mailfull-{date.today().isoformat()}-{folder}-saved-{n:02d}.json").exists():
        n += 1
    out = q / f"mailfull-{date.today().isoformat()}-{folder}-saved-{n:02d}.json"
    if recs:
        out.write_text(json.dumps({"agent": "claude-code:mail-full", "prompt_version": "mail-full-2026-10", "mail_messages": recs}))
        for p in paths:
            if not any(b.startswith(Path(p).name + ":") for b in bad):
                Path(p).unlink(missing_ok=True)
    return (out if recs else None), len(recs), bad
