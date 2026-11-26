"""Task history (assist/task_history.py, Sam, 23 Oct 2026): the tasks Sam would have had, rebuilt from what he did, kept
RETENTION_DAYS like the material they come from."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS history_tasks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  title         TEXT NOT NULL,
  done_when     TEXT,                       -- the outcome the actions were working towards
  initiative_id INTEGER,                    -- or an area (tasks.AREAS), never both
  area          TEXT,
  kind          TEXT,                       -- tasks.KINDS: what the work mostly was
  started_at    TEXT,                       -- first action
  finished_at   TEXT,                       -- last action (retention counts from here)
  status        TEXT NOT NULL DEFAULT 'done',   -- done | removed (Sam: not a task)
  edited        INTEGER DEFAULT 0,          -- 1 once Sam renamed, merged, split, moved or removed it: his call, kept on rebuilds
  people_json   TEXT,                       -- names of the people in its actions, most frequent first
  week          TEXT,                       -- the week it was first built in (YYYY-MM-DD, a Monday)
  run_id        INTEGER,
  created_at    TEXT NOT NULL,
  updated_at    TEXT
);
CREATE TABLE IF NOT EXISTS history_steps (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id       INTEGER NOT NULL REFERENCES history_tasks(id) ON DELETE CASCADE,
  title         TEXT NOT NULL,
  kind          TEXT,
  owner         TEXT,                       -- NULL: Sam; else who it was handed to
  position      INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history_actions (
  ref           TEXT PRIMARY KEY,           -- action_profile.actions ref: mail-12, chat-34, meeting-5, event-9, doc-7, decision-3, loop-8
  task_id       INTEGER REFERENCES history_tasks(id) ON DELETE CASCADE,   -- NULL: read and judged not part of a task
  step_id       INTEGER REFERENCES history_steps(id) ON DELETE SET NULL,
  key           TEXT,                       -- its action type (action_profile.CATALOGUE)
  ts            TEXT,
  label         TEXT,
  url           TEXT,
  item_id       INTEGER
);
CREATE INDEX IF NOT EXISTS history_actions_task ON history_actions(task_id, ts);
CREATE TABLE IF NOT EXISTS history_weeks (
  week          TEXT PRIMARY KEY,           -- Monday, London time
  status        TEXT NOT NULL,              -- ok | error
  actions       INTEGER,
  tasks         INTEGER,
  run_id        INTEGER,
  error         TEXT,
  created_at    TEXT NOT NULL
);
"""


def up(con):
    con.executescript(SCHEMA)
