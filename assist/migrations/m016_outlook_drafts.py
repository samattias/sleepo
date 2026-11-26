"""Reply drafts SleePO saved into Sam's Outlook (assist/outlook_drafts.py): one per email and kind of reply, so saving
again updates the same draft instead of making another."""


def up(con):
    con.execute("""CREATE TABLE IF NOT EXISTS outlook_drafts (
      item_id    INTEGER NOT NULL REFERENCES items(id),   -- the email it answers
      mode       TEXT NOT NULL,                           -- reply | replyall | followup | forward
      draft_id   TEXT NOT NULL,                           -- the draft's Microsoft Graph id
      web_link   TEXT,
      quote      TEXT,                                    -- the reply body Outlook made (the quoted email), to rebuild on a later save
      created_at TEXT NOT NULL, updated_at TEXT,
      PRIMARY KEY (item_id, mode))""")
