"""Things content can be about besides people, organisations and initiatives: products, roadmap items and Jira issues.

Each is a row in ref_entities (type, key, name, url) so mentions can point at it like any other entity:
- product: Acme products and modules (PRODUCTS below; kept in step with memory/glossary.md). Matched by name in text,
  including Granola's usual mishearings ("Peer+" for COPILOT+).
- roadmap: items of Rowan's Roadmap Workbook workbook (roadmap_items, assist/roadmap.py), matched by ID (AI-001, PLT-077),
  and by name when the name is specific (three words or more). The snapshot is rebuilt on every re-read, so roadmap
  entities are keyed by the item ID, never by row number.
- ticket: Jira issues (DEV-59722, SUP-21220), matched only for real project keys: the projects list read from Jira
  (JIRA_PROJECTS, plus settings key jira_projects for extras) plus any key seen in a Jira notification subject "[JIRA] (KEY-123) Title", which also
  gives the issue its title until Jira itself is read. The refresh's documents pull reads the issues `assist.cli
  tickets-todo` lists from Jira (read-only) into inbox/jira/issues.json and `assist.cli tickets-import` stores title,
  type and status. SUP (the customer support desk) keeps type and status only, never the summary, which can carry
  customer details (org rule for Atlassian data). Look-alikes such as CVE-2026-1234, Q2-2026 or roadmap IDs are not projects, so not issues.
"""
import json
import re
from . import org

SCHEMA = """
CREATE TABLE IF NOT EXISTS ref_entities (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  type  TEXT NOT NULL,                 -- product | roadmap | ticket
  key   TEXT NOT NULL,                 -- slug, roadmap ID or issue key
  name  TEXT,
  url   TEXT,
  updated_at TEXT,
  UNIQUE(type, key)
);
"""

# (slug, name, pattern, case-sensitive). Kept narrow on purpose: a missed mention costs less than a wrong one.
PRODUCTS = [tuple(x) for x in org.section("products", [])]   # (slug, name, pattern, case-sensitive): the org pack
_JIRA = org.section("jira", {})
JIRA = f"https://{_JIRA['site']}/browse/" if _JIRA.get("site") else ""   # the org pack
# Jira projects visible to Sam (read from Atlassian, 13 Oct 2026). LQ is not browsable for him but appears in Jira mail.
JIRA_PROJECTS = set(_JIRA.get("projects") or [])   # the org pack, plus settings jira_projects
JIRA_SUBJECT = re.compile(r"\[JIRA\][^()]*\(([A-Z][A-Z0-9]{1,9})-(\d{1,7})\)\s*(.*)$")


def ensure_schema(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(ref_entities)")}
    for col in ("status", "status_category", "issue_type", "source_updated"):   # Jira issues (tickets-import)
        if col not in have:
            con.execute(f"ALTER TABLE ref_entities ADD COLUMN {col} TEXT")


SUPPORT_DESK = set(_JIRA.get("support_desk") or [])   # summaries never stored: they can name customers (the org pack)


def import_issues(con, path, now):
    """Title, type and status of Jira issues from a file written by the pull (inbox/jira/issues.json)."""
    ensure_schema(con)
    data = json.loads(open(path).read())
    n = 0
    for x in data.get("issues") or []:
        key = (x.get("key") or "").strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}-\d{1,7}", key):
            continue
        desk = key.split("-")[0] in SUPPORT_DESK
        name = (f"{x.get('type') or 'Support'} (support desk)" if desk else (x.get("summary") or "").strip()[:200]) or None
        _upsert(con, "ticket", key, None, JIRA + key, now)
        con.execute("UPDATE ref_entities SET name=COALESCE(?, name), status=?, status_category=?, issue_type=?, source_updated=?, updated_at=? WHERE type='ticket' AND key=?",
                    (name, x.get("status"), x.get("status_category"), x.get("type"), x.get("updated"), now, key))
        n += 1
    con.commit()
    return n


def tickets_todo(con, days=14):
    """Issue keys to (re)read from Jira: never read, or not refreshed for `days`."""
    ensure_schema(con)
    return [r[0] for r in con.execute("SELECT key FROM ref_entities WHERE type='ticket' AND (status IS NULL OR updated_at < datetime('now', ?)) ORDER BY key",
                                      (f"-{days} days",))]


def _upsert(con, type_, key, name, url, now):
    con.execute("INSERT INTO ref_entities (type, key, name, url, updated_at) VALUES (?,?,?,?,?) ON CONFLICT(type, key) DO UPDATE SET "
                "name=COALESCE(excluded.name, ref_entities.name), url=COALESCE(excluded.url, ref_entities.url), updated_at=excluded.updated_at",
                (type_, key, name, url, now))
    return con.execute("SELECT id FROM ref_entities WHERE type=? AND key=?", (type_, key)).fetchone()[0]


def jira_projects(con):
    r = con.execute("SELECT value FROM settings WHERE key='jira_projects'").fetchone()
    keys = set(JIRA_PROJECTS) | set(json.loads(r[0]) if r and r[0] else [])   # settings jira_projects: extra keys, optional
    for (subj,) in con.execute("SELECT subject FROM items WHERE subject LIKE '%[JIRA]%'"):
        m = JIRA_SUBJECT.search(subj or "")
        if m:
            keys.add(m.group(1))
    return keys


def matchers(con, now):
    """Sync the entities and return [(type, entity id, compiled pattern, confidence)] plus a ticket matcher."""
    ensure_schema(con)
    out = []
    for slug, name, pat, cs in PRODUCTS:
        out.append(("product", _upsert(con, "product", slug, name, None, now), re.compile(pat, 0 if cs else re.I), 0.7))
    have = con.execute("SELECT 1 FROM sqlite_master WHERE name='roadmap_items'").fetchone()
    for r in (con.execute("SELECT id, name_internal, name_external FROM roadmap_items") if have else []):
        eid = _upsert(con, "roadmap", r["id"], r["name_internal"] or r["name_external"], f"#/roadmap?item={r['id']}", now)
        out.append(("roadmap", eid, re.compile(r"(?<![A-Za-z0-9-])" + re.escape(r["id"]) + r"(?![0-9])"), 1.0))
        for nm in {r["name_internal"], r["name_external"]}:
            nm = re.sub(r"\s*\(.*?\)\s*", " ", nm or "").strip()
            if len(nm.split()) >= 3 and len(nm) >= 18:
                out.append(("roadmap", eid, re.compile(r"(?<![\w])" + re.escape(nm).replace(r"\ ", r"[\s-]+") + r"(?![\w])", re.I), 0.6))
    # Jira issue titles from notification subjects
    titles = {}
    for (subj,) in con.execute("SELECT subject FROM items WHERE subject LIKE '%[JIRA]%' ORDER BY ts"):
        m = JIRA_SUBJECT.search(subj or "")
        if m and m.group(3).strip() and m.group(1) not in SUPPORT_DESK:
            titles[f"{m.group(1)}-{m.group(2)}"] = m.group(3).strip()[:200]
    keys = jira_projects(con)
    ticket_re = re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(sorted(map(re.escape, keys), key=len, reverse=True)) + r")-(\d{1,7})(?![0-9])") if keys else None

    def ticket(key):
        eid = _upsert(con, "ticket", key, None, JIRA + key, now)
        if titles.get(key):   # a title from a notification only until Jira itself has been read
            con.execute("UPDATE ref_entities SET name=? WHERE id=? AND status IS NULL", (titles[key], eid))
        return eid
    return out, ticket_re, ticket


def get(con, eid):
    ensure_schema(con)
    r = con.execute("SELECT id, type, key, name, url, status, issue_type FROM ref_entities WHERE id=?", (eid,)).fetchone()
    return dict(r) if r else None
