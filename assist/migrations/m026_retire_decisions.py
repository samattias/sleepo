"""Decisions retired (Sam, 26 Oct 2026). The decisions extracted from mail and meetings were a log nobody read (only the
Explore graph and search showed them) and some were facts rather than decisions. What Sam has to decide is a task or a
"decide" step in Tasks; what he decided shows in the task's closed steps and in Tasks › History.

The rows move to decisions_retired (with their sources and links, so it can be undone), and the live tables are emptied,
so nothing reads them any more. Open items made from a pending decision stay: they are already suggested tasks.
Idempotent."""


def up(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'").fetchone():
        return
    con.execute("CREATE TABLE IF NOT EXISTS decisions_retired AS SELECT * FROM decisions WHERE 0")
    con.execute("CREATE TABLE IF NOT EXISTS decision_sources_retired AS SELECT * FROM fact_sources WHERE 0")
    con.execute("CREATE TABLE IF NOT EXISTS decision_mentions_retired AS SELECT * FROM mentions WHERE 0")
    con.execute("INSERT INTO decisions_retired SELECT * FROM decisions")
    con.execute("INSERT INTO decision_sources_retired SELECT * FROM fact_sources WHERE fact_type='decision'")
    con.execute("INSERT INTO decision_mentions_retired SELECT * FROM mentions WHERE ref_type='decision'")
    con.execute("DELETE FROM fact_sources WHERE fact_type='decision'")
    con.execute("DELETE FROM mentions WHERE ref_type='decision'")
    con.execute("DELETE FROM decisions")
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='search_fts'").fetchone():
        con.execute("DELETE FROM search_fts WHERE kind='decision'")
