"""Granola notes as meetings, repairing a recording resumed in the wrong note.

Stopping a recording and then pressing "resume" on an older note (Sam, 12 Oct 2026: today's meeting resumed in an empty
note from Friday 9 Oct) puts the second half of a meeting in a note dated days earlier. Granola's API is read-only, so
the repair happens here, when notes are read:

- A note whose recording starts more than RESUMED after the note was made is dated by its recording, not by the note.
- A note with a long silence inside its transcript (an old meeting, then a resumed one) is split there; the later part
  becomes its own piece, id "<note id>~2".
- A resumed piece that starts within JOIN of another note's last words is the rest of that meeting: its transcript and
  summary are appended to that note (key "_continued_by" lists what was added) and it is not a meeting of its own.
  Back-to-back meetings recorded normally are never joined: only resumed pieces are.

Standard library only: scripts/collect_granola.py (system Python) imports it too.
"""
from datetime import datetime, timedelta, timezone

RESUMED = timedelta(hours=6)
JOIN = timedelta(minutes=10)


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc) if s else None


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stitch(notes):
    """notes: Granola note dicts (with 'transcript'). Returns (meetings, joins): the notes to treat as meetings, and
    [(piece id, host id)] for each piece appended to another note. Inputs are not modified."""
    pieces = []
    for n in notes:
        segs = [s for s in (n.get("transcript") or []) if s.get("start_time")]
        if not segs:
            pieces.append(dict(n))
            continue
        parts, cur = [], [segs[0]]
        for a, b in zip(segs, segs[1:]):
            if _t(b["start_time"]) - _t(a.get("end_time") or a["start_time"]) > RESUMED:
                parts.append(cur)
                cur = []
            cur.append(b)
        parts.append(cur)
        for i, part in enumerate(parts):
            p = dict(n)
            p["transcript"] = part
            if i:
                p.update(id=f"{n['id']}~{i + 1}", summary_markdown="", summary_text="", _part_of=n["id"])
            first = _t(part[0]["start_time"])
            if i or first - _t(n["created_at"]) > RESUMED:
                p["_resumed"] = True
                p["_note_created_at"] = n["created_at"]
                p["created_at"] = _iso(first)
            pieces.append(p)

    def end(p):
        segs = p.get("transcript") or []
        return _t(segs[-1].get("end_time") or segs[-1]["start_time"]) if segs else None

    by_id = {p["id"]: p for p in pieces}
    joins = []
    for p in sorted((p for p in pieces if p.get("_resumed")), key=lambda p: p["created_at"]):
        start = _t(p["transcript"][0]["start_time"])
        hosts = [h for h in by_id.values() if h["id"] != p["id"] and h.get("transcript") and timedelta(0) <= start - end(h) <= JOIN]
        if not hosts:
            continue
        h = max(hosts, key=end)
        h["transcript"] = list(h["transcript"]) + list(p["transcript"])
        extra = (p.get("summary_markdown") or p.get("summary_text") or "").strip()
        note = f"_Recording resumed {start.strftime('%H:%M')} UTC in another Granola note: {p.get('web_url') or p['id']}_"
        h["summary_markdown"] = "\n\n".join(x for x in [(h.get("summary_markdown") or h.get("summary_text") or "").strip(),
                                                        "# Continued recording", note, extra] if x)
        h["_continued_by"] = h.get("_continued_by", []) + [p.get("_part_of") or p["id"]]
        joins.append((p["id"], h["id"]))
        del by_id[p["id"]]
    return list(by_id.values()), joins
