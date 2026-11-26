"""Granola transcripts as structured data for the transcript view.

Granola records two channels: Sam's microphone ("Sam Doe") and everyone else on the call. Since late September 2026
Granola names the speakers on the second channel from the call's display names (Teams, Zoom, Meet), with no calendar
needed; those names are resolved to people here. Unnamed lines ("Other participant", older notes and in-person
meetings) fall back as before: in a 1:1 the other side is named from the calendar or the note's attendees (marked as
inferred); in a group meeting it is "Others", with the attendee list alongside.
"""
import json
import re

from . import db, views
from . import profile

LINE = re.compile(r"^\*\*\[(\d\d):(\d\d):(\d\d)\] ([^:*]+):\*\*\s?(.*)$")


def _file(con, mid):
    m = re.fullmatch(r"(?:m-)?(\d+)", mid or "")   # "m-15567" and plain "15567" (links built either way)
    if not m:
        return None, None
    row = con.execute("SELECT m.*, i.external_id, i.url AS granola, e.payload AS event_payload, e.subject AS cal_subject, e.url AS outlook "
                      "FROM meetings m JOIN items i ON i.id=m.note_item_id LEFT JOIN items e ON e.id=m.event_item_id WHERE m.id=?", (int(m.group(1)),)).fetchone()
    if not row:
        return None, None
    short = (row["external_id"] or "")[-6:]
    d = views.GRANOLA / "transcripts"
    hit = next(iter(d.glob(f"*[[]{short}].md")), None) if short and d.exists() else None
    return row, hit


def _continuations(con, row):
    """Transcript files of notes appended to this one because the recording was resumed in them."""
    r = con.execute("SELECT payload FROM items WHERE id=?", (row["note_item_id"],)).fetchone()
    ids = (json.loads(r["payload"] or "{}") if r else {}).get("_continued_by") or []
    d = views.GRANOLA / "transcripts"
    return [f for f in (next(iter(d.glob(f"*[[]{i[-6:]}].md")), None) for i in ids) if f]


def _dt(s):
    from datetime import datetime, timezone
    s = (s or "").replace("Z", "")[:19]
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() if s else None


def overlapping_event(con, starts, ends):
    """The calendar event (with other attendees, not yet holding a recording) this note overlaps: start within 20 min,
    or at least half the note's time inside the event."""
    s = _dt(starts)
    if s is None:
        return None
    e = _dt(ends) or s + 1800
    best = None
    for r in con.execute("SELECT * FROM items WHERE kind='event' AND ts BETWEEN datetime(?, 'unixepoch', '-12 hours') AND datetime(?, 'unixepoch', '+12 hours') "
                         "AND id NOT IN (SELECT event_item_id FROM meetings WHERE event_item_id IS NOT NULL)", (s, s)):
        p = json.loads(r["payload"] or "{}")
        if p.get("isCancelled") or p.get("isAllDay"):
            continue
        es, ee = _dt(p.get("start") or r["ts"]), _dt(p.get("end"))
        if es is None or ee is None:
            continue
        overlap, gap = min(e, ee) - max(s, es), abs(es - s)
        if overlap > 0 and (gap <= 1200 or overlap >= (e - s) / 2) and (best is None or gap < best[0]):
            best = (gap, r)
    return best[1] if best else None


def load(con, mid):
    row, path = _file(con, mid)
    if not row or row["status"] == "personal":   # personal syncs are out of scope (CLAUDE.md): never served
        return None
    note_att = [a for a in json.loads(row["attendees"] or "[]") if a and not profile.is_me(a)]
    ev = json.loads(row["event_payload"] or "{}")
    outlook, cal_subject = row["outlook"], row["cal_subject"]
    if not ev:   # no server match: use the calendar event it overlaps (same rule as the Meetings page)
        host = overlapping_event(con, row["starts_at"], row["ends_at"])
        if host:
            ev, outlook, cal_subject = json.loads(host["payload"] or "{}"), host["url"], host["subject"]
    cal_att = [a for a in ev.get("attendees") or [] if not db.ME_ADDRESS.search(a)]
    cal_names = [re.sub(r"@.*$", "", a).replace(".", " ").title() if "@" in a else a for a in cal_att]
    others = []
    for a in (cal_att or note_att):   # prefer calendar addresses: they resolve to people reliably
        pid = db.resolve_person(con, a) or db.resolve_person(con, re.sub(r"@.*$", "", a).replace(".", " ")) if a else None
        p = con.execute("SELECT name FROM people WHERE id=?", (pid,)).fetchone() if pid else None
        n = p["name"] if p else (re.sub(r"@.*$", "", a).replace(".", " ").title() if "@" in a else a)
        if n not in others:
            others.append(n)
    others = others or note_att or cal_names
    one_to_one = len(others) == 1
    other_label = others[0] if one_to_one else "Others"

    out = {"id": mid, "title": (row["title"] or cal_subject or "Untitled meeting").strip(), "calendar_title": cal_subject or "",
           "starts_at": row["starts_at"], "ends_at": row["ends_at"], "granola": row["granola"] or "", "outlook": outlook or ev.get("webLink") or "",
           "attendees": others, "status": row["status"], "other_label": other_label, "other_inferred": one_to_one,
           "summary_md": "", "turns": [], "segments": 0, "available": bool(path), "item_id": row["note_item_id"]}
    if not path:
        from . import granola_shots
        out["shots"] = granola_shots.for_meeting(con, row["id"])
        return out
    files = [path] + _continuations(con, row)   # a recording resumed in another note (assist/granola_stitch.py)
    summaries, body = [], ""
    for i, f in enumerate(files):
        text = f.read_text(errors="ignore")
        if "## AI Summary" in text:
            s = text.split("## AI Summary", 1)[1].split("\n## Transcript", 1)[0]
            s = "\n".join(l for l in s.splitlines() if not l.startswith("Chat with meeting transcript")).strip()
            summaries.append(s if not i else "# Continued recording\n\n" + s)
        body += "\n" + (text.split("## Transcript", 1)[1] if "## Transcript" in text else "")
        # a call recorded on Sam's microphone alone, its speakers split afterwards (Granola Export/speaker-fixes, 26 Oct 2026)
        if "_Speakers split from one microphone" in text:
            out["speakers_split"] = True
    out["summary_md"] = "\n\n".join(summaries)
    names = {}

    def speaker(raw):   # Granola's display name ("Marlow Harlow", "Nell Sutton") -> the person's name in SleePO
        if raw not in names:
            pid = db.resolve_person(con, raw)
            p = con.execute("SELECT name FROM people WHERE id=?", (pid,)).fetchone() if pid else None
            names[raw] = p["name"] if p else raw
        return names[raw]

    segs, start = [], None
    for line in body.splitlines():
        m = LINE.match(line.strip())
        if m:
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            start = secs if start is None else start
            rel = secs - start if secs >= start else secs + 86400 - start   # meetings that cross midnight
            who = m.group(4).strip()
            me = profile.is_me(who)   # the microphone's label is the user's (assist/profile.py speaker_label)
            segs.append({"t": rel, "clock": f"{m.group(1)}:{m.group(2)}", "me": me, "text": m.group(5).strip(),
                         "speaker": None if me or who == "Other participant" else speaker(who)})
        elif segs and line.strip() and not line.startswith("#"):
            segs[-1]["text"] += " " + line.strip()
    out["segments"] = len(segs)
    # consecutive lines from the same speaker become one turn
    for s in segs:
        last = out["turns"][-1] if out["turns"] else None
        if last and last["me"] == s["me"] and last["speaker"] == s["speaker"] and s["t"] - last["end"] <= 90:
            last["lines"].append(s["text"])
            last["end"] = s["t"]
        else:
            out["turns"].append({"t": s["t"], "end": s["t"], "clock": s["clock"], "me": s["me"], "speaker": s["speaker"], "lines": [s["text"]]})
    words = lambda me: sum(len(" ".join(t["lines"]).split()) for t in out["turns"] if t["me"] == me)
    out["words"] = {"me": words(True), "others": words(False)}
    # words per named speaker, most first; a name with only a line or two is often a misattribution, so it is kept
    # in the turns but not added to the attendees
    talk = {}
    for t in out["turns"]:
        if t["speaker"]:
            talk[t["speaker"]] = talk.get(t["speaker"], 0) + len(" ".join(t["lines"]).split())
    out["speakers"] = [{"name": n, "words": w} for n, w in sorted(talk.items(), key=lambda kv: -kv[1])]
    for sp in out["speakers"]:
        if sp["words"] >= 40 and sp["name"] not in out["attendees"]:
            out["attendees"].append(sp["name"])
    out["duration"] = segs[-1]["t"] if segs else 0
    from . import granola_shots   # screenshots of the shared screen, at their second of the recording
    out["shots"] = granola_shots.for_meeting(con, row["id"], start)
    return out
