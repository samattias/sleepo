#!/usr/bin/env python3
"""Build a triage digest from the Granola export.

Reads  ../Granola Export/raw-json/*.json
Writes inbox/granola/<YYYY-MM-DD>.md   (one digest per run day; re-running overwrites)
       inbox/granola/latest.md         (copy of the newest digest)
       inbox/granola/.state.json       (ids already digested, so each meeting is digested once)

Usage:
  python3 scripts/collect_granola.py            # everything new since the last run (first run: last 7 days)
  python3 scripts/collect_granola.py --days 14  # everything from the last 14 days, regardless of state
  python3 scripts/collect_granola.py --all      # every note ever (big)
  python3 scripts/collect_granola.py --prune    # also delete inbox digests older than 30 days

Privacy: attendee e-mail addresses are dropped; only names and the AI summary are kept.
Transcripts are never copied into the digest. Compatible with Python 3.9 (macOS system python).
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover
    LOCAL_TZ = None

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from assist.db import ASSIST  # noqa: E402  (the user's data folder: ASSIST_HOME, ~/.assist/home, else this folder)
RAW = ASSIST.parent / "Granola Export" / "raw-json"
INBOX = ASSIST / "inbox" / "granola"
STATE = INBOX / ".state.json"
RETENTION_DAYS = 30
# Meetings whose title matches are personal and never digested.
def _personal():
    """The user's personal meetings (assist/profile.py), or nothing when the package cannot be loaded."""
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from assist import profile
        return profile.PERSONAL
    except Exception:
        return re.compile(r"(?!)")


PERSONAL = _personal()

# Headings in Granola's AI summary that tend to hold the things triage cares about.
SIGNAL = re.compile(
    r"(action|next step|to-?do|follow[- ]?up|decision|decided|open question|question|risk|"
    r"blocker|owner|deadline|due|commit|agreed|ask)", re.I)


def parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def local(dt):
    return dt.astimezone(LOCAL_TZ) if LOCAL_TZ else dt.astimezone()


def update_coverage(notes, state, now):
    """Keep the Granola row in inbox/coverage.json truthful after every run."""
    cov_path = ASSIST / "inbox" / "coverage.json"
    if not cov_path.exists():
        return
    try:
        cov = json.loads(cov_path.read_text())
    except Exception:
        return
    dates = sorted(parse_iso(n["created_at"]) for n in notes)
    first, last = (local(dates[0]).strftime("%-d %b"), local(dates[-1]).strftime("%Y-%m-%d")) if dates else ("", "")
    digested = len(set(state.get("digested", [])) & {n["id"] for n in notes})
    processed = ASSIST / "inbox" / "processed"
    analysed_ids = set()
    for f in list((ASSIST / "inbox" / "granola").glob("backfill-*.md")) + (list(processed.glob("*.md")) if processed.exists() else []):
        analysed_ids |= set(re.findall(r"`(not_[A-Za-z0-9]+)`", f.read_text(errors="replace")))
    analysed = len(analysed_ids & {n["id"] for n in notes})
    age = (now - dates[-1]).days if dates else 999
    health = "ok" if age <= 3 else "stale"
    for src in cov.get("sources", []):
        if src.get("key") == "granola":
            src.update({"source": f"Granola meetings ({first} – {local(dates[-1]).strftime('%-d %b') if dates else ''})",
                        "available": len(notes), "digested": digested, "analysed": analysed, "last_seen": last, "health": health,
                        "note": f"{len(notes)} notes in the export; {digested} digested; {analysed} analysed into commitments and decisions; "
                                f"{digested - analysed} digested but not yet triaged. Last pull {local(now).strftime('%Y-%m-%d %H:%M')}."})
    cov["gaps"] = [g for g in cov.get("gaps", []) if not g.startswith("Granola:")]
    if age > 3:
        cov["gaps"].insert(0, f"Granola: newest note is {last}; nothing newer has been pulled.")
    cov["updated"] = local(now).strftime("%Y-%m-%d %H:%M %Z")
    cov_path.write_text(json.dumps(cov, indent=2, ensure_ascii=False))


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"digested": [], "last_run": None}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2) + "\n")


def sections(summary_md):
    """Split a markdown summary into (heading, body_lines)."""
    out, head, body = [], None, []
    for line in summary_md.splitlines():
        if line.startswith("#"):
            if head is not None or body:
                out.append((head, body))
            head, body = line.lstrip("#").strip(), []
        else:
            body.append(line)
    if head is not None or body:
        out.append((head, body))
    return out


def candidates(summary_md):
    """Bullets under signal-bearing headings, or bullets that themselves carry a signal word."""
    found = []
    for head, body in sections(summary_md):
        head_hit = bool(head and SIGNAL.search(head))
        for line in body:
            s = line.strip()
            if not s.startswith(("-", "*", "•")):
                continue
            text = re.sub(r"^[-*•]\s*", "", s).replace("**", "").strip()
            if not text or len(text) < 4:
                continue
            if head_hit or SIGNAL.search(text):
                found.append((head or "", text))
    return found


def render_note(note):
    title = note.get("title") or "Untitled"
    created = local(parse_iso(note["created_at"]))
    names = [a.get("name") for a in (note.get("attendees") or []) if a.get("name")]
    names = [n for n in names if n != "Sam Doe"] or ["(no other attendees recorded)"]
    summary = (note.get("summary_markdown") or note.get("summary_text") or "").strip()
    private = (note.get("private_notes_markdown") or note.get("private_notes_text") or "").strip()
    segs = len(note.get("transcript") or [])
    url = note.get("web_url", "")
    nid = note["id"]

    lines = [f"## {created.strftime('%Y-%m-%d %a %H:%M')} · {title}", "",
             f"**With:** {', '.join(names)}  ·  **Transcript:** {segs} segments  ·  "
             f"[Granola]({url})  ·  `{nid}`", ""]
    cands = candidates(summary)
    if cands:
        lines += ["### Candidates for triage", ""]
        for head, text in cands[:25]:
            tag = f" _({head})_" if head else ""
            lines.append(f"- [ ] {text}{tag}")
        lines.append("")
    if private:
        lines += ["### Your private notes", "", private, ""]
    if summary:
        lines += ["### AI summary", "", summary, ""]
    else:
        lines += ["_No AI summary on this note; open the transcript if it matters._", ""]
    lines += ["---", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="window in days (ignores state)")
    ap.add_argument("--all", action="store_true", help="every note (ignores state)")
    ap.add_argument("--prune", action="store_true", help=f"delete digests older than {RETENTION_DAYS} days")
    ap.add_argument("--backfill", action="store_true", help="digest every note not yet digested, one file per month (inbox/granola/backfill-YYYY-MM.md)")
    args = ap.parse_args()

    INBOX.mkdir(parents=True, exist_ok=True)
    if not RAW.exists():
        sys.exit(f"Granola raw-json folder not found at {RAW}")

    state = load_state()
    notes = [json.loads(p.read_text()) for p in RAW.glob("*.json")]
    sys.path.insert(0, str(ASSIST))
    from assist.granola_stitch import stitch
    notes, _ = stitch(notes)   # a recording resumed in the wrong note joins the meeting it continues
    key = lambda n: "+".join([n["id"]] + n.get("_continued_by", []))   # a meeting that gained a continuation is digested again
    notes = [n for n in notes if not PERSONAL.search(n.get("title") or "")]
    now = datetime.now(timezone.utc)

    if args.backfill:
        done = set(state["digested"])
        todo = sorted([n for n in notes if key(n) not in done], key=lambda n: n["created_at"])
        by_month = {}
        for n in todo:
            by_month.setdefault(local(parse_iso(n["created_at"])).strftime("%Y-%m"), []).append(n)
        for month, group in sorted(by_month.items()):
            out = INBOX / f"backfill-{month}.md"
            head = [f"# Granola backfill · {month} · {len(group)} meeting(s)", "",
                    "Historical meetings never digested before. Process with `/triage` (or the backfill agent); move to inbox/processed/ when done.", "",
                    "| When | Meeting | With |", "|---|---|---|"]
            for n in group:
                names = [a.get("name") for a in (n.get("attendees") or []) if a.get("name") and a.get("name") != "Sam Doe"]
                head.append(f"| {local(parse_iso(n['created_at'])).strftime('%m-%d %a')} | {n.get('title') or 'Untitled'} | {', '.join(names) or '—'} |")
            head += ["", "---", ""]
            out.write_text("\n".join(head) + "\n" + "".join(render_note(n) for n in group))
            print(f"Wrote {out.relative_to(ASSIST)} ({len(group)} meetings, {out.stat().st_size // 1024} KB)")
        state["digested"] = sorted(set(state["digested"]) | {key(n) for n in todo})
        state["last_run"] = now.isoformat()
        save_state(state)
        update_coverage(notes, state, now)
        return

    if args.all:
        picked = notes
    elif args.days:
        since = now - timedelta(days=args.days)
        picked = [n for n in notes if parse_iso(n["created_at"]) >= since]
    else:
        done = set(state["digested"])
        if state["last_run"]:
            picked = [n for n in notes if key(n) not in done]
        else:
            since = now - timedelta(days=7)
            picked = [n for n in notes if parse_iso(n["created_at"]) >= since]

    picked.sort(key=lambda n: n["created_at"])
    today = local(now).strftime("%Y-%m-%d")
    out = INBOX / f"{today}.md"

    if not picked:
        print("Nothing new to digest.")
    else:
        first = local(parse_iso(picked[0]["created_at"])).strftime("%Y-%m-%d")
        last = local(parse_iso(picked[-1]["created_at"])).strftime("%Y-%m-%d")
        head = [f"# Granola digest · generated {local(now).strftime('%Y-%m-%d %H:%M')}", "",
                f"{len(picked)} meeting(s), {first} → {last}. Run `/triage` in this folder to process.", "",
                "| When | Meeting | With |", "|---|---|---|"]
        for n in picked:
            names = [a.get("name") for a in (n.get("attendees") or []) if a.get("name") and a.get("name") != "Sam Doe"]
            head.append(f"| {local(parse_iso(n['created_at'])).strftime('%m-%d %a')} | {n.get('title') or 'Untitled'} | {', '.join(names) or '—'} |")
        head += ["", "---", ""]
        out.write_text("\n".join(head) + "\n" + "".join(render_note(n) for n in picked))
        shutil.copy(out, INBOX / "latest.md")
        print(f"Wrote {out.relative_to(ASSIST)} with {len(picked)} meeting(s) ({first} → {last}).")

    if not (args.all or args.days):
        state["digested"] = sorted(set(state["digested"]) | {key(n) for n in picked})
    else:
        state["digested"] = sorted(set(state["digested"]) | {key(n) for n in picked})
    state["last_run"] = now.isoformat()
    save_state(state)
    update_coverage(notes, state, now)

    if args.prune:
        cutoff = now - timedelta(days=RETENTION_DAYS)
        for p in list(INBOX.glob("*.md")) + list((ASSIST / "inbox" / "processed").glob("*.md")):
            if p.name == "latest.md":
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
            if m and datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc) < cutoff:
                p.unlink()
                print(f"pruned {p.name}")


if __name__ == "__main__":
    main()
