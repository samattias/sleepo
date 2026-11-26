"""Pre-drafted replies (assist/replies.py predraft): one recommended reply per email waiting on Sam, written in the
background so the Inbox composer opens with it. Kept 30 days, like every other draft."""


def up(con):
    con.execute("""CREATE TABLE IF NOT EXISTS reply_predrafts (
      item_id        INTEGER PRIMARY KEY REFERENCES items(id),   -- the email it answers
      status         TEXT NOT NULL,                                -- ok | error
      subject        TEXT, body TEXT, notes TEXT,
      mode           TEXT, length INTEGER,
      prompt_version TEXT, model TEXT, error TEXT,
      tries          INTEGER DEFAULT 1,
      created_at     TEXT NOT NULL)""")
