"""A new database gets the core sources (db.CORE_SOURCES), so its first ingest does not fail the pulls' foreign key
(16 Nov 2026: sources were only ever created by import-legacy from a local file). An existing database is left as it is."""


def up(con):
    from .. import db
    if con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]:
        return
    for s in db.CORE_SOURCES:
        db.ensure_source(con, s["id"])
