"""One-off import of everything the prototype collected into the database.

  assist import-legacy          (idempotent; safe to re-run)

Reads: inbox/sources.json, inbox/coverage.json, Granola Export/raw-json, inbox/granola/*.md digests,
inbox/calendar/events.json + reconciled.json, inbox/live/*.md snapshots, TASKS.md,
memory/people/*.md, memory/projects/*.md, briefs, analyses and design documents.
"""
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from . import db
from . import org
from . import profile

ASSIST = db.ASSIST
GRANOLA = ASSIST.parent / "Granola Export"
sys.path.insert(0, str(db.APP / "scripts"))
import build_ui as legacy  # noqa: E402  (parsers for tasks, digests, snapshots, people, projects, brief)

SYSTEM_STREAMS = {
    "granola": [("granola", "Meeting notes")],
    "outlook": [("outlook.inbox", "Inbox"), ("outlook.sent", "Sent")],
    "calendar": [("calendar", "Events")],
    "teams": [("teams", "Messages")],
    "slack": [("slack", "Messages")],
    "jira": [("jira", "Issues")],
    "sharepoint": [("sharepoint", "Documents")],
    "salesforce": [("salesforce", "Pipeline")],
}
COVERAGE_KEY_TO_SOURCE = {"granola": "granola", "mail": "outlook.inbox", "teams": "teams", "slack": "slack",
                          "calendar": "calendar", "jira": "jira"}
STREAM_TO_KIND = {"outlook.inbox": "mail", "outlook.sent": "sent", "teams": "chat", "slack": "chat", "calendar.snap": "event"}


# a meeting about an HR matter (kept as hr_legal): generic words, plus names the user marks sensitive (the profile)
SENSITIVE_TITLE = profile.FieldPattern("sensitive_names", prefix=r"\bHR\b|legal|termination|rupture")


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------- sources
def import_sources(con):
    reg = json.loads((ASSIST / "inbox" / "sources.json").read_text()).get("systems", [])
    cov = json.loads((ASSIST / "inbox" / "coverage.json").read_text()) if (ASSIST / "inbox" / "coverage.json").exists() else {"sources": []}
    for i, sysr in enumerate(reg):
        for sid, sname in SYSTEM_STREAMS.get(sysr["id"], [(sysr["id"], sysr["name"])]):
            db.upsert_source(con, {"id": sid, "system": sysr["id"], "name": f"{sysr['name']} · {sname}" if len(SYSTEM_STREAMS.get(sysr['id'], [])) > 1 else sysr["name"],
                                   "vendor": sysr.get("vendor"), "kind": sysr.get("kind"), "how": sysr.get("how"), "auth": sysr.get("auth"),
                                   "connect": sysr.get("connect"), "color": sysr.get("color"), "mono": sysr.get("mono"), "logo": sysr.get("logo"),
                                   "sort": i * 10})
    # coverage rows become pulls (one per window) and set health/last_pull on the stream
    n = 0
    for r in cov.get("sources", []):
        key = (r.get("key") or "").split("_")[0]
        sid = COVERAGE_KEY_TO_SOURCE.get(key)
        if not sid:
            continue
        exists = con.execute("SELECT 1 FROM pulls WHERE source_id=? AND note=?", (sid, r.get("source"))).fetchone()
        if not exists:
            def num(v):
                m = re.search(r"\d[\d,]*", str(v)) if v is not None else None
                return int(m.group(0).replace(",", "")) if m else None
            con.execute("INSERT INTO pulls (source_id, window_from, window_to, available, pulled, complete, agent, note, started_at, finished_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (sid, None, r.get("last_seen"), num(r.get("available")), num(r.get("digested")), 1, "claude-code (prototype)",
                         r.get("source"), r.get("last_seen"), r.get("last_seen")))
            n += 1
        con.execute("UPDATE sources SET health=?, last_pull_at=COALESCE(?, last_pull_at), note=? WHERE id=?",
                    (r.get("health"), r.get("last_seen"), r.get("note"), sid))
        if sid == "outlook.inbox" and "sent" in str(r.get("source", "")).lower():
            con.execute("UPDATE sources SET health=?, last_pull_at=COALESCE(?, last_pull_at) WHERE id='outlook.sent'", (r.get("health"), r.get("last_seen")))
    for g in cov.get("gaps", []):
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("gap:" + db.fingerprint(g), g))
    log(f"sources: {len(reg)} systems, {n} new pull windows")


# -------------------------------------------------------------- people / initiatives
def import_people(con):
    me = con.execute("SELECT id FROM people WHERE is_me=1 ORDER BY id LIMIT 1").fetchone()   # the user (assist/profile.py)
    p = profile.get(con)
    if not me and p["full_name"]:
        me = [db.get_or_create_person(con, p["full_name"], role=p["role"] or None, aliases=[p["first_name"], *p["emails"], *p["aliases"]])]
        con.execute("UPDATE people SET is_me=1 WHERE id=?", (me[0],))
    n = 0
    for p in legacy.md_files(ASSIST / "memory" / "people"):
        text, meta = legacy.read(p)
        name = legacy.title_of(p, text, meta)
        first = name.split()[0]
        email = org.address_for(name)   # the org pack's address pattern; "" without one
        pid = db.get_or_create_person(con, name, role=meta.get("role"), relationship=meta.get("relationship"), profile_md=text,
                                      aliases=[first, email, name.replace("é", "e").replace("ü", "u")])
        con.execute("UPDATE people SET role=COALESCE(?, role), relationship=COALESCE(?, relationship), profile_md=?, updated_at=? WHERE id=?",
                    (meta.get("role"), meta.get("relationship"), text, meta.get("updated") or db.now(), pid))
        n += 1
    # known transcription variants
    for alias, canon in org.section("mishearings", []):   # names Granola mishears (the org pack)
        pid = db.resolve_person(con, canon)
        if pid:
            con.execute("INSERT OR IGNORE INTO people_aliases (alias, person_id) VALUES (?, ?)", (alias, pid))
    log(f"people: {n} profiles")


def import_initiatives(con):
    """Canonical initiatives come from assist/initiatives.py REGISTRY (memory/context/strategy.md); applied through an ingest bundle."""
    from . import initiatives, ingest
    ingest.ingest_bundle(con, initiatives.setup_bundle())
    log("initiatives: ok (registry)")


# -------------------------------------------------------------- granola + calendar
def import_granola(con):
    raw = GRANOLA / "raw-json"
    bodies = legacy.load_digest_sections()
    pull = db.start_pull(con, "granola", "importer", note="legacy import of Granola export")
    n = 0
    notes = []
    for p in sorted(raw.glob("*.json")):
        try:
            notes.append(json.loads(p.read_text()))
        except Exception:
            continue
    from .granola_stitch import stitch
    notes, joins = stitch(notes)   # a recording resumed in the wrong note joins the meeting it continues
    for piece, host in joins:
        con.execute("UPDATE items SET noise=1 WHERE source_id='granola' AND external_id=?", (piece,))
        log(f"granola: {piece} is the rest of {host} (recording resumed in another note)")
    for note in notes:
        names = [a.get("name") for a in (note.get("attendees") or []) if a.get("name")]
        # speakers Granola named from the call's display names: {name: lines spoken} (assist/meeting_people.py)
        spoke = {}
        for s in note.get("transcript") or []:
            nm = (s.get("speaker") or {}).get("name")
            if nm:
                spoke[nm] = spoke.get(nm, 0) + 1
        note = dict(note, _speakers=spoke) if spoke else note
        summary = note.get("summary_markdown") or note.get("summary_text") or ""
        personal = bool(profile.PERSONAL.search(note.get("title") or ""))
        item_id, _ = db.upsert_item(con, "granola", note["id"], "note", note.get("created_at"), pull_id=pull,
                                    from_name=profile.name(con) or None, subject=note.get("title") or "Untitled",
                                    text="" if personal else summary, url=note.get("web_url"),
                                    payload=None if personal else {k: v for k, v in note.items() if k != "transcript"},
                                    retention="hr_legal" if SENSITIVE_TITLE.search(note.get("title") or "") else "general",   # \bHR\b: "Isla" is not HR (28 Oct 2026)
                                    noise=1 if personal else 0)
        body, analysed = bodies.get(note["id"], ("", False))
        status = "personal" if personal else ("analysed" if analysed else ("digested" if body else "pending"))
        con.execute("INSERT INTO meetings (note_item_id, title, starts_at, attendees, segments, digest_md, status) VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(note_item_id) DO UPDATE SET "
                    # never erase a digest or downgrade a status: digests also arrive through ingest bundles and processed files
                    "digest_md=COALESCE(NULLIF(excluded.digest_md, ''), meetings.digest_md), "
                    "status=CASE WHEN excluded.status='personal' THEN 'personal' "
                    "WHEN NULLIF(excluded.digest_md, '') IS NOT NULL AND NOT (meetings.status='analysed' AND excluded.status='digested') THEN excluded.status "
                    "ELSE meetings.status END, segments=excluded.segments",
                    (item_id, note.get("title") or "Untitled", db.canon_ts(note.get("created_at")), json.dumps(names), len(note.get("transcript") or []),
                     None if personal else body, status))
        n += 1
    db.finish_pull(con, pull, available=n, pulled=n)
    log(f"granola: {n} notes")


def merge_calendar_pull(pull_path, ev_path=None):
    """Merge a calendar pull file from the connector (the pulls may not run their own scripts). Returns (added, replaced)."""
    r = merge_calendar(json.loads(Path(pull_path).read_text()), ev_path)
    return r["added"], r["replaced"]


def merge_calendar(pull, ev_path=None, record_window=True, dry_run=False):
    """Merge a calendar pull ({"window": {...}, "events": [...]}, times in UTC) into inbox/calendar/events.json: replace events
    by id, keep older ones and the fields the pull lacks (a join link read earlier).

    A complete pull (window events_fetched equals totalResultCount) owns its window: an event stored there that the pull no
    longer has was moved out of the window, deleted, declined or re-sent under a new id, so it is marked removed
    (isCancelled, `removed` = the day it went) and every view drops it; a later pull that has it brings it back. Without this
    a moved meeting stayed on its old day as well. The file is rewritten only when an event changed.
    Returns counts (added, replaced, removed, moved, changed) and the moves as text."""
    ev_path = Path(ev_path) if ev_path else ASSIST / "inbox" / "calendar" / "events.json"
    events = pull.get("events")
    if not isinstance(events, list) or any(not isinstance(e, dict) or not e.get("id") or not e.get("start") for e in events):
        raise ValueError("a calendar pull is {\"window\": {...}, \"events\": [{\"id\", \"start\", ...}]}")
    data = json.loads(ev_path.read_text()) if ev_path.exists() else {"events": [], "windows": []}
    by_id = {e["id"]: e for e in data.get("events", [])}
    out = {"added": 0, "replaced": 0, "removed": 0, "moved": 0, "changed": 0, "moves": []}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for e in events:
        e = dict(e)
        e.setdefault("start_tz", "UTC")
        e["summary"] = (e.get("summary") or "")[:200]
        old = by_id.get(e["id"])
        if old and not e.get("join_url") and old.get("join_url"):
            e["join_url"] = old["join_url"]
        new = {**(old or {}), **e}
        new.pop("removed", None)                        # it is on the calendar again
        if old and "response" not in e and e.get("showAs") != old.get("showAs"):
            new.pop("response", None)                   # Sam's reply changed since Calendar.app read it
        if old:
            out["replaced"] += 1
            if old.get("start", "")[:16] != new["start"][:16] and not old.get("removed"):
                out["moved"] += 1
                out["moves"].append(f"{(new.get('subject') or '')[:50]!r} {old['start'][:16]} -> {new['start'][:16]}")
        else:
            out["added"] += 1
        if new != old:
            out["changed"] += 1
        by_id[e["id"]] = new
    w = pull.get("window") or {}
    lo, hi = (w.get("afterDateTime") or "")[:19], (w.get("beforeDateTime") or "")[:19]
    complete = bool(lo and hi) and w.get("events_fetched") is not None and w.get("events_fetched") == w.get("totalResultCount")
    if complete:
        got = {e["id"] for e in events}
        for eid, e in by_id.items():
            # inside the window from start to end (the connector's window is "starts after, ends before")
            if eid not in got and not e.get("isCancelled") and lo <= (e.get("start") or "")[:19] and (e.get("end") or e.get("start") or "")[:19] <= hi:
                by_id[eid] = {**e, "isCancelled": True, "removed": today}
                out["removed"] += 1
                out["changed"] += 1
    if dry_run or (not out["changed"] and not record_window):
        return out
    data["events"] = sorted(by_id.values(), key=lambda e: e.get("start") or "")
    if w and record_window:
        data.setdefault("windows", []).append(w)
    data["pulled"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = ev_path.with_suffix(".json.tmp")   # never leave a half-written calendar behind
    tmp.parent.mkdir(parents=True, exist_ok=True)   # a new install's data folder has no inbox/calendar yet (16 Nov 2026)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(ev_path)
    return out


def import_calendar(con):
    ev_path = ASSIST / "inbox" / "calendar" / "events.json"
    if not ev_path.exists():
        return
    j = json.loads(ev_path.read_text())
    pull = db.start_pull(con, "calendar", "claude-code (prototype)", note="full calendar pull 6 Jul – 23 Oct")
    ids = {}
    for e in j.get("events", []):
        iso = e["start"].split(".")[0] + ("Z" if not e["start"].endswith("Z") else "")
        att = [a for a in (e.get("attendees") or []) if a]
        item_id, _ = db.upsert_item(con, "calendar", e["id"], "event", iso, pull_id=pull, from_name=e.get("organizer"),
                                    subject=e.get("subject") or "(no subject)", text=e.get("summary"), url=e.get("webLink"),
                                    payload=e, thread=e.get("location"), noise=1 if e.get("isCancelled") else 0)
        ids[e["id"]] = item_id
    # events.json is the calendar: an event row it does not have came from an ingest bundle ("cal:<id>" copies) and would
    # show the meeting twice
    stray = [r["id"] for r in con.execute("SELECT id, external_id FROM items WHERE source_id='calendar' AND kind='event' AND noise=0")
             if r["external_id"] not in ids]
    if stray:
        con.execute(f"UPDATE items SET noise=1 WHERE id IN ({','.join('?' * len(stray))})", stray)
        log(f"calendar: {len(stray)} event rows not in the calendar file set aside")
    db.finish_pull(con, pull, available=len(j.get("events", [])), pulled=len(ids))
    rc_path = ASSIST / "inbox" / "calendar" / "reconciled.json"
    m = 0
    if rc_path.exists():
        rc = json.loads(rc_path.read_text())
        for note_id, v in rc.get("matched", {}).items():
            note_row = con.execute("SELECT id FROM items WHERE source_id='granola' AND external_id=?", (note_id,)).fetchone()
            if not note_row or v["event_id"] not in ids:
                continue
            con.execute("UPDATE meetings SET event_item_id=?, organizer=?, ends_at=?, match_quality=?, "
                        "attendees=CASE WHEN attendees IS NULL OR attendees='[]' THEN ? ELSE attendees END WHERE note_item_id=?",
                        (ids[v["event_id"]], v.get("organizer"), v.get("end"), "loose" if v.get("loose") else "exact",
                         json.dumps(v.get("attendees") or []), note_row["id"]))
            m += 1
        # a recording the matcher no longer places (it had been put in an all-day or multi-day entry, 23 Oct 2026) loses that
        # event, its end and the attendees copied from it; Sam's own matches and person holds are kept
        for note_id in rc.get("unmatched_notes", []):
            note_row = con.execute("SELECT id FROM items WHERE source_id='granola' AND external_id=?", (note_id,)).fetchone()
            if note_row:
                con.execute("UPDATE meetings SET event_item_id=NULL, organizer=NULL, ends_at=NULL, match_quality=NULL, attendees='[]' "
                            "WHERE note_item_id=? AND match_quality IN ('exact', 'loose')", (note_row["id"],))
    m += match_person_holds(con)
    from . import meeting_people   # who was in each meeting: calendar overlap, title, notes; Sam confirms the uncertain ones
    meeting_people.suggest(con, log=log)
    from . import speakers   # who said what: per-speaker statistics from the transcripts (main points come from the refresh)
    speakers.sync(con, log=log)
    log(f"calendar: {len(ids)} events, {m} meetings matched")


def infer_attendees(con):
    """Most Granola notes record no attendees. Their titles usually end "... with Marlow and Ellis" or "... with Rowan, Gray and
    Finley": resolve those names (aliases, or a first name only when nobody else has it) and record them, for meetings whose
    attendees are still only Sam. Unknown or ambiguous names are left out rather than guessed."""
    from .relevance import resolve
    n = 0
    for r in con.execute("SELECT id, title, attendees FROM meetings WHERE status != 'personal' "
                         "AND (attendees IS NULL OR attendees IN ('[]', ?))", (json.dumps([profile.name(con)]),)).fetchall():
        m = re.search(r"\bwith\s+(.+)$", r["title"] or "", re.I)
        if not m:
            continue
        names = [x.strip(" .") for x in re.split(r",|\band\b|&", m.group(1)) if x.strip(" .")]
        found = []
        for nm in names:
            if len(nm.split()) > 3 or re.search(r"\b(team|group|customer|partner|board|everyone|internal)\b", nm, re.I):
                continue
            p = resolve(con, nm)
            if p and not p["is_me"] and p["name"] not in found:
                found.append(p["name"])
        if found:
            con.execute("UPDATE meetings SET attendees=? WHERE id=?", (json.dumps([n for n in [profile.name(con)] if n] + found), r["id"]))
            con.execute("UPDATE items SET pulled_at=? WHERE id=(SELECT note_item_id FROM meetings WHERE id=?)", (db.now(), r["id"]))   # re-link
            n += 1
    return n


def match_person_holds(con):
    """A calendar hold with no invitees whose subject is one person's name ("Noel") is a meeting with that person. A recording
    that started within 30 minutes of it, and has no other attendees, is matched to it and gets that person as attendee.
    Names resolve through people_aliases (full names and aliases; a bare first name only when nobody else has it)."""
    from .relevance import resolve
    n = 0
    rows = con.execute("SELECT m.id, m.starts_at, m.attendees, m.event_item_id FROM meetings m WHERE m.status != 'personal' "
                       "AND (m.attendees IS NULL OR m.attendees IN ('[]', ?))", (json.dumps([profile.name(con)]),)).fetchall()
    used = {r[0] for r in con.execute("SELECT event_item_id FROM meetings WHERE event_item_id IS NOT NULL")}
    for r in rows:
        st = (r["starts_at"] or "")[:19]
        if not st:
            continue
        cands = [r["event_item_id"]] if r["event_item_id"] else [e["id"] for e in con.execute(
            "SELECT id FROM items WHERE kind='event' AND noise=0 AND abs(julianday(ts) - julianday(?)) <= 30.0/1440 ORDER BY abs(julianday(ts) - julianday(?))",
            (st, st)) if e["id"] not in used]
        for eid in cands:
            ev = con.execute("SELECT subject, payload FROM items WHERE id=?", (eid,)).fetchone()
            p = json.loads(ev["payload"] or "{}")
            subj = (p.get("subject") or ev["subject"] or "").strip()
            if (p.get("attendees") or []) or not subj or len(subj.split()) > 3:
                continue
            who = resolve(con, re.sub(r"^(1:1|catch[- ]?up|call|sync)\s*(with)?\s*|\s*(1:1|catch[- ]?up|sync)$", "", subj, flags=re.I).strip())
            if not who or who["is_me"]:
                continue
            con.execute("UPDATE meetings SET event_item_id=?, match_quality='person-hold', attendees=? WHERE id=?",
                        (eid, json.dumps([n for n in [profile.name(con)] if n] + [who["name"]]), r["id"]))
            used.add(eid)
            n += 1
            break
    return n


# -------------------------------------------------------------- snapshots (mail, teams, slack)
def external_id_from(links, cells, stream, file):
    for l in links:
        u = l.get("url", "")
        m = re.search(r"[?&]ItemID=([^&]+)", u)
        if m:
            return "mail:" + urllib.parse.unquote(m.group(1))
        m = re.search(r"teams\.microsoft\.com/l/message/([^/]+)/(\d+)", u)
        if m:
            return "teams:" + m.group(2)
        if "slack.com" in u:
            return "slack:" + u.rsplit("/", 1)[-1]
    return "row:" + db.fingerprint(stream + "|" + "|".join(cells[:4]))


def parse_when(cells, headers, file_year="2026"):
    """Best effort: first cell with a date; returns ISO or None."""
    for c in cells[:2]:
        m = re.search(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?", c)
        if m:
            return f"{m.group(1)}T{m.group(2) or '00:00'}:00Z"
        m = re.search(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{2}:\d{2})?", c)
        if m:
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {file_year} {m.group(3) or '00:00'}", "%d %b %Y %H:%M")
                return dt.strftime("%Y-%m-%dT%H:%M:00Z")
            except ValueError:
                pass
    return None


def import_snapshots(con):
    streams = legacy.snapshots()
    total = 0
    for stream, tables in streams.items():
        sid = {"outlook.inbox": "outlook.inbox", "outlook.sent": "outlook.sent", "teams": "teams", "slack": "slack"}.get(stream)
        if not sid:
            continue
        for t in tables:
            pull = db.start_pull(con, sid, "claude-code (prototype)", note=f"{t['title']} · {t['heading']}")
            hdr = [h.lower() for h in t["headers"]]
            def col(row, *names):
                for n in names:
                    for i, h in enumerate(hdr):
                        if n in h and i < len(row):
                            return row[i]
                return None
            n = 0
            m = re.search(r"(\d{4})-(\d{2})", t["file"])
            year = m.group(1) if m else "2026"
            for r in t["rows"]:
                cells = r["c"]
                ts = parse_when(cells, hdr, year) or f"{year}-01-01T00:00:00Z"
                subject = col(cells, "subject", "first line", "message", "event") or (cells[2] if len(cells) > 2 else "")
                gist = col(cells, "gist", "note", "first line") or ""
                frm = col(cells, "from", "sender") or ""
                where = col(cells, "where", "conversation", "chat")
                noise = 1 if re.search(r"\bnoise\b", " ".join(cells[-2:]), re.I) else 0
                db.upsert_item(con, sid, external_id_from(r["l"], cells, stream, t["file"]), STREAM_TO_KIND.get(stream, "chat"), ts, pull_id=pull,
                               from_name=frm, subject=subject, text=gist if gist != subject else None, thread=where,
                               url=(r["l"][0]["url"] if r["l"] else None), noise=noise,
                               retention="hr_legal" if re.search(r"\bHR\b|legal|people matter|rupture|alerte|termination", " ".join(cells), re.I) else "general",
                               from_person_id=db.resolve_person(con, frm))
                n += 1
            db.finish_pull(con, pull, pulled=n)
            total += n
    log(f"snapshots: {total} items")


# -------------------------------------------------------------- facts
def import_facts(con):
    run = db.start_run(con, "importer", input_summary={"files": ["TASKS.md"]})
    tasks = legacy.parse_tasks((ASSIST / "TASKS.md").read_text())
    kinds = {"active": "owed_by_me", "waiting": "owed_to_me", "someday": "someday", "done": "owed_by_me"}
    nc = 0
    for t in tasks:
        cid, created = db.upsert_commitment(con, kinds.get(t["group"], "owed_by_me"), t["title"], run_id=run, context=t["context"],
                                            counterparty=t.get("person"), origin=t["origin"], status="done" if t["done"] else "open",
                                            links=[{"url": l["url"], "label": l["label"]} for l in t["links"]])
        db.tag_mentions(con, "commitment", cid, t["title"] + " " + (t["context"] or ""))
        nc += created
    # memory/decisions.md is no longer imported: decisions were retired (Sam, 26 Oct 2026, migration m026)
    db.finish_run(con, run, output_json={"commitments_new": nc})
    log(f"facts: {nc} new commitments (of {len(tasks)})")


# -------------------------------------------------------------- documents
def import_documents(con):
    n = 0
    def add(path, section, label=None):
        nonlocal n
        if not path.exists():
            return
        text, meta = legacy.read(path)
        db.upsert_document(con, str(path.relative_to(ASSIST)), section, label or legacy.title_of(path, text, meta), text, str(path.relative_to(ASSIST)), meta)
        n += 1
    for p in legacy.md_files(ASSIST / "briefs"):
        add(p, "Weekly reviews" if p.name.endswith("-review.md") else "Briefs")
    for p in sorted((ASSIST / "inbox" / "backfill").glob("*.md")):
        add(p, "Analyses")
    for p in legacy.md_files(ASSIST / "inbox" / "live"):
        add(p, "Pulls")
    for p in legacy.md_files(ASSIST / "drafts"):
        add(p, "Drafts")
    add(ASSIST / "CLAUDE.md", "Memory", "Working memory (CLAUDE.md)")
    add(ASSIST / "memory" / "glossary.md", "Memory", "Glossary")
    from . import soul
    from .promptkit import USER
    for name, label in [("context/me.md", "Me"), (USER.plan_file.replace("memory/", "", 1), USER.plan_title), ("context/strategy.md", "Strategy frame"),
                        ("context/preferences.md", "Writing and meeting preferences"), ("context/company.md", org.name() or "Company"), ("context/soul.md", "The soul of the company"), (soul.files()["cpo"].replace("memory/", "", 1), f"The soul of a {USER.role_short}"),
                        ("context/assistant-soul.md", "SleePO's soul")]:
        add(ASSIST / "memory" / name, "Context", label)
    for name, label in [("DESIGN.md", "System design"), ("DESIGN-UI.md", "UI review and redesign"), ("DESIGN-SYSTEM.md", "From prototype to system"), ("DESIGN-FRONTEND.md", "Front-end framework proposal"), ("README.md", "How to use")]:
        add(ASSIST / name, "System", label)
    # the latest brief is also a run
    briefs = [p for p in legacy.md_files(ASSIST / "briefs") if not p.name.endswith("-review.md")]
    for p in briefs:
        text, _ = legacy.read(p)
        exists = con.execute("SELECT 1 FROM runs WHERE agent='claude-code:/brief' AND input_summary=?", (json.dumps({"brief": p.name}),)).fetchone()
        if not exists:
            rid = db.start_run(con, "claude-code:/brief", input_summary={"brief": p.name})
            db.finish_run(con, rid, output_md=text)
    log(f"documents: {n}")


def run_all(con):
    import_sources(con)
    import_people(con)
    import_initiatives(con)
    import_granola(con)
    import_calendar(con)
    import_snapshots(con)
    import_facts(con)
    import_documents(con)
    con.commit()
    # rebuild FTS for documents (external content table)
    con.execute("INSERT INTO docs_fts(docs_fts) VALUES ('rebuild')")
    con.commit()
