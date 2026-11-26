"""New emails started from an initiative's page (assist/initiative_work.py; Sam, 29 Oct 2026): the draft keeps the
initiative it is about and the items Sam picked for it, so every rewrite reads the initiative's context. Idempotent."""


def up(con):
    from .. import new_mail
    new_mail.ensure_schema(con)
    have = {r[1] for r in con.execute("PRAGMA table_info(mail_drafts)")}
    if "initiative_id" not in have:
        con.execute("ALTER TABLE mail_drafts ADD COLUMN initiative_id INTEGER")
    if "focus_json" not in have:
        con.execute("ALTER TABLE mail_drafts ADD COLUMN focus_json TEXT")
