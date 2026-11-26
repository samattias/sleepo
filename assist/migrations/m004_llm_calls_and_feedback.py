"""Tables for the single model runner (assist/llm.py) and for Sam's feedback on what agents produce."""


def up(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS llm_calls (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      purpose TEXT, model TEXT, started_at TEXT, finished_at TEXT, secs REAL,
      cost_usd REAL, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
      prompt_chars INTEGER, output_chars INTEGER, ok INTEGER, error TEXT
    );
    CREATE INDEX IF NOT EXISTS llm_calls_started ON llm_calls(started_at);
    CREATE TABLE IF NOT EXISTS feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      target_type TEXT NOT NULL,          -- action | brief | prep | reply | ...
      target_id TEXT NOT NULL,
      rating INTEGER,                     -- 1 useful, -1 not useful
      copied INTEGER,                     -- 1 when the text was copied
      edit_ratio REAL,                    -- share of the text Sam changed before copying (0..1)
      note TEXT,
      created_at TEXT
    );
    CREATE INDEX IF NOT EXISTS feedback_target ON feedback(target_type, target_id);
    """)
