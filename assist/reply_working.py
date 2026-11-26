"""The reply Sam is working on for an email, kept so it survives leaving the email (Sam, 22 Oct 2026: a draft taken back from
the chat with Use in reply, or his own edits in the composer, came back as the old recommended reply after navigating away).

One row per email: the text in the Inbox's composer, its reply mode, and where it last came from (chat: Use in reply; edit:
Sam typing or a regenerate). The composer loads it ahead of the recommended reply (assist/replies.py predraft). Email-derived
text: kept RETENTION_DAYS (assist/retention.py), like the pre-drafts. Nothing is sent.
"""
from datetime import datetime, timedelta, timezone

from . import db
from .retention import RETENTION_DAYS

SCHEMA = """CREATE TABLE IF NOT EXISTS reply_working (
  item_id    INTEGER PRIMARY KEY,   -- the email being answered
  body       TEXT NOT NULL,
  mode       TEXT,                  -- reply | replyall | followup | forward
  source     TEXT,                  -- chat (Use in reply) | edit (the composer) | generated (a draft he asked for, kept by the job)
  updated_at TEXT NOT NULL
)"""


def ensure_schema(con):
    con.execute(SCHEMA)


def get(con, item_id):
    ensure_schema(con)
    cut = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con.execute("DELETE FROM reply_working WHERE updated_at < ?", (cut,))
    r = con.execute("SELECT * FROM reply_working WHERE item_id=?", (item_id,)).fetchone()
    return dict(r) if r else None


def put(con, item_id, body, mode=None, source="edit"):
    ensure_schema(con)
    if not (body or "").strip():
        con.execute("DELETE FROM reply_working WHERE item_id=?", (item_id,))
    else:
        con.execute("INSERT INTO reply_working (item_id, body, mode, source, updated_at) VALUES (?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET "
                    "body=excluded.body, mode=COALESCE(excluded.mode, reply_working.mode), source=excluded.source, updated_at=excluded.updated_at",
                    (item_id, body[:20000], mode if mode in ("reply", "replyall", "followup", "forward") else None,
                     source if source in ("chat", "edit", "generated") else "edit", db.now()))
    con.commit()
