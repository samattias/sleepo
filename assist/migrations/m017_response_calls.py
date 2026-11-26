"""Needs response, not just needs reply (Sam, 22 Oct 2026). response_calls: SleePO's read of mail the rule left out
(group mail, mail addressed to someone else) on whether it still needs a response from Sam, and which: reply, reply all,
forward (to whom) or none. reply_predrafts gains the response the draft chose, its recipients and why."""


def up(con):
    con.execute("""CREATE TABLE IF NOT EXISTS response_calls (
      item_id        INTEGER PRIMARY KEY REFERENCES items(id),
      response       TEXT NOT NULL,      -- none | reply | replyall | forward
      recipients     TEXT,               -- JSON list of addresses (forward: who to send it to)
      why            TEXT,
      model          TEXT, prompt_version TEXT,
      created_at     TEXT NOT NULL)""")
    have = {r[1] for r in con.execute("PRAGMA table_info(reply_predrafts)")}
    for col in ("recipients", "why"):
        if col not in have:
            con.execute(f"ALTER TABLE reply_predrafts ADD COLUMN {col} TEXT")
