"""Open items that look like the same thing (assist/loops.py flag): which older item a loop seems to repeat (dup_of), and
the items Sam said are different (distinct_from, JSON list of loop ids), so the flag does not come back."""


def up(con):
    have = {r[1] for r in con.execute("PRAGMA table_info(loops)")}
    if "dup_of" not in have:
        con.execute("ALTER TABLE loops ADD COLUMN dup_of INTEGER")
    if "distinct_from" not in have:
        con.execute("ALTER TABLE loops ADD COLUMN distinct_from TEXT")
