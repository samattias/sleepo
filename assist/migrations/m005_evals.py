"""Results of offline evaluations (assist/evals.py): one row per case, grouped by run."""


def up(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS evals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run TEXT NOT NULL, kind TEXT NOT NULL, target TEXT, metrics TEXT, created_at TEXT
    );
    CREATE INDEX IF NOT EXISTS evals_run ON evals(run);
    """)
