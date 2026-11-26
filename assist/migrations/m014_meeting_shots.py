"""Granola screenshots of the shared screen (assist/granola_shots.py): one row per screenshot, linked to the meeting.
The image file is deleted 30 days after capture (file and thumb set to NULL, purged_at set); the description stays."""


def up(con):
    con.execute("""CREATE TABLE IF NOT EXISTS meeting_shots (
      id             TEXT PRIMARY KEY,                     -- Granola's attachment id
      granola_meeting TEXT NOT NULL,                       -- Granola's meeting id (the UUID in the note URL)
      note_item_id   INTEGER REFERENCES items(id),
      meeting_id     INTEGER REFERENCES meetings(id),      -- NULL until the note has a meeting
      captured_at    TEXT NOT NULL,                        -- ISO 8601 UTC
      description    TEXT,                                 -- Granola's machine description (lossy)
      retention      TEXT DEFAULT 'general',               -- the note's: general | commercial | hr_legal
      file           TEXT, thumb TEXT, mime TEXT,
      width          INTEGER, height INTEGER, bytes INTEGER,
      tries          INTEGER,                              -- failed image fetches
      created_at     TEXT, fetched_at TEXT, purged_at TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS meeting_shots_meeting ON meeting_shots(meeting_id, captured_at)")
    con.execute("CREATE INDEX IF NOT EXISTS meeting_shots_granola ON meeting_shots(granola_meeting)")
