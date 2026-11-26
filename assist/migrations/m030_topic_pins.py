"""Top of mind topics Sam pins, and new emails started from a topic's page (assist/topics.py, assist/initiative_work.py;
Sam, 29 Oct 2026: "I want to be able to pin these ... and unpin them based on what's important at the moment"). Idempotent."""


def up(con):
    from .. import new_mail, topics
    topics.ensure_schema(con)   # adds topics.pinned_at
    new_mail.ensure_schema(con)
    if "topic_id" not in {r[1] for r in con.execute("PRAGMA table_info(mail_drafts)")}:
        con.execute("ALTER TABLE mail_drafts ADD COLUMN topic_id INTEGER")
