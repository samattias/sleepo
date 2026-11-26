"""Rows that hang off an item go with it (22 Oct 2026). m014-m018 declared `REFERENCES items(id)` with no ON DELETE, and
db.connect turns foreign keys on, so the 30-day purges (chatsync.purge, mailsync, claudelog, localfiles) failed with
"FOREIGN KEY constraint failed" on any item a screenshot, pre-draft, Outlook draft, response check or task-link check
pointed at. Each table is rebuilt with ON DELETE CASCADE on its item columns (SET NULL on meeting_shots.meeting_id),
keeping its rows and indexes. Idempotent: a table already rebuilt is left alone."""
import re

TABLES = ("meeting_shots", "reply_predrafts", "outlook_drafts", "response_calls", "task_link_checks")


def up(con):
    for t in TABLES:
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        if not row or "ON DELETE" in row[0]:
            continue
        sql = re.sub(r"REFERENCES items\(id\)", "REFERENCES items(id) ON DELETE CASCADE", row[0])
        sql = re.sub(r"REFERENCES meetings\(id\)", "REFERENCES meetings(id) ON DELETE SET NULL", sql)
        sql = re.sub(r"CREATE TABLE (IF NOT EXISTS )?\"?" + t + r"\"?", f"CREATE TABLE {t}__new", sql, count=1)
        indexes = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (t,))]
        cols = ", ".join(f'"{r[1]}"' for r in con.execute(f"PRAGMA table_info({t})"))
        con.execute(sql)
        con.execute(f"INSERT INTO {t}__new ({cols}) SELECT {cols} FROM {t}")
        con.execute(f"DROP TABLE {t}")
        con.execute(f"ALTER TABLE {t}__new RENAME TO {t}")
        for ix in indexes:
            con.execute(ix)
