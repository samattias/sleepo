"""Timestamps in one form: UTC as YYYY-MM-DDTHH:MM:SSZ.

Converts only unambiguous forms (fractional seconds with Z, or an explicit +00:00 offset). Times without a zone are left
untouched: guessing them caused the BST-labelled-as-UTC bug. Covers items.ts, meetings.starts_at/ends_at and the loops dates.
"""


def _canon(col):
    # 2026-10-05T16:33:50.336Z -> 2026-10-05T16:33:50Z ; 2026-10-05T16:33:50+00:00 -> 2026-10-05T16:33:50Z
    return (f"CASE WHEN {col} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].*Z' "
            f"OR {col} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00' "
            f"THEN substr({col}, 1, 19) || 'Z' ELSE {col} END")


def up(con):
    targets = [("items", "ts"), ("meetings", "starts_at"), ("meetings", "ends_at")]
    cols = {r[1] for r in con.execute("PRAGMA table_info(loops)")}
    targets += [("loops", c) for c in ("origin_at", "closed_at", "updated_at", "due") if c in cols]
    for table, col in targets:
        con.execute(f"UPDATE {table} SET {col} = {_canon(col)} WHERE {col} IS NOT NULL AND {col} <> {_canon(col)}")
