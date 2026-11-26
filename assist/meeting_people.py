"""Who was in each meeting. Granola records almost no attendees (it has no link to the calendar), so they are worked out
backwards and Sam confirms the uncertain ones with a tick or a cross.

Evidence, per recorded meeting (confidence in brackets):
- Granola's own attendee list, when it has one (0.95)
- speakers Granola named from the call's display names (Teams, Zoom, Meet; since late Sep 2026): 0.95 when they spoke
  at least 5 lines, 0.5 below that (a line or two is often a misattribution)
- the calendar event the recording was matched to: its invitees (0.95 exact match, 0.85 loose)
- calendar events overlapping the recording: one such event with invitees (0.85); several (0.5 each, Sam picks)
- the meeting title, "... with Marlow and Ellis" (0.8); a hold named after one person, "Noel" (0.8)
- full names said in the notes (0.4)
Each person keeps the best evidence and every source. Suggestions at 0.8 or more count as attendees straight away; lower
ones wait for Sam. Sam's tick (confirmed) and cross (rejected) are final: matching never re-adds or removes them.
meetings.attendees is rebuilt from this table (Sam + confirmed + accepted), so prep, replies, the brief and people
timelines all see the same people. Group mailboxes (elt@...) are shown as a group, not expanded.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import db
from . import profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS meeting_people (
  meeting_id   INTEGER NOT NULL REFERENCES meetings(id),
  key          TEXT NOT NULL,              -- person:<id> | email:<address> | name:<lower name>
  person_id    INTEGER REFERENCES people(id),
  name         TEXT NOT NULL,
  email        TEXT,
  confidence   REAL NOT NULL,
  sources      TEXT,                       -- JSON list: granola | speaker | event | overlap | title | hold | notes | sam
  evidence     TEXT,                       -- e.g. the calendar subject that suggested them
  status       TEXT DEFAULT 'suggested',   -- suggested | confirmed | rejected
  decided_at   TEXT,
  updated_at   TEXT,
  PRIMARY KEY (meeting_id, key)
);
"""
ACCEPT = 0.8
ME = db.ME_LOOSE   # the one definition, assist/db.py
GROUP = re.compile(r"^(elt|team|all|staff|everyone|leadership|product|sales|marketing|engineering|rd|dev|ops|support|exec)[\w.-]*@", re.I)


def ensure_schema(con):
    con.executescript(SCHEMA)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _name_of(email):
    local = (email or "").split("@")[0]
    parts = [p for p in re.split(r"[._\-]+", local) if p]
    return " ".join(p.capitalize() if p.islower() else p for p in parts) or email


def _who(con, raw):
    """(key, person_id, name, email) for an address or a name. People resolve by identity; unknown addresses stay as they are."""
    from .relevance import resolve
    raw = (raw or "").strip()
    if not raw or ME.search(raw):
        return None
    email = raw if "@" in raw else None
    p = resolve(con, raw)
    if p and p["is_me"]:
        return None
    if p:
        return f"person:{p['id']}", p["id"], p["name"], email
    if email:
        return f"email:{email.lower()}", None, ("Group: " + email.split("@")[0].upper()) if GROUP.match(email) else _name_of(email), email
    return None   # an unresolved bare name is not evidence enough


def _event_attendees(payload):
    p = json.loads(payload or "{}")
    return [a for a in (p.get("attendees") or []) if a] + ([p["organizer"]] if p.get("organizer") else []), (p.get("subject") or "").strip()


def candidates(con, m):
    """Evidence for one meeting row -> {key: {person_id, name, email, confidence, sources, evidence}}."""
    out = {}

    def add(raw, conf, source, evidence=""):
        w = _who(con, raw)
        if not w:
            return
        key, pid, name, email = w
        c = out.setdefault(key, {"person_id": pid, "name": name, "email": email, "confidence": 0.0, "sources": [], "evidence": ""})
        if conf > c["confidence"]:
            c["confidence"], c["evidence"] = conf, evidence or c["evidence"]
        if source not in c["sources"]:
            c["sources"].append(source)
        c["email"] = c["email"] or email

    note = con.execute("SELECT payload, text FROM items WHERE id=?", (m["note_item_id"],)).fetchone()
    np = json.loads((note["payload"] if note else None) or "{}")
    for a in np.get("attendees") or []:
        add(a.get("email") or a.get("name"), 0.95, "granola")
    for nm, lines in (np.get("_speakers") or {}).items():
        add(nm, 0.95 if lines >= 5 else 0.5, "speaker", f"spoke {lines} line{'s' if lines != 1 else ''} in the recording")
    # the matched calendar event
    matched = None
    if m["event_item_id"]:
        ev = con.execute("SELECT payload FROM items WHERE id=?", (m["event_item_id"],)).fetchone()
        if ev:
            att, subj = _event_attendees(ev["payload"])
            matched = m["event_item_id"]
            for a in att:
                add(a, 0.95 if (m["match_quality"] or "") in ("exact", "sam", "person-hold") else 0.85, "event", subj)
    # the title: "... with Marlow and Ellis"
    titled = set()
    t = re.search(r"\bwith\s+(.+)$", m["title"] or "", re.I)
    if t:
        for nm in [x.strip(" .") for x in re.split(r",|\band\b|&", t.group(1)) if x.strip(" .")]:
            if len(nm.split()) <= 3 and not re.search(r"\b(team|group|customer|partner|board|everyone|internal)\b", nm, re.I):
                w = _who(con, nm)
                if w:
                    titled.add(w[0])
                add(nm, 0.8, "title", m["title"])
    # other calendar events overlapping the recording (Sam may have recorded in a different slot than the matched one).
    # When the title names people, an overlapping event without any of them is probably a neighbouring meeting: Sam decides.
    st = (m["starts_at"] or "")[:19]
    if st:
        evs = []
        # an event that STARTS near the recording (20 min before to 15 after): a meeting that merely ends as this one starts
        # is the previous slot of a back-to-back afternoon, not evidence
        for e in con.execute("SELECT id, payload FROM items WHERE kind='event' AND noise=0 AND julianday(ts) BETWEEN julianday(?) - 20.0/1440 "
                             "AND julianday(?) + 15.0/1440", (st, st)):
            att, subj = _event_attendees(e["payload"])
            if e["id"] != matched and [a for a in att if not ME.search(a)]:
                evs.append((att, subj))
        for att, subj in evs:
            keys = {w[0] for w in (_who(con, a) for a in att) if w}
            conf = 0.85 if (len(evs) == 1 and not matched and (not titled or keys & titled)) else 0.5
            for a in att:
                add(a, conf, "overlap", subj)
    # full names said in the notes
    text = ((note["text"] if note else "") or "")[:20000].lower()
    if text:
        for p in con.execute("SELECT id, name FROM people WHERE is_me=0"):
            if " " in p["name"] and p["name"].lower() in text:
                add(p["name"], 0.4, "notes")
    return out


def _rebuild_attendees(con, mid):
    rows = con.execute("SELECT name, person_id FROM meeting_people WHERE meeting_id=? AND (status='confirmed' OR (status='suggested' AND confidence >= ?)) "
                       "ORDER BY status='confirmed' DESC, confidence DESC, name", (mid, ACCEPT)).fetchall()
    names = [n for n in [profile.name(con)] if n] + [r["name"] for r in rows if not r["name"].startswith("Group: ")]
    groups = [r["name"] for r in rows if r["name"].startswith("Group: ")]
    con.execute("UPDATE meetings SET attendees=? WHERE id=?", (json.dumps(names + groups), mid))
    con.execute("UPDATE items SET pulled_at=? WHERE id=(SELECT note_item_id FROM meetings WHERE id=?)", (_now(), mid))   # re-link people


def suggest(con, meeting_ids=None, log=print):
    """Recompute suggestions (never touching Sam's confirmed or rejected people) and rebuild attendees."""
    ensure_schema(con)
    q = "SELECT * FROM meetings WHERE status != 'personal'" + (f" AND id IN ({','.join('?' * len(meeting_ids))})" if meeting_ids else "")
    rows = con.execute(q, list(meeting_ids or [])).fetchall()
    now, n_sugg = _now(), 0
    for m in rows:
        # an address that was nobody when it was recorded resolves once the person is known (a partner added to People later)
        for r in con.execute("SELECT key, email FROM meeting_people WHERE meeting_id=? AND person_id IS NULL AND email IS NOT NULL", (m["id"],)).fetchall():
            w = _who(con, r["email"])
            if w and w[1]:
                con.execute("UPDATE meeting_people SET person_id=?, name=?, updated_at=? WHERE meeting_id=? AND key=?", (w[1], w[2], now, m["id"], r["key"]))
        rows_d = con.execute("SELECT key, person_id FROM meeting_people WHERE meeting_id=? AND status IN ('confirmed','rejected')", (m["id"],)).fetchall()
        decided = {r["key"] for r in rows_d} | {f"person:{r['person_id']}" for r in rows_d if r["person_id"]}
        cands = candidates(con, m)
        con.execute("DELETE FROM meeting_people WHERE meeting_id=? AND status='suggested'", (m["id"],))
        for key, c in cands.items():
            if key in decided:
                continue
            con.execute("INSERT INTO meeting_people (meeting_id, key, person_id, name, email, confidence, sources, evidence, status, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?, 'suggested', ?)",
                        (m["id"], key, c["person_id"], c["name"], c["email"], round(c["confidence"], 2), json.dumps(c["sources"]), c["evidence"][:200], now))
            n_sugg += 1
        _rebuild_attendees(con, m["id"])
    con.commit()
    log(f"meeting people: {len(rows)} meetings, {n_sugg} suggestions")
    return {"meetings": len(rows), "suggestions": n_sugg}


def listing(con, mid):
    ensure_schema(con)
    out = []
    for r in con.execute("SELECT * FROM meeting_people WHERE meeting_id=? ORDER BY CASE status WHEN 'confirmed' THEN 0 WHEN 'suggested' THEN 1 ELSE 2 END, "
                         "confidence DESC, name", (mid,)):
        d = dict(r)
        d["sources"] = json.loads(d["sources"] or "[]")
        d["accepted"] = d["status"] == "confirmed" or (d["status"] == "suggested" and d["confidence"] >= ACCEPT)
        out.append(d)
    return out


def decide(con, mid, key=None, status="confirmed", who=None):
    """Sam's tick or cross on a suggestion, or a person he adds (who = name or email)."""
    ensure_schema(con)
    if status not in ("confirmed", "rejected", "suggested"):
        raise ValueError("bad status")
    now = _now()
    if who:
        w = _who(con, who)
        if not w:
            raise ValueError("Unknown person: use a full name from People or an email address")
        key, pid, name, email = w
        con.execute("INSERT INTO meeting_people (meeting_id, key, person_id, name, email, confidence, sources, status, decided_at, updated_at) "
                    "VALUES (?,?,?,?,?,1.0,'[\"sam\"]','confirmed',?,?) ON CONFLICT(meeting_id, key) DO UPDATE SET status='confirmed', "
                    "confidence=1.0, decided_at=excluded.decided_at, updated_at=excluded.updated_at", (mid, key, pid, name, email, now, now))
    else:
        if not con.execute("SELECT 1 FROM meeting_people WHERE meeting_id=? AND key=?", (mid, key)).fetchone():
            raise ValueError("no such suggestion")
        con.execute("UPDATE meeting_people SET status=?, decided_at=?, updated_at=? WHERE meeting_id=? AND key=?",
                    (status, now if status != "suggested" else None, now, mid, key))
    _rebuild_attendees(con, mid)
    con.commit()
    try:   # the people timelines follow straight away
        from . import entities
        entities.link(con, log=lambda *_: None)
    except Exception:
        pass


def review_queue(con, days=60, limit=40):
    """Meetings where Sam's input would help: undecided suggestions below the auto-accept line, or nobody but Sam."""
    ensure_schema(con)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for m in con.execute("SELECT id, title, starts_at, attendees FROM meetings WHERE status != 'personal' AND starts_at >= ? ORDER BY starts_at DESC", (since,)):
        open_ = con.execute("SELECT COUNT(*) FROM meeting_people WHERE meeting_id=? AND status='suggested' AND confidence < ? AND sources != '[\"notes\"]'",
                            (m["id"], ACCEPT)).fetchone()[0]
        alone = json.loads(m["attendees"] or "[]") in ([], [profile.name(con)])
        if open_ or alone:
            out.append({"id": f"m-{m['id']}", "title": m["title"], "starts_at": m["starts_at"], "open": open_, "alone": alone})
    out.sort(key=lambda x: (not x["alone"], x["starts_at"] and -datetime.fromisoformat(x["starts_at"][:19]).timestamp()))   # nobody known first
    return out[:limit]
