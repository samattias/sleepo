"""Mail, chat and meeting notes SleePO has already matched against Sam's tasks (assist/task_links.py), so each is read
by the model once. The links themselves live in mentions (entity_type 'task')."""


def up(con):
    con.execute("""CREATE TABLE IF NOT EXISTS task_link_checks (
      item_id    INTEGER PRIMARY KEY REFERENCES items(id),
      task_id    INTEGER,          -- the task it matched, or NULL
      checked_at TEXT NOT NULL)""")
