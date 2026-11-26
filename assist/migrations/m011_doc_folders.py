"""Document folders (assist/documents.py): the initiative(s), type and sensitivity each document is filed under, by Sam or
by the filing pass, so the Documents page can show folders."""


def up(con):
    from ..documents import ensure_schema
    ensure_schema(con)
