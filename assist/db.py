"""Database access for Assist. SQLite, WAL mode, schema applied from schema.sql.

The database lives outside OneDrive by default:
  ~/Library/Application Support/Assist/assist.db   (override with ASSIST_DB)
"""
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PKG = Path(__file__).resolve().parent
APP = PKG.parent   # the code: assist/, scripts/, assets/, templates/


def _home():
    """The user's data folder (16 Nov 2026, DESIGN-PERSONALISATION.md phase 6): env ASSIST_HOME, else the path in
    ~/.assist/home (written by scripts/install.sh), else the code folder itself (code and data together, as Sam's install)."""
    h = os.environ.get("ASSIST_HOME", "").strip()
    if not h:
        f = Path.home() / ".assist" / "home"
        try:
            h = f.read_text().strip() if f.exists() else ""
        except OSError:
            h = ""
    return Path(os.path.expanduser(h)).resolve() if h else APP


ASSIST = _home()   # the user's data: memory/, inbox/, org/, drafts/, briefs/, CLAUDE.md, .claude/skills; Claude runs start here
DEFAULT_DB = Path.home() / "Library" / "Application Support" / "Assist" / "assist.db"
SCHEMA_VERSION = 1


def db_path():
    return Path(os.environ.get("ASSIST_DB") or DEFAULT_DB)


# One Mac can run a second, separate SleePO beside the real one: the demo copy (assist/demo.py, 16 Nov 2026), with its own
# data folder, database, Keychain account, port and restart trigger, so testing first-run setup never touches the user's data.
PORT = int(os.environ.get("ASSIST_PORT") or 8765)
DEMO = os.environ.get("ASSIST_DEMO") == "1"


def reload_trigger():
    """The file whose change restarts this server (`assist.cli restart`, Apply now): the demo copy watches its own."""
    return PKG / (os.environ.get("ASSIST_RELOAD_TRIGGER") or "reload.trigger")


def connect(path=None):
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


PEOPLE_COLUMNS = {"title": "TEXT", "department": "TEXT", "location": "TEXT", "manager_id": "INTEGER", "start_date": "TEXT",
                  "kb_url": "TEXT", "org_source": "TEXT", "active": "INTEGER DEFAULT 1", "avatar": "TEXT", "affiliation": "TEXT", "affiliation_note": "TEXT"}


def migrate(con):
    con.executescript((PKG / "schema.sql").read_text())
    have = {r[1] for r in con.execute("PRAGMA table_info(people)")}
    for col, typ in PEOPLE_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE people ADD COLUMN {col} {typ}")
    for table, cols in {"initiatives": {"goal": "TEXT", "v2mom": "TEXT", "key_people": "TEXT", "themes": "TEXT", "active": "INTEGER DEFAULT 1", "merged_into": "INTEGER"},
                        "mentions": {"reason": "TEXT", "source": "TEXT", "verdict": "TEXT", "updated_at": "TEXT"}}.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    if "text" not in {r[1] for r in con.execute("PRAGMA table_info(mail_attachments)")}:
        con.execute("ALTER TABLE mail_attachments ADD COLUMN text TEXT")  # extracted text when the original file is not available
    from . import entities, loops   # base tables older than the numbered migrations (m009 alters loops); the rest: m020
    entities.ensure_schema(con)
    loops.ensure_schema(con)
    cur = con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    if cur is None or cur < SCHEMA_VERSION:
        con.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, ?)", (SCHEMA_VERSION, now()))
    con.commit()
    from . import migrations   # numbered migrations (assist/migrations/mNNN_*.py), each applied once
    migrations.apply(con, con.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0, now, log=lambda *_: None)


def has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprint(text):
    return hashlib.sha1(re.sub(r"\W+", " ", (text or "").lower()).strip().encode()).hexdigest()[:16]


def hash_payload(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- helpers
def upsert_source(con, s):
    cols = ["id", "system", "name", "vendor", "kind", "how", "auth", "connect", "color", "mono", "logo", "health",
            "last_pull_at", "window_from", "window_to", "note", "sort"]
    vals = {c: s.get(c) for c in cols}
    con.execute(
        "INSERT INTO sources (%s) VALUES (%s) ON CONFLICT(id) DO UPDATE SET %s" % (
            ",".join(cols), ",".join("?" * len(cols)),
            ",".join(f"{c}=COALESCE(excluded.{c}, sources.{c})" for c in cols if c != "id")),
        [vals[c] for c in cols])


# The sources every install has (16 Nov 2026: a new database had none, so its first ingest failed the pulls' foreign key).
# Seeded once into an empty sources table (migration m031); start_pull adds any other source on first use.
CORE_SOURCES = [
    {"id": "granola", "system": "granola", "name": "Granola", "vendor": "Granola", "kind": "Meeting notes and transcripts",
     "color": "#2f7d4f", "mono": "G", "logo": "granola", "sort": 0},
    {"id": "outlook.inbox", "system": "outlook", "name": "Outlook · Inbox", "vendor": "Microsoft 365", "kind": "Mail: inbox and sent",
     "color": "#0f6cbd", "mono": "O", "logo": "outlook", "sort": 10},
    {"id": "outlook.sent", "system": "outlook", "name": "Outlook · Sent", "vendor": "Microsoft 365", "kind": "Mail: inbox and sent",
     "color": "#0f6cbd", "mono": "O", "logo": "outlook", "sort": 10},
    {"id": "calendar", "system": "calendar", "name": "Calendar", "vendor": "Microsoft 365", "kind": "Calendar events",
     "color": "#0f6cbd", "mono": "C", "logo": "outlook", "sort": 20},
    {"id": "teams", "system": "teams", "name": "Teams", "vendor": "Microsoft 365", "kind": "Chats and channel messages",
     "color": "#5b5fc7", "mono": "T", "logo": "teams", "sort": 30},
    {"id": "slack", "system": "slack", "name": "Slack", "vendor": "Slack", "kind": "DMs, threads and channels",
     "color": "#4a154b", "mono": "S", "logo": "slack", "sort": 40},
    {"id": "sharepoint", "system": "sharepoint", "name": "SharePoint & OneDrive", "vendor": "Microsoft 365",
     "kind": "Documents: your OneDrive and files shared with you", "color": "#0f6cbd", "mono": "SP", "logo": "sharepoint", "sort": 70},
    {"id": "salesforce", "system": "salesforce", "name": "Salesforce", "vendor": "Salesforce", "kind": "Pipeline and accounts (company-level only)",
     "color": "#00a1e0", "mono": "SF", "logo": "salesforce", "sort": 80},
    {"id": "local", "system": "local", "name": "Local files", "vendor": "This Mac", "kind": "Documents in Downloads, Desktop and Documents",
     "color": "#3a3a3a", "mono": "LF", "sort": 80},
]


def ensure_source(con, source_id):
    """Add a source row when it is missing (a core source's defaults, else just its id). Never changes an existing row."""
    if con.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
        return
    s = next((dict(x) for x in CORE_SOURCES if x["id"] == source_id), None) or {"id": source_id, "system": source_id.split(".")[0], "name": source_id}
    cols = list(s)
    con.execute(f"INSERT OR IGNORE INTO sources ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [s[c] for c in cols])


def start_pull(con, source_id, agent, window_from=None, window_to=None, note=None):
    ensure_source(con, source_id)
    cur = con.execute("INSERT INTO pulls (source_id, agent, window_from, window_to, note, started_at) VALUES (?,?,?,?,?,?)",
                      (source_id, agent, window_from, window_to, note, now()))
    return cur.lastrowid


def finish_pull(con, pull_id, available=None, pulled=None, noise=None, complete=1):
    con.execute("UPDATE pulls SET available=?, pulled=?, noise=?, complete=?, finished_at=? WHERE id=?",
                (available, pulled, noise, complete, now(), pull_id))
    row = con.execute("SELECT source_id, window_to FROM pulls WHERE id=?", (pull_id,)).fetchone()
    if row:
        con.execute("UPDATE sources SET last_pull_at=?, window_to=COALESCE(?, window_to) WHERE id=?",
                    (now(), row["window_to"], row["source_id"]))


def canon_ts(ts):
    """UTC timestamps as YYYY-MM-DDTHH:MM:SSZ. Unambiguous forms only (Z, +00:00, any explicit offset); a time without a zone
    is returned unchanged rather than guessed."""
    if not ts or not isinstance(ts, str):
        return ts
    m = re.match(r"^(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d)(:\d\d)?(\.\d+)?(Z|[+-]\d\d:?\d\d)$", ts.strip())
    if not m:
        return ts
    if m.group(5) in ("Z", "+00:00", "+0000", "-00:00"):
        return f"{m.group(1)}T{m.group(2)}{m.group(3) or ':00'}Z"
    try:
        d = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{m.group(3) or ':00'}{m.group(5) if ':' in m.group(5) else m.group(5)[:3] + ':' + m.group(5)[3:]}")
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ts


def upsert_item(con, source_id, external_id, kind, ts, pull_id=None, **f):
    """Insert or update a raw item. Returns (id, created: bool). ts is stored in canonical UTC form when unambiguous."""
    ts = canon_ts(ts)
    payload = f.get("payload")
    payload_json = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else payload
    phash = hash_payload(payload) if payload is not None else None
    existing = con.execute("SELECT id, payload_hash FROM items WHERE source_id=? AND external_id=?", (source_id, external_id)).fetchone()
    fields = {"kind": kind, "ts": ts, "from_name": f.get("from_name"), "subject": f.get("subject"), "text": f.get("text"),
              "thread": f.get("thread"), "url": f.get("url"), "payload": payload_json, "payload_hash": phash,
              "retention": f.get("retention") or "general", "noise": 1 if f.get("noise") else 0,
              "from_person_id": f.get("from_person_id")}
    if existing:
        # merge payloads: a later, slimmer record (e.g. a brief's calendar rows) must not erase fields an earlier pull stored,
        # such as an event's join_url or summary. New keys win; keys the new record lacks are kept.
        if isinstance(payload, dict):
            old = con.execute("SELECT payload FROM items WHERE id=?", (existing["id"],)).fetchone()["payload"]
            try:
                prev = json.loads(old) if old else {}
            except ValueError:
                prev = {}
            if isinstance(prev, dict):
                merged = {**prev, **{k: v for k, v in payload.items() if v not in (None, "")}}
                fields["payload"] = json.dumps(merged, ensure_ascii=False)
                fields["payload_hash"] = hash_payload(merged)
        sets = ",".join(f"{k}=COALESCE(?, {k})" for k in fields)
        con.execute(f"UPDATE items SET {sets}, pull_id=COALESCE(?, pull_id) WHERE id=?",
                    [fields[k] for k in fields] + [pull_id, existing["id"]])
        return existing["id"], False
    cols = ["source_id", "external_id"] + list(fields) + ["pull_id", "pulled_at"]
    vals = [source_id, external_id] + [fields[k] for k in fields] + [pull_id, now()]
    cur = con.execute(f"INSERT INTO items ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
    return cur.lastrowid, True


def get_or_create_person(con, name, **f):
    name = (name or "").strip()
    if not name:
        return None
    row = con.execute("SELECT person_id FROM people_aliases WHERE alias=?", (name.lower(),)).fetchone()
    if row:
        return row["person_id"]
    row = con.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()
    if row:
        pid = row["id"]
    else:
        cur = con.execute("INSERT INTO people (name, role, relationship, profile_md, updated_at) VALUES (?,?,?,?,?)",
                          (name, f.get("role"), f.get("relationship"), f.get("profile_md"), now()))
        pid = cur.lastrowid
    con.execute("INSERT OR IGNORE INTO people_aliases (alias, person_id) VALUES (?, ?)", (name.lower(), pid))
    for a in f.get("aliases") or []:
        if a:
            con.execute("INSERT OR IGNORE INTO people_aliases (alias, person_id) VALUES (?, ?)", (a.lower(), pid))
    return pid


# ---------------------------------------------------------------- who the user is (one place: assist/profile.py)
# ME_ADDRESS finds their address anywhere; ME_STRICT is their address or their full name; ME_LOOSE also takes a one-word
# name of theirs (speaker labels, meeting attendees). Built from the profile when used (16 Nov 2026; until then these were
# fixed patterns for one user).
from . import profile as _profile  # noqa: E402  (profile reads the database through this module at call time)

ME_ADDRESS = _profile.ADDRESS
ME_STRICT = _profile.STRICT
ME_LOOSE = _profile.LOOSE


def person_emails(con, person_id):
    """The e-mail addresses SleePO knows for a person (people_aliases), lower case."""
    if not person_id:
        return []
    return [r[0] for r in con.execute("SELECT alias FROM people_aliases WHERE person_id=? AND alias LIKE '%@%'", (person_id,))]


def keychain_account():
    """The macOS Keychain account SleePO's sign-ins are kept under: env ASSIST_KEYCHAIN_ACCOUNT, else settings
    keychain_account, else the Mac user's name. Reads only."""
    v = os.environ.get("ASSIST_KEYCHAIN_ACCOUNT", "").strip()
    if not v:
        try:
            from .profile import read_only
            c = read_only(db_path())
            if c is not None:
                try:
                    r = c.execute("SELECT value FROM settings WHERE key='keychain_account'").fetchone()
                    v = (r[0] or "").strip() if r else ""
                finally:
                    c.close()
        except sqlite3.Error:
            v = ""
    if not v:
        import getpass
        v = getpass.getuser()
    return v


def get_setting(con, key, default=None):
    """A value from the settings table, or default."""
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r and r[0] is not None else default


def set_setting(con, key, value):
    con.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, None if value is None else str(value)))
    con.commit()


def resolve_person(con, name_or_email):
    if not name_or_email:
        return None
    row = con.execute("SELECT person_id FROM people_aliases WHERE alias=?", (name_or_email.strip().lower(),)).fetchone()
    return row["person_id"] if row else None


def upsert_commitment(con, kind, title, run_id=None, **f):
    fp = fingerprint(title)
    row = con.execute("SELECT id FROM commitments WHERE fingerprint=?", (fp,)).fetchone()
    if row:
        con.execute("UPDATE commitments SET context=COALESCE(?, context), counterparty=COALESCE(?, counterparty), due=COALESCE(?, due), "
                    "origin=COALESCE(?, origin), status=COALESCE(?, status) WHERE id=?",
                    (f.get("context"), f.get("counterparty"), f.get("due"), f.get("origin"), f.get("status"), row["id"]))
        cid, created = row["id"], False
    else:
        cur = con.execute("INSERT INTO commitments (kind, title, context, counterparty, counterparty_id, due, status, origin, created_at, closed_at, run_id, fingerprint) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (kind, title, f.get("context"), f.get("counterparty"), resolve_person(con, f.get("counterparty")), f.get("due"),
                           f.get("status") or "open", f.get("origin"), f.get("created_at") or now(), f.get("closed_at"), run_id, fp))
        cid, created = cur.lastrowid, True
    for l in f.get("links") or []:
        con.execute("INSERT OR IGNORE INTO fact_sources (fact_type, fact_id, item_id, url, label) VALUES ('commitment', ?, ?, ?, ?)",
                    (cid, l.get("item_id"), l.get("url"), l.get("label")))
    return cid, created


def start_run(con, agent, prompt_version=None, model=None, input_summary=None):
    cur = con.execute("INSERT INTO runs (agent, prompt_version, model, input_summary, started_at) VALUES (?,?,?,?,?)",
                      (agent, prompt_version, model, json.dumps(input_summary) if input_summary is not None else None, now()))
    return cur.lastrowid


def finish_run(con, run_id, output_md=None, output_json=None, cost_note=None):
    con.execute("UPDATE runs SET output_md=?, output_json=?, cost_note=?, finished_at=? WHERE id=?",
                (output_md, json.dumps(output_json) if output_json is not None else None, cost_note, now(), run_id))


def upsert_document(con, doc_id, section, title, body_md, path=None, meta=None):
    con.execute("INSERT INTO documents (id, section, title, path, meta, body_md, updated_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET section=excluded.section, title=excluded.title, path=excluded.path, meta=excluded.meta, "
                "body_md=excluded.body_md, updated_at=excluded.updated_at",
                (doc_id, section, title, path, json.dumps(meta or {}), body_md, now()))


def tag_mentions(con, ref_type, ref_id, text):
    """Link a record to initiatives whose match_regex hits, and to people whose alias appears."""
    text_l = (text or "")
    for ini in con.execute("SELECT id, match_regex FROM initiatives WHERE match_regex IS NOT NULL AND COALESCE(active, 1)=1"):
        try:
            if re.search(ini["match_regex"], text_l):
                con.execute("INSERT OR IGNORE INTO mentions (ref_type, ref_id, entity_type, entity_id, confidence, source, updated_at) VALUES (?,?,?,?,0.6,'regex',?)",
                            (ref_type, ref_id, "initiative", ini["id"], now()))
        except re.error:
            pass
    low = text_l.lower()
    for p in con.execute("SELECT id, name FROM people WHERE is_me=0"):
        first = p["name"].split()[0].lower()
        if len(first) > 3 and re.search(r"\b" + re.escape(first) + r"\b", low):
            con.execute("INSERT OR IGNORE INTO mentions (ref_type, ref_id, entity_type, entity_id, confidence) VALUES (?,?,?,?,0.5)",
                        (ref_type, ref_id, "person", p["id"]))
