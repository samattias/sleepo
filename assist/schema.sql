-- Assist · system of record (SQLite). Applied by assist/db.py; versioned by schema_version.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL);

-- Where data comes from. One row per system/stream the assistant reads.
CREATE TABLE IF NOT EXISTS sources (
  id            TEXT PRIMARY KEY,              -- 'granola', 'outlook.inbox', 'outlook.sent', 'teams', 'slack', 'calendar', 'jira'
  system        TEXT NOT NULL,                 -- 'granola', 'outlook', 'calendar', 'teams', 'slack', 'jira', 'sharepoint', 'salesforce'
  name          TEXT NOT NULL,
  vendor        TEXT,
  kind          TEXT,
  how           TEXT,
  auth          TEXT,
  connect       TEXT,
  color         TEXT,
  mono          TEXT,
  logo          TEXT,
  health        TEXT DEFAULT 'planned',        -- ok | stale | broken | capped | planned
  last_pull_at  TEXT,
  window_from   TEXT,
  window_to     TEXT,
  cursor        TEXT,
  note          TEXT,
  sort          INTEGER DEFAULT 100
);

-- Every pull: what window, how many, by whom. The audit of "did it see everything".
CREATE TABLE IF NOT EXISTS pulls (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id     TEXT NOT NULL REFERENCES sources(id),
  window_from   TEXT, window_to TEXT,
  available     INTEGER, pulled INTEGER, noise INTEGER,
  complete      INTEGER DEFAULT 1,             -- 1 = paginated to the end
  agent         TEXT,                          -- 'claude-code', 'granola_update.py', 'assist ingest'
  note          TEXT,
  started_at    TEXT, finished_at TEXT
);

-- Raw items: one row per mail, message, event, note. Idempotent on (source_id, external_id).
CREATE TABLE IF NOT EXISTS items (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id     TEXT NOT NULL REFERENCES sources(id),
  external_id   TEXT NOT NULL,
  kind          TEXT NOT NULL,                 -- mail | sent | chat | channel | event | note
  ts            TEXT NOT NULL,                 -- ISO 8601 UTC
  from_person_id INTEGER REFERENCES people(id),
  from_name     TEXT,
  subject       TEXT,
  text          TEXT,                          -- gist, summary or body as allowed by retention_class
  thread        TEXT,                          -- chat / channel / thread description or id
  url           TEXT,
  payload       TEXT,                          -- JSON, full record when kept (Granola notes, calendar events)
  payload_hash  TEXT,
  retention     TEXT DEFAULT 'general',        -- general | commercial | hr_legal
  noise         INTEGER DEFAULT 0,
  pull_id       INTEGER REFERENCES pulls(id),
  pulled_at     TEXT NOT NULL,
  UNIQUE(source_id, external_id)
);
CREATE INDEX IF NOT EXISTS items_ts ON items(ts);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind, ts);

-- Resolved identities. Aliases carry every spelling and address seen.
CREATE TABLE IF NOT EXISTS people (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  role          TEXT,
  org_id        INTEGER REFERENCES orgs(id),
  relationship  TEXT,
  is_me         INTEGER DEFAULT 0,
  profile_md    TEXT,                          -- the memory/people file, kept as the human-readable profile
  updated_at    TEXT
);
CREATE TABLE IF NOT EXISTS people_aliases (
  alias         TEXT PRIMARY KEY,              -- lower-cased name variant or e-mail
  person_id     INTEGER NOT NULL REFERENCES people(id)
);
CREATE TABLE IF NOT EXISTS orgs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  kind          TEXT                           -- customer | partner | vendor | internal | advisor
);

-- The bets. Weight drives prioritisation.
CREATE TABLE IF NOT EXISTS initiatives (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  slug          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  weight        INTEGER DEFAULT 3,
  status        TEXT,
  owner         TEXT,
  next_milestone TEXT,
  match_regex   TEXT,                          -- how free text is tagged to this initiative
  profile_md    TEXT,
  updated_at    TEXT
);

-- Facts: what Sam owes, what is owed to Sam. Provenance in fact_sources.
CREATE TABLE IF NOT EXISTS commitments (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  kind          TEXT NOT NULL,                 -- owed_by_me | owed_to_me | someday
  title         TEXT NOT NULL,
  context       TEXT,
  counterparty_id INTEGER REFERENCES people(id),
  counterparty  TEXT,
  due           TEXT,
  status        TEXT DEFAULT 'open',           -- open | done | dropped
  origin        TEXT,                          -- 'Current' | 'Meetings Jul–Sep' | ...
  created_at    TEXT NOT NULL,
  closed_at     TEXT,
  run_id        INTEGER REFERENCES runs(id),
  fingerprint   TEXT UNIQUE                    -- hash of normalised title, for idempotent upserts
);
CREATE TABLE IF NOT EXISTS decisions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  text          TEXT NOT NULL,
  owner         TEXT,
  status        TEXT DEFAULT 'pending',        -- pending | taken | reversed
  status_note   TEXT,
  decided_on    TEXT,                          -- date
  created_at    TEXT NOT NULL,
  run_id        INTEGER REFERENCES runs(id),
  fingerprint   TEXT UNIQUE
);
-- Provenance: a fact points at the items (or documents) it came from.
CREATE TABLE IF NOT EXISTS fact_sources (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_type     TEXT NOT NULL,                 -- commitment | decision
  fact_id       INTEGER NOT NULL,
  item_id       INTEGER REFERENCES items(id),
  url           TEXT,                          -- when the source is a link we did not ingest as an item
  label         TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS fact_sources_uq ON fact_sources(fact_type, fact_id, COALESCE(item_id, -1), COALESCE(url, ''));
-- The graph: which item / fact mentions which entity.
CREATE TABLE IF NOT EXISTS mentions (
  ref_type      TEXT NOT NULL,                 -- item | commitment | decision | meeting
  ref_id        INTEGER NOT NULL,
  entity_type   TEXT NOT NULL,                 -- person | org | initiative
  entity_id     INTEGER NOT NULL,
  confidence    REAL DEFAULT 1.0,
  PRIMARY KEY (ref_type, ref_id, entity_type, entity_id)
);

-- Meetings: a Granola note, optionally matched to a calendar event.
CREATE TABLE IF NOT EXISTS meetings (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  note_item_id  INTEGER UNIQUE REFERENCES items(id),      -- the Granola note (kind=note)
  event_item_id INTEGER REFERENCES items(id),             -- the calendar event (kind=event)
  title         TEXT,
  starts_at     TEXT,
  ends_at       TEXT,
  attendees     TEXT,                          -- JSON list of names
  organizer     TEXT,
  segments      INTEGER,
  digest_md     TEXT,                          -- candidates + AI summary
  status        TEXT DEFAULT 'pending',        -- pending | digested | analysed | personal
  match_quality TEXT                           -- exact | loose | none
);

-- Every agent run: who ran what over which inputs and what came out.
CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  agent         TEXT NOT NULL,                 -- 'claude-code:/brief', 'claude-code:/triage', 'importer', ...
  prompt_version TEXT,
  model         TEXT,
  input_summary TEXT,                          -- JSON: windows, counts, item id ranges
  output_md     TEXT,                          -- the brief or report produced
  output_json   TEXT,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  cost_note     TEXT
);
-- Proposed actions awaiting a human verdict (the gate for future agents).
CREATE TABLE IF NOT EXISTS approvals (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id        INTEGER REFERENCES runs(id),
  action_type   TEXT NOT NULL,                 -- send_mail | reply_teams | create_issue | move_event | ...
  proposal      TEXT NOT NULL,                 -- JSON
  evidence      TEXT,                          -- JSON list of item ids / urls
  status        TEXT DEFAULT 'proposed',       -- proposed | approved | rejected | executed
  decided_by    TEXT, decided_at TEXT, executed_at TEXT, result TEXT,
  created_at    TEXT NOT NULL
);
-- Documents kept whole (briefs, analyses, memory files) so the Library survives the move.
CREATE TABLE IF NOT EXISTS documents (
  id            TEXT PRIMARY KEY,              -- path-like id
  section       TEXT NOT NULL,
  title         TEXT NOT NULL,
  path          TEXT,
  meta          TEXT,                          -- JSON
  body_md       TEXT NOT NULL,
  updated_at    TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

-- Search
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(subject, text, from_name, content='items', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, subject, text, from_name) VALUES (new.id, new.subject, new.text, new.from_name);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, subject, text, from_name) VALUES ('delete', old.id, old.subject, old.text, old.from_name);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, subject, text, from_name) VALUES ('delete', old.id, old.subject, old.text, old.from_name);
  INSERT INTO items_fts(rowid, subject, text, from_name) VALUES (new.id, new.subject, new.text, new.from_name);
END;
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(title, body_md, content='documents', content_rowid='rowid');

-- Full Outlook messages (approved by Sam 2026-10-06): exact body, all recipients, attachments on disk.
-- One row per mail item; the item keeps its gist / triage note, this row keeps the message itself.
CREATE TABLE IF NOT EXISTS mail_messages (
  item_id       INTEGER PRIMARY KEY REFERENCES items(id),
  graph_id      TEXT UNIQUE NOT NULL,          -- Microsoft Graph message id
  folder        TEXT NOT NULL,                 -- inbox | sentitems
  internet_message_id TEXT,
  conversation_id TEXT,
  from_name     TEXT, from_address TEXT,
  to_json       TEXT, cc_json TEXT, bcc_json TEXT, reply_to_json TEXT,   -- JSON [{name, address}]
  subject       TEXT,
  received_at   TEXT, sent_at TEXT,
  body_type     TEXT,                          -- html | text
  body          TEXT,                          -- exactly as Graph returned it
  body_text     TEXT,                          -- plain text derived from body, for search and agents
  preview       TEXT,
  has_attachments INTEGER DEFAULT 0,
  importance    TEXT, is_read INTEGER, flag TEXT, categories_json TEXT,
  web_link      TEXT,
  synced_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mail_messages_conv ON mail_messages(conversation_id);
CREATE TABLE IF NOT EXISTS mail_attachments (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id       INTEGER NOT NULL REFERENCES items(id),
  graph_id      TEXT NOT NULL,
  name          TEXT, content_type TEXT, size INTEGER,
  is_inline     INTEGER DEFAULT 0, content_id TEXT,
  kind          TEXT,                          -- file | item | reference
  path          TEXT,                          -- relative to the attachments folder; NULL when not downloadable
  sha256        TEXT,
  UNIQUE(item_id, graph_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts USING fts5(subject, body_text, people);

-- Full Teams / Slack messages (assist/chatsync.py). Purged after chat_retention_days (default 30).
CREATE TABLE IF NOT EXISTS chat_messages (
  item_id       INTEGER PRIMARY KEY REFERENCES items(id),
  source_id     TEXT NOT NULL,                 -- teams | slack
  external_id   TEXT NOT NULL,                 -- connector message id
  conversation_id TEXT, conversation_name TEXT,
  conversation_kind TEXT,                      -- dm | group | channel
  author        TEXT,
  sent_at       TEXT NOT NULL,                 -- ISO UTC from the connector
  body_text     TEXT,                          -- full text; links as markdown
  links_json    TEXT,                          -- [{url, title}]
  thread_parent TEXT,
  web_link      TEXT,
  fetched_at    TEXT
);
CREATE INDEX IF NOT EXISTS chat_messages_sent ON chat_messages(sent_at);
CREATE TABLE IF NOT EXISTS chat_attachments (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id       INTEGER NOT NULL REFERENCES items(id),
  name TEXT, content_type TEXT, size INTEGER,
  url           TEXT                           -- link back to the file in Teams / SharePoint / Slack; files are never downloaded
);
CREATE VIRTUAL TABLE IF NOT EXISTS chat_fts USING fts5(body_text, author, conversation);

-- Prioritised to-do list (assist/todo.py): what to deal with now / today, each with ready-made actions.
CREATE TABLE IF NOT EXISTS todo (
  id            TEXT PRIMARY KEY,              -- fingerprint of the title
  run_id        INTEGER,
  rank          INTEGER,
  priority      TEXT,                          -- now | today | this_week
  category      TEXT,                          -- reply | content | chase | check | decide | prep | other
  title         TEXT NOT NULL,
  why           TEXT,
  effort_min    INTEGER,
  due           TEXT,
  sources_json  TEXT,                          -- [{label, url, ref}]
  actions_json  TEXT,                          -- [Action] (same shape as brief actions)
  status        TEXT DEFAULT 'open',           -- open | done | dismissed | snoozed | superseded
  snooze_until  TEXT,
  created_at    TEXT, updated_at TEXT, touched_at TEXT
);
CREATE INDEX IF NOT EXISTS todo_status ON todo(status, rank);

-- Initiatives: dated status updates (drafted by Claude weekly, approved by Sam; approval sets the initiative's health).
CREATE TABLE IF NOT EXISTS initiative_updates (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  initiative_id INTEGER NOT NULL REFERENCES initiatives(id),
  health        TEXT,                          -- on track | at risk | off track
  status_line   TEXT, progress TEXT, blockers TEXT, next TEXT, scope TEXT,
  sources       TEXT,                          -- JSON [{label, url, ref_type, ref_id}]
  drafted_by    TEXT, drafted_at TEXT,
  approved_at   TEXT,                          -- NULL = draft waiting for Sam
  edited        INTEGER DEFAULT 0,
  discarded     INTEGER DEFAULT 0
);

-- Which records the initiative tagger has already read (so each runs once; rejected links stay rejected in mentions).
CREATE TABLE IF NOT EXISTS tagged (
  ref_type      TEXT NOT NULL,
  ref_id        INTEGER NOT NULL,
  tagged_at     TEXT,
  PRIMARY KEY (ref_type, ref_id)
);

-- Document cards: what each document that matters is (assist/doccards.py). doc_id is the app's id: lf-<item>, sp-<item>, ma-<attachment>.
CREATE TABLE IF NOT EXISTS doc_cards (
  doc_id        TEXT PRIMARY KEY,
  title TEXT, kind TEXT, summary TEXT,
  facts TEXT, decisions TEXT, people TEXT, orgs TEXT, initiatives TEXT,   -- JSON lists
  doc_date TEXT, file_date TEXT,
  version_key TEXT, is_current INTEGER, versions INTEGER,
  sensitivity TEXT,                            -- normal | confidential | hr-legal | personal
  text_hash TEXT, created_at TEXT
);
