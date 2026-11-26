#!/usr/bin/env python3
"""Update the Granola Export folder from the Granola public API.

Usage:  python3 granola_update.py   (key from GRANOLA_API_KEY, else the macOS Keychain: service granola-api, the account in
        SleePO's settings, keychain_account)

SleePO's copy (DESIGN-PERSONALISATION.md phase 6): run with the Granola Export folder as the working directory; the
Keychain account and the time zone come from SleePO (assist.db.keychain_account, the profile's time zone).

Fetches the note list, downloads any note that is new or whose updated_at
changed, rewrites its raw JSON + transcript markdown, and regenerates README.md.
Existing local notes that no longer exist remotely are kept (reported only).
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from assist import profile as _profile
    LOCAL_TZ = ZoneInfo(_profile.get()["timezone"])
except Exception:
    LOCAL_TZ = None

BASE = "https://public-api.granola.ai/v1"
ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw-json"
TRANSCRIPTS = ROOT / "transcripts"
# Speaker fixes (26 Oct 2026): a call recorded on Sam's microphone alone (a phone or WhatsApp call on speaker) comes from
# Granola with every line as Sam. speaker-fixes/<note id>.json says where each turn starts and who speaks it, as the first
# words of the turn inside a segment (no transcript text of its own); render_markdown applies it every time the note is
# written, so a later Granola update keeps the split. Granola itself still shows the note as recorded.
FIXES = ROOT / "speaker-fixes"

def _account():
    """SleePO's Keychain account (assist.db.keychain_account)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from assist import db as _db
    return _db.keychain_account()


def _api_key():
    """The Granola API key: GRANOLA_API_KEY if set, otherwise the macOS Keychain (service granola-api, SleePO's account)."""
    if os.environ.get("GRANOLA_API_KEY"):
        return os.environ["GRANOLA_API_KEY"]
    import subprocess
    r = subprocess.run(["security", "find-generic-password", "-s", "granola-api", "-a", _account(), "-w"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit("No Granola API key: add it with  security add-generic-password -s granola-api -a <your Keychain account> -w")
    return r.stdout.strip()


API_KEY = _api_key()


def api_get(path, **params):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def list_all_notes():
    notes, cursor = [], None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        data = api_get("/notes", **params)
        notes.extend(data.get("notes", []))
        if not data.get("hasMore"):
            return notes
        cursor = data.get("cursor")


def parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def to_local(ts):
    dt = parse_iso(ts)
    return dt.astimezone(LOCAL_TZ) if LOCAL_TZ else dt.astimezone()


def sanitize_title(title):
    title = title or "Untitled"
    kept = "".join(c for c in title if c.isalnum() or c in " &-_.")
    return re.sub(r"\s+", " ", kept).strip() or "Untitled"


def md_filename(note):
    date = to_local(note["created_at"]).strftime("%Y-%m-%d")
    return f"{date} - {sanitize_title(note.get('title'))} [{note['id'][-6:]}].md"


def _fixed_segments(note):
    """The note's segments with a speaker fix applied: (segments, fix) or (segments, None). Each segment is split where a
    turn starts; a piece keeps the segment's speaker source, takes the turn's speaker and a start time placed by its
    position in the segment's text. A turn whose words are not found where expected is skipped (its speaker carries on)."""
    segments = note.get("transcript") or []
    path = FIXES / f"{note['id']}.json"
    if not path.exists():
        return segments, None
    fix = json.loads(path.read_text())
    names = fix.get("names") or {}
    turns = {}
    for t in fix.get("turns") or []:
        turns.setdefault(t["seg"], []).append(t)
    out, who = [], "me"
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        cuts, pos = [], 0
        for t in turns.get(i, []):
            at = text.find(t["at"], pos)
            if at < 0:
                print(f"  speaker fix {note['id']}: segment {i}: \"{t['at'][:40]}\" not found; skipped")
                continue
            cuts.append((at, t["who"]))
            pos = at + 1
        if not cuts or cuts[0][0] > 0:
            cuts.insert(0, (0, who))
        try:
            t0, t1 = parse_iso(seg["start_time"]), parse_iso(seg.get("end_time") or seg["start_time"])
        except (KeyError, ValueError):
            t0 = t1 = None
        for k, (at, w) in enumerate(cuts):
            end = cuts[k + 1][0] if k + 1 < len(cuts) else len(text)
            piece = text[at:end].strip()
            who = w
            if not piece:
                continue
            start = seg.get("start_time")
            if t0 and t1 and text:
                start = (t0 + (t1 - t0) * (at / len(text))).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            name = names.get("other") if w == "other" else None
            out.append({**seg, "text": piece, "start_time": start,
                        "speaker": {"source": (seg.get("speaker") or {}).get("source"), "attribution": "me" if w == "me" else "other", "name": name}})
    return out, fix


def render_markdown(note):
    title = note.get("title") or "Untitled"
    owner = (note.get("owner") or {}).get("name") or "Unknown"
    attendees = [a.get("name") or a.get("email") or "Unknown"
                 for a in (note.get("attendees") or [])]
    event = note.get("calendar_event") or {}
    lines = ["---",
             f'title: "{title.replace(chr(34), chr(92) + chr(34))}"',
             f"granola_id: {note['id']}",
             f"created: {note['created_at']}",
             f"updated: {note['updated_at']}"]
    if event.get("scheduled_start_time"):
        lines.append(f"meeting_start: {event['scheduled_start_time']}")
    if event.get("scheduled_end_time"):
        lines.append(f"meeting_end: {event['scheduled_end_time']}")
    lines += [f"granola_url: {note.get('web_url', '')}", "attendees:"]
    lines += [f'  - "{a}"' for a in attendees]
    lines += ["---", "", f"# {title}", ""]

    header = ""
    if event.get("scheduled_start_time"):
        when = parse_iso(event["scheduled_start_time"]).astimezone(timezone.utc)
        header += f"**When:** {when.strftime('%Y-%m-%d %H:%M')} UTC  ·  "
    header += f"**Owner:** {owner}"
    if event.get("organiser"):
        header += f"  ·  **Organiser:** {event['organiser']}"
    lines += [header, ""]
    lines.append(f"**Attendees ({len(attendees)}):** {', '.join(attendees)}")
    lines.append("")

    summary = (note.get("summary_markdown") or note.get("summary_text") or "").strip()
    if summary:
        lines += ["## AI Summary", "", summary, ""]

    raw_segments = note.get("transcript") or []
    segments, fix = _fixed_segments(note)
    if segments:
        lines.append(f"## Transcript ({len(raw_segments)} segments)")
        lines.append("")
        if fix:
            lines.append(f"_Speakers split from one microphone by {fix.get('by') or 'SleePO'} ({fix.get('made', '')}; speaker-fixes/{note['id']}.json); "
                         "Granola itself shows every line as the owner._")
            lines.append("")
        block_texts, block_speaker, block_start = [], None, None

        def flush():
            if not block_texts:
                return
            # Granola names speakers from the call's display names (Teams, Zoom, Meet); without one the system-audio
            # channel is just "Other participant"
            speaker = block_speaker[1] or (owner if block_speaker[0] == "me" else "Other participant")
            ts = to_local(block_start).strftime("%H:%M:%S")
            lines.append(f"**[{ts}] {speaker}:** {' '.join(block_texts)}")
            lines.append("")

        for seg in segments:
            who = seg.get("speaker") or {}
            attribution = (who.get("attribution"), (who.get("name") or "").replace(":", " ").strip() or None)
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            if attribution != block_speaker:
                flush()
                block_texts, block_speaker, block_start = [], attribution, seg.get("start_time")
            block_texts.append(text)
        flush()

    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")
    return "\n".join(lines) + "\n"


def render_readme(notes):
    now = datetime.now(LOCAL_TZ) if LOCAL_TZ else datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d %H:%M %Z")
    lines = ["# Granola Export", "",
             f"Exported {stamp}  ·  **{len(notes)} notes**", "",
             "| Date | Note | Segments | People |", "|---|---|---|---|"]
    for note in sorted(notes, key=lambda n: n["created_at"], reverse=True):
        date = to_local(note["created_at"]).strftime("%Y-%m-%d")
        link = "transcripts/" + urllib.parse.quote(md_filename(note))
        segs = len(note.get("transcript") or [])
        people = len(note.get("attendees") or [])
        title = note.get("title") or "Untitled"
        lines.append(f"| {date} | [{title}]({link}) | {segs} | {people} |")
    return "\n".join(lines) + "\n"


def rerender(only=None):
    """Rewrite every transcript file from the saved raw notes (no API calls), e.g. after a format change; only: one note id."""
    n = 0
    for path in RAW.glob(f"{only}.json" if only else "not_*.json"):
        note = json.loads(path.read_text())
        for old in TRANSCRIPTS.glob(f"*[[]{note['id'][-6:]}[]].md"):
            old.unlink()
        (TRANSCRIPTS / md_filename(note)).write_text(render_markdown(note))
        n += 1
    print(f"Re-rendered {n} transcripts from raw-json/.")


def main():
    if "--rerender" in sys.argv:   # --rerender [note id]
        i = sys.argv.index("--rerender")
        return rerender(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
    RAW.mkdir(exist_ok=True)
    TRANSCRIPTS.mkdir(exist_ok=True)

    remote = list_all_notes()
    print(f"API reports {len(remote)} notes")

    local = {}
    for path in RAW.glob("not_*.json"):
        note = json.loads(path.read_text())
        local[note["id"]] = note

    fetched, kept = [], 0
    for stub in remote:
        nid = stub["id"]
        cached = local.get(nid)
        if cached and cached.get("updated_at") == stub.get("updated_at"):
            kept += 1
            continue
        note = api_get(f"/notes/{nid}", include="transcript")
        (RAW / f"{nid}.json").write_text(json.dumps(note, indent=2, ensure_ascii=False) + "\n")
        # drop any stale markdown for this note (title/date may have changed)
        for old in TRANSCRIPTS.glob(f"*[[]{nid[-6:]}[]].md"):
            old.unlink()
        (TRANSCRIPTS / md_filename(note)).write_text(render_markdown(note))
        local[nid] = note
        fetched.append(f"{to_local(note['created_at']).strftime('%Y-%m-%d')}  {note.get('title') or 'Untitled'}")
        print(f"  updated: {fetched[-1]}")

    remote_ids = {n["id"] for n in remote}
    orphans = [n for nid, n in local.items() if nid not in remote_ids]
    for o in orphans:
        print(f"  local-only (kept): {o.get('title') or 'Untitled'} [{o['id']}]")

    (ROOT / "README.md").write_text(render_readme(list(local.values())))
    print(f"Done: {len(fetched)} new/updated, {kept} unchanged, "
          f"{len(orphans)} local-only. README regenerated with {len(local)} notes.")


if __name__ == "__main__":
    main()
