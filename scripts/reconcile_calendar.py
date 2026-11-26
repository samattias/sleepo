#!/usr/bin/env python3
"""Match Granola notes to Outlook calendar events.

Granola has no calendar access in this tenant, so its notes carry only a start time (and their transcript, which says when
the recording stopped). This script pairs each note with the calendar event that was running when the note started, and
writes inbox/calendar/reconciled.json:

  {"matched": {"<note id>": {"event_id", "subject", "start", "end", "organizer", "attendees": [names], "webLink"}},
   "unmatched_notes": [note ids], "unrecorded_events": [event ids with no note],
   "stats": {...}}

This is the only matcher: the Meetings page shows its pairs and overlays every other recording as Granola-only.
Inputs: inbox/calendar/events.json (written by the calendar pull) and ../Granola Export/raw-json.
Usage: python3 scripts/reconcile_calendar.py      (build_ui.py reads the result)
"""
import json
import sys
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from assist.db import ASSIST  # noqa: E402  (the user's data folder: ASSIST_HOME, ~/.assist/home, else this folder)
RAW = ASSIST.parent / "Granola Export" / "raw-json"
EVENTS = ASSIST / "inbox" / "calendar" / "events.json"
OUT = ASSIST / "inbox" / "calendar" / "reconciled.json"
TOLERANCE = timedelta(minutes=12)   # note may start a little before/after the slot
WIDE = timedelta(minutes=30)        # second pass: a note started up to this long before or after a meeting began
INTO = timedelta(minutes=10)        # a recording that started before a meeting must still be running this far into it (fits)
LONGEST = timedelta(hours=8)        # 23 Oct 2026: a call was matched to an all-day "PTO" entry spanning nine days
NOISE = re.compile(r"^(busy|hold|block|focus|lunch|ooo|out of office|dto|pto|new event|untitled)?$", re.I)
TRAVEL = re.compile(r"^(move|travel|head|drive|walk|commute|taxi|train|flight)( back)? to\b", re.I)   # a journey, not a meeting


def iso(s, tz):
    """Calendar dateTime + timeZone -> aware UTC datetime (the connector returns UTC)."""
    s = s.split(".")[0]
    dt = datetime.fromisoformat(s)
    if tz and tz.upper() != "UTC":
        try:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def when(s):
    """A Granola time ("2026-10-26T15:41:45.297Z") -> aware UTC datetime, or None."""
    try:
        dt = datetime.fromisoformat(re.sub(r"\.\d+", "", s or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def name_of(email):
    local = (email or "").split("@")[0]
    parts = [p for p in re.split(r"[._\-]+", local) if p]
    if not parts:
        return email
    return " ".join(p.capitalize() if p.islower() else p for p in parts)


def note_of(n):
    """A raw Granola note -> {id, title, _s: when it started, _e: its last transcript line (None with no transcript)}."""
    start = when(n.get("created_at"))
    if not start:
        return None
    ends = [t for t in (when(x.get("end_time") or x.get("start_time")) for x in (n.get("transcript") or []) if isinstance(x, dict)) if t]
    heard = {" ".join(((x.get("speaker") or {}).get("name") or "").lower().split()) for x in (n.get("transcript") or []) if isinstance(x, dict)}
    return {"id": n["id"], "title": n.get("title") or "Untitled", "_s": start, "_e": max(ends) if ends else None, "heard": heard - {""},
            "attendees": [a.get("name") for a in (n.get("attendees") or []) if a.get("name")]}


def wanted(e):
    """0 for a meeting with attendees, 1 for a private block or a journey: a recording goes to a meeting before either. 4 Nov
    2026, Lisbon: the itinerary's "Move to Contoso" carries everyone on the trip, so it looked like a meeting."""
    subject = (e.get("subject") or "").strip()
    return 0 if (e.get("attendees") and not NOISE.match(subject) and not TRAVEL.match(subject)) else 1


def inside(n, e):
    """Seconds of the recording within the event's time (0 when the recording's end is unknown)."""
    if not n["_e"]:
        return 0.0
    return max(0.0, (min(n["_e"], e["_e"]) - max(n["_s"], e["_s"])).total_seconds())


def fits(n, e):
    """A recording that started before the event is that event only if it was still running INTO it (or at its end, for a
    shorter event), or half of it falls within it, or everyone else invited was heard in it (a 1:1 started early). A quick
    call just before a meeting is a call of its own: 26 Oct 2026, ten minutes with Gray, 15:41 to 15:51, became the 16:00 UX
    review (Lane, Rowan and Gray) while the review's own recording was not in yet. A note with no transcript has no known
    end and keeps the start rule."""
    if n["_s"] >= e["_s"] or not n["_e"]:
        return True
    length = (n["_e"] - n["_s"]).total_seconds()
    if n["_e"] >= min(e["_s"] + INTO, e["_e"]) or (length > 0 and inside(n, e) >= length / 2):
        return True
    others = {" ".join(name_of(a).lower().split()) for a in (e.get("attendees") or []) if a and "sam.doe" not in a.lower()}
    return bool(others) and others <= n["heard"]


RSVP = {"organizer": 0, "accepted": 0, "tentative": 1, "none": 2, "notResponded": 2, "declined": 3}


def evidence(n, e):
    """How surely the recording is this event, from what it holds: the share of the other invitees heard speaking, plus half
    when the note's title names one of them ("… with Rowan"). 27 Oct 2026: Sam's 1:1 with Rowan and the CFT meeting (Rowan among
    eight invited) both started at 15:00, and the tie went to the CFT by list order although Rowan alone was heard."""
    others = {" ".join(name_of(a).lower().split()) for a in (e.get("attendees") or []) if a and "sam.doe" not in a.lower()}
    if not others:
        return 0.0
    words = set(re.findall(r"[a-z]+", (n.get("title") or "").lower()))
    named = any(o.split()[0] in words for o in others if o)
    return len(others & n["heard"]) / len(others) + (0.5 if named and len(others) <= 3 else 0.0)


def match(notes, ev):
    """{note id: (event, loose)}, notes in the order they started. First pass: the event running when the note started, or
    starting up to TOLERANCE after it (a meeting with attendees before a block, then the closest start). Second pass: notes
    still unmatched, up to WIDE before or after a meeting with attendees began. Either way the recording must fit it. Among
    events that compete (two meetings at 15:00), the one the recording shows most evidence of wins, then the closest start,
    then the one Sam accepted or organised over one he never answered. A note that started during blocks or journeys only
    waits for the second pass, and keeps the block when no meeting takes it (4 Nov 2026, Lisbon: recorded from 07:59 for the
    08:15 contoso meeting, it went to "Move to Contoso" at 08:00)."""
    gap = lambda n, e: abs((e["_s"] - n["_s"]).total_seconds())
    rank = lambda n, e: (wanted(e), -evidence(n, e), gap(n, e), RSVP.get(e.get("response") or "", 1))
    out, used, blocks = {}, set(), {}
    for n in sorted(notes, key=lambda x: x["_s"]):
        cands = [e for e in ev if e["_s"] - TOLERANCE <= n["_s"] <= e["_e"] and e["id"] not in used and fits(n, e)]
        if cands:
            e = min(cands, key=lambda e: rank(n, e))
            if wanted(e):
                blocks[n["id"]] = cands
                continue
            out[n["id"]] = (e, False)
            used.add(e["id"])
    for n in sorted(notes, key=lambda x: x["_s"]):
        if n["id"] in out:
            continue
        cands = [e for e in ev if gap(n, e) <= WIDE.total_seconds() and e["id"] not in used and wanted(e) == 0 and fits(n, e)]
        left = [e for e in blocks.get(n["id"], []) if e["id"] not in used]
        if cands:
            e = min(cands, key=lambda e: (-evidence(n, e), gap(n, e), RSVP.get(e.get("response") or "", 1)))
            out[n["id"]] = (e, True)
            used.add(e["id"])
        elif left:
            e = min(left, key=lambda e: rank(n, e))
            out[n["id"]] = (e, False)
            used.add(e["id"])
    return out


def main():
    if not EVENTS.exists():
        raise SystemExit(f"{EVENTS} not found; run the calendar pull first")
    events = json.loads(EVENTS.read_text()).get("events", [])
    ev = []
    for e in events:
        if e.get("isCancelled"):
            continue
        try:
            s, t = iso(e["start"], e.get("start_tz")), iso(e["end"], e.get("start_tz"))
        except Exception:
            continue
        if e.get("isAllDay") or t - s > LONGEST:   # PTO, travel, a week-long hold: a call inside one is not that event
            continue
        ev.append({**e, "_s": s, "_e": t})
    notes = []
    for p in RAW.glob("*.json"):
        try:
            n = note_of(json.loads(p.read_text()))
        except Exception:
            continue
        if n:
            notes.append(n)

    matched = {}
    for nid, (e, loose) in match(notes, ev).items():
        att = [name_of(a) for a in (e.get("attendees") or []) if a and "sam.doe" not in a.lower()]
        matched[nid] = {"event_id": e["id"], "subject": e.get("subject") or "", "start": e["_s"].isoformat(),
                        "end": e["_e"].isoformat(), "organizer": name_of(e.get("organizer")),
                        "attendees": att, "webLink": e.get("webLink", ""), "location": e.get("location") or "", **({"loose": True} if loose else {})}
    used = {m["event_id"] for m in matched.values()}
    unmatched = [n["id"] for n in notes if n["id"] not in matched]
    now = datetime.now(timezone.utc)
    unrecorded = [e["id"] for e in ev if e["id"] not in used and e["_e"] < now and wanted(e) == 0]
    stats = {"notes": len(notes), "events": len(ev), "matched": len(matched), "unmatched_notes": len(unmatched),
             "unrecorded_meetings_with_attendees": len(unrecorded), "tolerance_minutes": int(TOLERANCE.total_seconds() // 60),
             "run": now.isoformat()}
    OUT.write_text(json.dumps({"matched": matched, "unmatched_notes": unmatched, "unrecorded_events": unrecorded, "stats": stats},
                              indent=1, ensure_ascii=False))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
