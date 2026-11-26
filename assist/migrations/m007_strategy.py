"""Strategy memos written by the strategy agent (assist/strategy.py), with Sam's marks (pinned, discussed, dismissed)."""


def up(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS strategy_memos (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at  TEXT NOT NULL,
      memo_json   TEXT NOT NULL,     -- {headline, thoughts: [...], watch: [...]}
      refs_json   TEXT,              -- evidence code -> {label, url}
      marks_json  TEXT,              -- thought index -> pinned | discussed | dismissed
      run_id      INTEGER
    );
    """)
