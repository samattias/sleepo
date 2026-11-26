"""The product roadmap snapshot: one row per initiative of Rowan Lowell's Roadmap Workbook workbook (assist/roadmap.py)."""


def up(con):
    from ..roadmap import SCHEMA
    con.executescript(SCHEMA)
