"""What the assistant drafted (reply drafts, prep briefs), so it can be compared with what Sam actually sent or kept.

assist/feedback.py reads it to show the drafting prompts how Sam changed earlier drafts, and purges rows after 30 days
(the org's retention rule for derived personal data).
"""


def up(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS drafts (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      kind            TEXT NOT NULL,      -- reply | prep
      target_id       TEXT NOT NULL,      -- mail item id (reply) or calendar event id (prep)
      conversation_id TEXT,               -- mail thread, to find what Sam sent after the draft
      body            TEXT,
      prompt_version  TEXT,
      model           TEXT,
      checks          TEXT,               -- JSON: what the post-generation checks removed or flagged
      created_at      TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS drafts_kind ON drafts(kind, created_at);
    """)
