"""New emails Sam writes in SleePO (the Inbox's Drafts folder, assist/new_mail.py; Sam, 26 Oct 2026). One row per draft: who
it goes to, the subject and text, what he asked for, the version before the last revision (for the redline), the Outlook
draft it was saved as, and whether it went out. Kept RETENTION_DAYS. Idempotent."""


def up(con):
    from .. import new_mail
    new_mail.ensure_schema(con)
