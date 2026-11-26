#!/usr/bin/env python3
"""Build Assist.html — the assistant app over the plain files in this folder.

Seven views (Today · Sources · Commitments · Decisions · Meetings · People · Initiatives)
plus a Library of every markdown document, one search, and browser-side state
(ticks and "seen" marks) that is listed under "Changes to apply" for Claude to write back.

Usage: python3 scripts/build_ui.py     (sync.sh and every skill call this)
Python 3.9 compatible. The markdown renderer (marked) loads from cdnjs; offline it falls back to plain text.
"""
import hashlib
import json
import sys
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from assist.db import ASSIST  # noqa: E402  (the user's data folder: ASSIST_HOME, ~/.assist/home, else this folder)
GRANOLA = ASSIST.parent / "Granola Export"
OUT = ASSIST / "Assist.html"
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover
    TZ = None

FM = re.compile(r"^---\n(.*?)\n---\n", re.S)
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
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
def _legacy_tags():
    """(name, pattern) pairs the legacy parsers tag records with: legacy_tags in the user's memory/context/initiatives.json."""
    try:
        return [tuple(x) for x in json.loads((ASSIST / "memory" / "context" / "initiatives.json").read_text()).get("legacy_tags") or []]
    except (OSError, ValueError):
        return []


INITIATIVES = _legacy_tags()


def now():
    return datetime.now(TZ) if TZ else datetime.now()


def hid(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]


def read(path):
    text = path.read_text(errors="replace")
    meta = {}
    m = FM.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        text = text[m.end():]
    return text, meta


def title_of(path, text, meta):
    if meta.get("title"):
        return meta["title"]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def doc(path, section, label=None, did=None):
    text, meta = read(path)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, TZ) if TZ else datetime.fromtimestamp(path.stat().st_mtime)
    return {"id": did or str(path.relative_to(ASSIST)), "section": section, "title": label or title_of(path, text, meta),
            "path": str(path.relative_to(ASSIST)), "mtime": mtime.strftime("%Y-%m-%d %H:%M"), "meta": meta,
            "md": text, "words": len(text.split())}


def md_files(folder, exclude=("README.md", "latest.md")):
    if not folder.exists():
        return []
    return sorted([p for p in folder.glob("*.md") if p.name not in exclude], reverse=True)


def clean(text):
    """Markdown links -> their label; bare URLs removed; whitespace collapsed."""
    text = LINK.sub(lambda m: m.group(1), text)
    text = re.sub(r"\(?https?://\S+\)?", "", text)
    return re.sub(r"\s+", " ", text).strip(" ·-–")


def tag_initiatives(text):
    return [name for name, rx in INITIATIVES if re.search(rx, text)]


# ---------------------------------------------------------------- tasks
def parse_tasks(md):
    items, section = [], None
    for line in md.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = re.match(r"- \[( |x)\] (.*)", line)
        if not m or not section:
            continue
        done, body = m.group(1) == "x", m.group(2).strip()
        t = re.search(r"\*\*(.+?)\*\*", body)
        title = t.group(1) if t else re.sub(r"~~", "", body).split(" - ")[0][:140]
        rest = body.replace(t.group(0), "", 1) if t else body
        links = [{"label": a, "url": b} for a, b in LINK.findall(rest)]
        rest = LINK.sub("", rest)
        rest = re.sub(r"^\s*[-–·]\s*", "", rest).strip(" ·-–")
        rest = re.sub(r"\s*·\s*$", "", rest).strip()
        low = section.lower()
        if low.startswith("waiting"):
            group = "waiting"
        elif low.startswith("someday"):
            group = "someday"
        elif low.startswith("done") or done:
            group = "done"
        else:
            group = "active"
        if "carried over" in low:
            origin = "Meetings Jul–Sep"
        elif "unanswered asks" in low:
            origin = "Mail & Teams Jul–Sep"
        else:
            origin = "Current"
        person = None
        if group == "waiting":
            pm = re.match(r"([A-Z][A-Za-z.\-' ]{1,40}?)\s*:\s", title)
            if pm:
                person = pm.group(1).strip()
        else:
            pm = re.match(r"([A-Z][A-Za-z\-' ]{2,30}):\s", title)
            if pm and len(pm.group(1).split()) <= 3:
                person = pm.group(1).strip()
        items.append({"id": "t-" + hid(title), "title": title, "context": rest, "links": links, "group": group,
                      "origin": origin, "person": person, "done": done,
                      "initiatives": tag_initiatives(title + " " + rest)})
    return items


# ------------------------------------------------------------- decisions
def parse_decisions(md):
    rows = []
    for line in md.splitlines():
        if not line.startswith("| 20"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        date, dec, owner, status, src = cells[:5]
        st = "pending" if "pending" in status.lower() else ("reversed" if "reversed" in status.lower() else "taken")
        links = [{"label": a, "url": b} for a, b in LINK.findall(src)]
        plain = LINK.sub("", src).strip(" ·")
        rows.append({"id": "d-" + hid(date + dec), "date": date, "decision": dec, "owner": owner, "status": st,
                     "status_note": status, "links": links, "source_text": plain, "initiatives": tag_initiatives(dec)})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


# -------------------------------------------------------------- meetings
def load_digest_sections():
    """Map granola note id -> markdown body (candidates + summary) from every digest file."""
    out = {}
    folder = ASSIST / "inbox" / "granola"
    files = [p for p in folder.glob("*.md") if p.name != "latest.md"] if folder.exists() else []
    proc = ASSIST / "inbox" / "processed"
    files += list(proc.glob("*.md")) if proc.exists() else []
    for p in files:
        analysed = p.name.startswith("backfill-") or p.parent.name == "processed"
        text = p.read_text(errors="replace")
        for chunk in re.split(r"\n(?=## \d{4}-\d{2}-\d{2} )", text):
            m = re.search(r"`(not_[A-Za-z0-9]+)`", chunk)
            if not m:
                continue
            body = chunk.split("\n", 1)[1] if "\n" in chunk else ""
            body = re.sub(r"^\*\*With:\*\*.*\n", "", body, count=1)
            body = body.replace("\n---\n", "\n").strip()
            out[m.group(1)] = (body, analysed)
    return out


def load_calendar():
    """events.json (pull) + reconciled.json (matcher) -> (events list, matched map)."""
    ev_path = ASSIST / "inbox" / "calendar" / "events.json"
    rc_path = ASSIST / "inbox" / "calendar" / "reconciled.json"
    events, pulled = [], ""
    if ev_path.exists():
        try:
            j = json.loads(ev_path.read_text())
            events, pulled = j.get("events", []), j.get("pulled", "")
        except Exception:
            pass
    rec = {"matched": {}, "unrecorded_events": [], "stats": {}}
    if rc_path.exists():
        try:
            rec = json.loads(rc_path.read_text())
        except Exception:
            pass
    def name_of(email):
        local = (email or "").split("@")[0]
        parts = [x for x in re.split(r"[._\-]+", local) if x]
        return " ".join(x.capitalize() if x.islower() else x for x in parts) if parts else (email or "")
    out = []
    unrec = set(rec.get("unrecorded_events", []))
    recorded = {v["event_id"] for v in rec.get("matched", {}).values()}
    for e in events:
        try:
            st = datetime.fromisoformat(e["start"].split(".")[0]).replace(tzinfo=__import__("datetime").timezone.utc)
            en = datetime.fromisoformat(e["end"].split(".")[0]).replace(tzinfo=__import__("datetime").timezone.utc)
        except Exception:
            continue
        if TZ:
            st, en = st.astimezone(TZ), en.astimezone(TZ)
        att = [name_of(a) for a in (e.get("attendees") or []) if a and "sam.doe" not in a.lower()]
        out.append({"id": e["id"], "subject": e.get("subject") or "(no subject)", "date": st.strftime("%Y-%m-%d"),
                    "day": st.strftime("%a %d %b"), "time": st.strftime("%H:%M") + "–" + en.strftime("%H:%M"),
                    "minutes": int((en - st).total_seconds() // 60), "organizer": name_of(e.get("organizer")),
                    "attendees": att, "cancelled": bool(e.get("isCancelled")), "mine": bool(e.get("isOrganizer")),
                    "webLink": e.get("webLink", ""), "location": e.get("location") or "",
                    "recorded": e["id"] in recorded, "unrecorded": e["id"] in unrec, "showAs": e.get("showAs", "")})
    out.sort(key=lambda x: (x["date"], x["time"]))
    return out, rec.get("matched", {}), rec.get("stats", {}), pulled


def meetings():
    cal_events, cal_matched, _, _ = load_calendar()
    raw = GRANOLA / "raw-json"
    tdir = GRANOLA / "transcripts"
    if not raw.exists():
        return [], []
    by_short = {}
    for t in tdir.glob("*.md") if tdir.exists() else []:
        m = re.search(r"\[([A-Za-z0-9]{6})\]\.md$", t.name)
        if m:
            by_short[m.group(1)] = t
    state_path = ASSIST / "inbox" / "granola" / ".state.json"
    digested = set(json.loads(state_path.read_text()).get("digested", [])) if state_path.exists() else set()
    bodies = load_digest_sections()
    items, docs = [], []
    for p in raw.glob("*.json"):
        try:
            n = json.loads(p.read_text())
        except Exception:
            continue
        nid = n["id"]
        created = n.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            dt = dt.astimezone(TZ) if TZ else dt
            when, date = dt.strftime("%a %d %b %Y, %H:%M"), dt.strftime("%Y-%m-%d")
        except Exception:
            when, date = created, created[:10]
        title = (n.get("title") or "Untitled").replace("|", "/")
        names = [a.get("name") for a in (n.get("attendees") or []) if a.get("name") and a.get("name") != "Sam Doe"]
        cal = cal_matched.get(nid)
        cal_subject = cal["subject"] if cal else ""
        if cal and not names:
            names = cal.get("attendees", [])
        t = by_short.get(nid[-6:])
        local = "../Granola%20Export/transcripts/" + urllib.parse.quote(t.name) if t else ""
        personal = bool(PERSONAL.search(title))
        summary_md, analysed = bodies.get(nid, ("", False))
        status = "personal" if personal else ("analysed" if analysed else ("digested" if (nid in digested or summary_md) else "pending"))
        segs = len(n.get("transcript") or [])
        md = f"# {title}\n\n**{when}**  ·  with {', '.join(names) or 'no other attendees recorded'}  ·  {segs} transcript segments  ·  "
        if cal:
            md += f"\n\n**Calendar:** {cal_subject} · organiser {cal.get('organizer','')}" + (f" · [open in Outlook]({cal['webLink']})" if cal.get('webLink') else "") + "\n\n"
        md += f"[Granola]({n.get('web_url', '')})" + (f"  ·  [transcript]({local})" if local else "") + "\n\n"
        if personal:
            md += "_Personal meeting; not analysed by design._\n"
        elif summary_md:
            md += summary_md + "\n"
        else:
            md += "_No digest yet. Press Refresh (or run the collector) to digest this meeting._\n"
        if status == "digested":
            md = md.replace("\n\n", "\n\n_Digested, not yet triaged into commitments and decisions. Run /triage._\n\n", 1)
        mid = "m-" + nid[-6:]
        items.append({"id": mid, "date": date, "when": when, "title": title, "with": names, "segments": segs,
                      "status": status, "granola": n.get("web_url", ""), "transcript": local,
                      "calendar": cal_subject, "organizer": (cal or {}).get("organizer", ""), "outlook": (cal or {}).get("webLink", ""),
                      "initiatives": [] if personal else tag_initiatives(title + " " + summary_md[:4000])})
        docs.append({"id": mid, "section": "Meetings", "title": title, "path": "Granola Export/transcripts", "mtime": date,
                     "meta": {}, "md": md, "words": len(md.split())})
    items.sort(key=lambda m: m["date"], reverse=True)
    return items, docs


# ------------------------------------------------------- people / projects
def people():
    out, docs = [], []
    for p in md_files(ASSIST / "memory" / "people"):
        text, meta = read(p)
        name = title_of(p, text, meta)
        sec = re.split(r"\n(?=## )", text)
        threads, recent, owns = [], [], ""
        for s in sec:
            head = s.split("\n", 1)[0].lower()
            body = s.split("\n", 1)[1] if "\n" in s else ""
            if "open threads" in head:
                threads = [l.strip() for l in body.splitlines() if l.strip().startswith("- ")]
            elif "recent interactions" in head:
                recent = [clean(l.strip()[2:]) for l in body.splitlines() if l.strip().startswith("- ")]
            elif head.startswith("## owns"):
                owns = clean(" ".join(l.strip("- ").strip() for l in body.splitlines() if l.strip()))[:220]
        pid = "p-" + hid(name)
        out.append({"id": pid, "name": name, "role": meta.get("role", ""), "relationship": meta.get("relationship", ""),
                    "updated": meta.get("updated", ""), "threads": len(threads), "last": (recent[0] if recent else "")[:160],
                    "owns": owns})
        docs.append({"id": pid, "section": "People", "title": name, "path": str(p.relative_to(ASSIST)),
                     "mtime": meta.get("updated", ""), "meta": meta, "md": text, "words": len(text.split())})
    out.sort(key=lambda x: (-x["threads"], x["name"]))
    return out, docs


def projects():
    out, docs = [], []
    for p in md_files(ASSIST / "memory" / "projects"):
        text, meta = read(p)
        name = title_of(p, text, meta)
        sec = re.split(r"\n(?=## )", text)
        stands, pending, risks = "", 0, 0
        for s in sec:
            head = s.split("\n", 1)[0].lower()
            body = s.split("\n", 1)[1] if "\n" in s else ""
            if "where it stands" in head:
                stands = clean(" ".join(l.strip("- ").strip() for l in body.splitlines() if l.strip()))[:420]
            elif "decisions pending" in head:
                pending = len([l for l in body.splitlines() if l.strip().startswith("- ")])
            elif head.startswith("## risks"):
                risks = len([l for l in body.splitlines() if l.strip().startswith("- ")])
        pid = "i-" + hid(name)
        out.append({"id": pid, "name": name, "status": meta.get("status", ""), "owner": meta.get("owner", ""),
                    "milestone": meta.get("next_milestone", ""), "updated": meta.get("updated", ""),
                    "stands": stands, "pending": pending, "risks": risks})
        docs.append({"id": pid, "section": "Initiatives", "title": name, "path": str(p.relative_to(ASSIST)),
                     "mtime": meta.get("updated", ""), "meta": meta, "md": text, "words": len(text.split())})
    return out, docs


# -------------------------------------------------------------- snapshots
STREAM_RULES = [
    (r"sam sent|sent items|sent \(", "outlook.sent"),
    (r"mail|inbox|outlook", "outlook.inbox"),
    (r"teams", "teams"),
    (r"slack", "slack"),
    (r"calendar", "calendar.snap"),
]


def parse_tables(md):
    """Yield (heading, headers, rows) for every markdown table under a heading."""
    heading, h2 = "", ""
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            txt = line.lstrip("#").strip()
            if level <= 2:
                h2, heading = txt, txt
            else:
                heading = f"{h2} › {txt}" if h2 else txt
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*-", lines[i + 1]):
            headers = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if any(cells):
                    rows.append(cells)
                i += 1
            yield heading, headers, rows
            continue
        i += 1


def snapshots():
    """Every table in inbox/live/*.md, classified into streams: {stream: [{file, title, mtime, heading, headers, rows}]}."""
    out = {}
    folder = ASSIST / "inbox" / "live"
    for path in md_files(folder):
        text, meta = read(path)
        mtime = datetime.fromtimestamp(path.stat().st_mtime, TZ) if TZ else datetime.fromtimestamp(path.stat().st_mtime)
        title = title_of(path, text, meta)
        for heading, headers, rows in parse_tables(text):
            h = heading.lower()
            if h.startswith(("count", "noise", "finding", "known gaps")) or not rows:
                continue
            stream = next((st for rx, st in STREAM_RULES if re.search(rx, h)), None)
            if stream is None:
                if "slack" in title.lower():
                    stream = "slack"
                else:
                    continue
            # split markdown links out of each cell: keep text, collect urls
            clean_rows = []
            for r in rows:
                cells, links = [], []
                for c in r:
                    found = LINK.findall(c)
                    for lab, url in found:
                        links.append({"label": lab if lab.lower() not in ("link", "src", "mail", "chat") else "open", "url": url})
                    txt = LINK.sub("", c).replace("**", "").strip(" ·")
                    cells.append(txt)
                clean_rows.append({"c": cells, "l": links})
            width = max([len(r["c"]) for r in clean_rows] + [len(headers)])
            headers = headers + [""] * (width - len(headers))
            out.setdefault(stream, []).append({"_m": mtime.isoformat(), "file": str(path.relative_to(ASSIST)), "doc": str(path.relative_to(ASSIST)), "title": title,
                                               "mtime": mtime.strftime("%Y-%m-%d %H:%M"), "heading": heading, "headers": headers, "rows": clean_rows})
    for k in out:
        out[k].sort(key=lambda t: t["_m"], reverse=True)
        for t in out[k]:
            t.pop("_m", None)
    return out


# ------------------------------------------------------------------ brief
def parse_brief(path):
    text, meta = read(path)
    title = title_of(path, text, meta)
    today = ""
    m = re.search(r"^\*\*Today:\*\*\s*(.+)$", text, re.M)
    if m:
        today = m.group(1).strip()
    sources_line = ""
    m = re.search(r"^_Sources:(.+?)_\s*$", text, re.M)
    if m:
        sources_line = m.group(1).strip()
    sections = {}
    for chunk in re.split(r"\n(?=## )", text):
        if chunk.startswith("## "):
            head, body = chunk.split("\n", 1) if "\n" in chunk else (chunk, "")
            sections[head[3:].strip()] = body.strip()
    return {"title": title, "today": today, "sources_line": sources_line, "sections": sections, "path": str(path.relative_to(ASSIST))}


# ------------------------------------------------------------------ main
def main():
    tasks_md = (ASSIST / "TASKS.md").read_text() if (ASSIST / "TASKS.md").exists() else ""
    tasks = parse_tasks(tasks_md)
    dec_md = (ASSIST / "memory" / "decisions.md").read_text() if (ASSIST / "memory" / "decisions.md").exists() else ""
    decisions = parse_decisions(dec_md)
    mtg, mdocs = meetings()
    ppl, pdocs = people()
    prj, idocs = projects()

    briefs = [p for p in md_files(ASSIST / "briefs") if not p.name.endswith("-review.md")]
    brief = parse_brief(briefs[0]) if briefs else None

    docs = []
    for p in briefs:
        docs.append(doc(p, "Briefs"))
    for p in [p for p in md_files(ASSIST / "briefs") if p.name.endswith("-review.md")]:
        docs.append(doc(p, "Weekly reviews"))
    docs.append(doc(ASSIST / "TASKS.md", "Commitments", "Task list (TASKS.md)"))
    docs.append(doc(ASSIST / "memory" / "decisions.md", "Decisions", "Decision log (decisions.md)"))
    bf = ASSIST / "inbox" / "backfill"
    for p in (sorted(bf.glob("*.md"), reverse=True) if bf.exists() else []):
        docs.append(doc(p, "Analyses"))
    for p in md_files(ASSIST / "inbox" / "live"):
        docs.append(doc(p, "Pulls"))
    for p in md_files(ASSIST / "inbox" / "granola"):
        docs.append(doc(p, "Digests"))
    for p in md_files(ASSIST / "inbox" / "processed"):
        docs.append(doc(p, "Digests"))
    for p in md_files(ASSIST / "drafts"):
        docs.append(doc(p, "Drafts"))
    docs.append(doc(ASSIST / "CLAUDE.md", "Memory", "Working memory (CLAUDE.md)"))
    for name, label in [("glossary.md", "Glossary"), ("context/strategy.md", "Strategy frame"),
                        ("context/preferences.md", "Writing preferences"), ("context/v2mom-2026-final.md", "V2MOM 2026 (final)")]:
        p = ASSIST / "memory" / name
        if p.exists():
            docs.append(doc(p, "Memory", label))
    for name, label in [("DESIGN.md", "System design"), ("DESIGN-UI.md", "UI review and redesign"), ("DESIGN-SYSTEM.md", "From prototype to system"), ("README.md", "How to use")]:
        if (ASSIST / name).exists():
            docs.append(doc(ASSIST / name, "System", label))
    docs += pdocs + idocs + mdocs

    cov_path = ASSIST / "inbox" / "coverage.json"
    coverage = json.loads(cov_path.read_text()) if cov_path.exists() else {"sources": [], "gaps": []}
    pulls = [{"id": d["id"], "title": d["title"], "mtime": d["mtime"], "words": d["words"]} for d in docs if d["section"] in ("Pulls", "Digests", "Analyses")]

    state_path = ASSIST / "inbox" / "granola" / ".state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    log_path = ASSIST / "inbox" / "sync.log"
    log_tail = "\n".join(log_path.read_text().splitlines()[-20:]) if log_path.exists() else "(no sync yet)"

    cal_events, cal_matched, cal_stats, cal_pulled = load_calendar()
    logos = {}
    for f in sorted((ASSIST / "assets" / "logos").glob("*")) if (ASSIST / "assets" / "logos").exists() else []:
        if f.suffix.lower() in (".svg", ".png") and f.stat().st_size > 200:
            import base64
            mime = "image/svg+xml" if f.suffix.lower() == ".svg" else "image/png"
            logos.setdefault(f.stem, "data:%s;base64,%s" % (mime, base64.b64encode(f.read_bytes()).decode()))
    src_path = ASSIST / "inbox" / "sources.json"
    sources = json.loads(src_path.read_text()).get("systems", []) if src_path.exists() else []
    data = {
        "logos": logos,
        "sources": sources,
        "streams": snapshots(),
        "calendar": {"events": cal_events, "stats": cal_stats, "pulled": cal_pulled},
        "built": now().strftime("%a %d %b %Y, %H:%M %Z"),
        "built_iso": now().strftime("%Y-%m-%d"),
        "brief": brief,
        "tasks": tasks,
        "decisions": decisions,
        "meetings": mtg,
        "people": ppl,
        "projects": prj,
        "coverage": coverage,
        "pulls": pulls,
        "sync": {"digested": len(state.get("digested", [])), "last_run": state.get("last_run"), "log": log_tail},
        "docs": docs,
        "initiatives": [n for n, _ in INITIATIVES],
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    OUT.write_text(html)
    print(f"Wrote {OUT.name}: {len(docs)} documents, {len(tasks)} tasks, {len(decisions)} decisions, {len(mtg)} meetings, "
          f"{len(ppl)} people, {len(prj)} initiatives, {OUT.stat().st_size // 1024} KB")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Assist</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<style>
:root{color-scheme:light;--bg:#f6f6f3;--panel:#ffffff;--panel2:#fbfbf9;--ink:#1f1e1b;--ink2:#5f5e58;--ink3:#9a998f;--line:#e4e3dd;--line2:#eeede8;
--accent:#2a78d6;--accent-bg:#e8f1fb;--good:#0ca30c;--warn:#fab219;--serious:#ec835a;--critical:#d03b3b;--hl:#fff3b0;
--mono:ui-monospace,SFMono-Regular,Menlo,monospace;--sans:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;--serif:Georgia,"Times New Roman",serif;--r:10px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#151517;--panel:#1d1d20;--panel2:#232327;--ink:#ebe9e2;--ink2:#a9a79e;--ink3:#6e6d66;--line:#2c2c31;--line2:#26262a;--accent:#3987e5;--accent-bg:#1c2a3d;--hl:#4a4320}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#151517;--panel:#1d1d20;--panel2:#232327;--ink:#ebe9e2;--ink2:#a9a79e;--ink3:#6e6d66;--line:#2c2c31;--line2:#26262a;--accent:#3987e5;--accent-bg:#1c2a3d;--hl:#4a4320}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans);min-height:100vh}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.app{display:grid;grid-template-columns:250px minmax(0,1fr);min-height:100vh}
aside{position:sticky;top:0;height:100vh;display:flex;flex-direction:column;background:var(--panel);border-right:1px solid var(--line);padding:14px 12px;gap:10px;overflow:auto}
.brand-row{display:flex;align-items:baseline;justify-content:space-between;padding:2px 8px}
.brand{font-weight:700;font-size:17px;letter-spacing:.2px}
.sidesearch input{width:100%;padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
nav#tabs{display:flex;flex-direction:column;gap:1px}
nav#tabs h5{margin:12px 8px 4px;font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--ink3);font-weight:600}
nav#tabs a{display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:8px;color:var(--ink2);font-size:14px}
nav#tabs a .g{width:18px;text-align:center;color:var(--ink3);font-size:14px}
nav#tabs a.on{background:var(--accent-bg);color:var(--ink);font-weight:600}nav#tabs a.on .g{color:var(--accent)}
nav#tabs a:hover{text-decoration:none;background:var(--panel2)}nav#tabs a.on:hover{background:var(--accent-bg)}
nav#tabs a small{margin-left:auto;color:var(--ink3);font-weight:400;font-size:12px}
.sidesources{margin-top:auto;border-top:1px solid var(--line);padding-top:10px}
.sidesources h5{margin:0 8px 6px;font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--ink3);font-weight:600}
.sidesources a{display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:6px;font-size:12.5px;color:var(--ink2)}
.sidesources a:hover{background:var(--panel2);text-decoration:none}.sidesources a span.n{flex:1;color:var(--ink)}.sidesources a .dot{width:7px;height:7px}.sidesources a.ok .dot{background:var(--good)}.sidesources a.stale .dot{background:var(--warn)}.sidesources a.broken .dot{background:var(--critical)}.sidesources a.capped .dot{background:var(--serious)}.sidesources a.planned .dot{background:var(--ink3)}
.sidefoot{display:flex;gap:8px;align-items:center;padding-top:8px;margin-top:auto}
.topbar{display:none;position:sticky;top:0;z-index:10;align-items:center;gap:10px;padding:8px 12px;background:var(--panel);border-bottom:1px solid var(--line)}
.btn{border:1px solid var(--line);background:var(--panel);color:var(--ink2);border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit;font-size:13px}
.btn:hover{border-color:var(--ink3);color:var(--ink)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:1240px;padding:22px 28px 90px;overflow-wrap:anywhere;min-width:0}
.strip{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.src{display:inline-flex;align-items:center;gap:7px;padding:5px 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel);font-size:12.5px;color:var(--ink2);cursor:pointer}
.src b{color:var(--ink);font-weight:600}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none}
.ok .dot{background:var(--good)}.stale .dot{background:var(--warn)}.broken .dot{background:var(--critical)}.capped .dot{background:var(--serious)}
.strip .label{color:var(--ink3);font-size:12.5px;margin-right:4px}
.ico{position:relative;display:inline-flex;align-items:center;justify-content:center;border-radius:8px;background:var(--c);color:#fff;flex:none;overflow:hidden}
.ico .mono{font-weight:700;font-size:.5em;letter-spacing:-.5px;line-height:1}
.ico img{position:absolute;inset:0;width:100%;height:100%;padding:12%;background:var(--panel);display:none;object-fit:contain}
.ico.has{background:var(--panel);border:1px solid var(--line)}.ico.has img{display:block}
.src .ico{font-size:16px;border-radius:4px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);font-size:12px;color:var(--ink2);white-space:nowrap}
.pill.ok .dot{background:var(--good)}.pill.stale .dot{background:var(--warn)}.pill.broken .dot{background:var(--critical)}.pill.capped .dot{background:var(--serious)}.pill.planned .dot{background:var(--ink3)}
.syshead{display:flex;gap:12px;align-items:center}.syshead .ico{font-size:36px}
.sysstats{display:flex;gap:18px;margin-top:12px}.sysstats div{display:flex;flex-direction:column}.sysstats b{font-size:18px;font-weight:650}.sysstats span{font-size:12px;color:var(--ink3)}
.src.planned .dot{background:var(--ink3)}
h1{font-size:24px;margin:4px 0 6px;font-weight:650;line-height:1.2}
h2.sec{font-size:12.5px;text-transform:uppercase;letter-spacing:.8px;color:var(--ink3);margin:22px 0 10px;font-weight:600}
h2.sec:first-child{margin-top:0}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:minmax(0,1.5fr) minmax(0,1fr)}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
.gcards{grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;min-width:0}
.card.click{cursor:pointer}.card.click:hover{border-color:var(--ink3)}
.card h3{margin:0 0 6px;font-size:15.5px;font-weight:650;line-height:1.3}
.card .sub{color:var(--ink2);font-size:13.5px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px}
.tile .v{font-size:30px;font-weight:650;line-height:1.1;letter-spacing:-.5px}
.tile .l{color:var(--ink2);font-size:13px;margin-top:4px}
.tile .n{color:var(--ink3);font-size:12px;margin-top:6px}
.hero{font-family:var(--serif);font-size:21px;line-height:1.4;color:var(--ink);margin:6px 0 16px;max-width:900px}
.md h1{font-size:22px;margin:.1em 0 .5em}.md h2{font-size:17px;margin:1.4em 0 .5em;padding-bottom:4px;border-bottom:1px solid var(--line)}.md h3{font-size:15px;margin:1.1em 0 .4em}
.md table{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0 14px;display:block;overflow:auto}.md th,.md td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}.md th{background:var(--panel2)}
.md code{font-family:var(--mono);font-size:12.5px;background:var(--panel2);padding:1px 5px;border-radius:4px}.md pre{background:var(--panel2);border:1px solid var(--line);padding:12px;border-radius:8px;overflow:auto;font-size:12.5px}
.md ul,.md ol{padding-left:22px}.md li{margin:4px 0}.md p{margin:.5em 0}.md hr{border:0;border-top:1px solid var(--line);margin:18px 0}
.md input[type=checkbox]{margin-right:6px;accent-color:var(--accent)}.md li:has(> input:checked){color:var(--ink3);text-decoration:line-through}
.md blockquote{border-left:3px solid var(--line);margin:0;padding:2px 14px;color:var(--ink2)}
.md em{color:var(--ink2)}
mark{background:var(--hl);color:inherit;padding:0 1px;border-radius:2px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px;align-items:center}
.chip{padding:4px 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel);font-size:12.5px;color:var(--ink2);cursor:pointer;user-select:none}
.chip.on{background:var(--accent-bg);color:var(--ink);border-color:transparent;font-weight:600}
.chip small{color:var(--ink3);margin-left:4px}
.item{display:grid;grid-template-columns:22px 1fr;gap:10px;padding:11px 0;border-bottom:1px solid var(--line2);align-items:start}
.item:last-child{border-bottom:0}
.item input{margin-top:3px;accent-color:var(--accent);width:16px;height:16px;cursor:pointer}
.item .t{font-weight:600;line-height:1.35}
.item.done .t{color:var(--ink3);text-decoration:line-through}
.item .c{color:var(--ink2);font-size:13.5px;margin-top:2px}
.item .m{display:flex;gap:8px;flex-wrap:wrap;margin-top:5px;font-size:12px;color:var(--ink3);align-items:center}
.tag{padding:1px 7px;border-radius:999px;background:var(--panel2);border:1px solid var(--line);font-size:11.5px;color:var(--ink2);white-space:nowrap}
.tag.pending{border-color:var(--serious);color:var(--ink)}.tag.taken{border-color:var(--good)}.tag.status{display:inline-flex;gap:5px;align-items:center}
.row{display:grid;grid-template-columns:92px 1fr auto;gap:12px;padding:10px 0;border-bottom:1px solid var(--line2);align-items:start;font-size:14px}
.row .d{color:var(--ink3);font-family:var(--mono);font-size:12px;padding-top:2px}
.row .who{color:var(--ink2);font-size:13px;margin-top:2px}
table.list{width:100%;border-collapse:collapse;font-size:13.5px}table.list th{text-align:left;color:var(--ink3);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px;padding:8px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
table.list td{padding:9px 8px;border-bottom:1px solid var(--line2);vertical-align:top}table.list tr.click{cursor:pointer}table.list tr.click:hover td{background:var(--panel2)}
.muted{color:var(--ink3)}.small{font-size:12.5px}
.meter{height:6px;background:var(--line2);border-radius:3px;overflow:hidden;margin-top:8px}.meter i{display:block;height:100%;background:var(--accent)}
.gap{padding:10px 12px;border-left:3px solid var(--serious);background:var(--panel);border-radius:0 8px 8px 0;margin:8px 0;font-size:13.5px}
.lib{display:grid;grid-template-columns:260px 1fr;gap:18px}
.lib nav{position:sticky;top:64px;max-height:calc(100vh - 80px);overflow:auto;padding-right:6px}
.lib nav h4{font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--ink3);margin:14px 0 4px}
.lib nav a{display:block;padding:4px 8px;border-radius:6px;color:var(--ink);font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lib nav a.on{background:var(--accent-bg)}.lib nav a:hover{background:var(--panel2);text-decoration:none}
.crumbs{color:var(--ink3);font-size:12px;font-family:var(--mono);margin-bottom:8px}
.results .r{padding:10px 0;border-bottom:1px solid var(--line2)}.results .r a{font-weight:600;color:var(--ink)}.results .r small{color:var(--ink3);font-family:var(--mono);margin-left:8px}.results .r p{margin:3px 0 0;color:var(--ink2);font-size:13.5px}
.rf{position:relative}.rf .menu{display:none;position:absolute;left:0;bottom:40px;width:300px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);box-shadow:0 10px 30px rgba(0,0,0,.15);padding:6px;z-index:30}
.rf.open .menu{display:block}.rf .menu button{display:block;width:100%;text-align:left;border:0;background:none;padding:9px 10px;border-radius:6px;cursor:pointer;color:var(--ink);font:inherit}.rf .menu button:hover{background:var(--panel2)}.rf .menu small{display:block;color:var(--ink3);font-size:12px}
.rf pre{margin:8px 0 0;max-height:220px;overflow:auto;font-size:11.5px;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;white-space:pre-wrap;color:var(--ink2)}
@keyframes spin{to{transform:rotate(360deg)}}.spin{display:inline-block;animation:spin 1s linear infinite}
.changes{position:fixed;right:18px;bottom:18px;z-index:20}
.changes .panel{display:none;position:absolute;right:0;bottom:44px;width:360px;max-height:50vh;overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px;box-shadow:0 10px 30px rgba(0,0,0,.15)}
.changes.open .panel{display:block}
.changes textarea{width:100%;height:150px;font:12px/1.4 var(--mono);background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:8px}
.empty{color:var(--ink3);padding:14px 0}
.kbd{font-family:var(--mono);font-size:11px;border:1px solid var(--line);border-radius:4px;padding:0 5px;color:var(--ink3)}
@media (max-width:900px){.app{grid-template-columns:1fr}aside{display:none;position:fixed;inset:0;z-index:30;height:100vh;width:min(300px,85vw);box-shadow:0 0 40px rgba(0,0,0,.3)}aside.open{display:flex}.topbar{display:flex}.g2,.g3,.g4{grid-template-columns:1fr 1fr}.lib{grid-template-columns:1fr}.lib nav{position:static;max-height:none}}
@media (max-width:600px){.g2,.g3,.g4{grid-template-columns:1fr}main{padding:14px 12px 90px}.row{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<aside id="side">
  <div class="brand-row"><span class="brand">Assist</span><span class="small muted" id="built"></span></div>
  <div class="sidesearch"><input id="q" type="search" placeholder="Search  /" autocomplete="off"></div>
  <nav id="tabs"></nav>
  <div class="sidefoot"><span id="refresh"></span><button class="btn" id="theme" title="Theme">◐</button></div>
</aside>
<div class="topbar"><button class="btn" id="menu">☰</button><span class="brand">Assist</span><span style="flex:1"></span><button class="btn" onclick="document.getElementById('q').focus()">⌕</button></div>
<main id="main"></main>
</div>
<div class="changes" id="changes"><button class="btn primary" id="chbtn">Changes to apply · 0</button><div class="panel" id="chpanel"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const byId = Object.fromEntries(D.docs.map(d => [d.id, d]));
function md(s){ if (window.marked){ marked.setOptions({gfm:true}); return marked.parse(s||''); } return '<pre style="white-space:pre-wrap">'+esc(s)+'</pre>'; }
function inline(s){ return md(s).replace(/^<p>|<\/p>\s*$/g,''); }
function store(k, def){ try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : def; } catch(e){ return def; } }
function save(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }
let done = new Set(store('assist-done', [])), seen = new Set(store('assist-seen', [])), lastVisit = store('assist-last-visit', null);

const TABS = [['today','Today','◎'],['commitments','Commitments','☑'],['decisions','Decisions','⚖'],['calendar','Calendar','▦'],['meetings','Meetings','◫'],['people','People','◌'],['initiatives','Initiatives','◆'],['library','Library','▤'],['sources','Sources','⇅']];
const GROUPS = [['Overview',['today']],['Work',['commitments','decisions','calendar','meetings']],['Knowledge',['people','initiatives','library']],['System',['sources']]];
function counts(){
  const open = D.tasks.filter(t => (t.group==='active') && !t.done && !done.has(t.id)).length;
  const wait = D.tasks.filter(t => t.group==='waiting' && !done.has(t.id)).length;
  const pend = D.decisions.filter(d => d.status==='pending').length;
  return {open, wait, pend};
}
function tabs(active){
  const c = counts();
  const n = {commitments: c.open + c.wait, decisions: c.pend, calendar: D.calendar.events.length, meetings: D.meetings.length, people: D.people.length, initiatives: D.projects.length, library: D.docs.length};
  $('#tabs').innerHTML = GROUPS.map(([g,keys]) => `<h5>${g}</h5>` + keys.map(k => { const t = TABS.find(x=>x[0]===k); return `<a href="#${k}" class="${active===k?'on':''}"><span class="g">${t[2]}</span>${t[1]}${n[k]?`<small>${n[k].toLocaleString()}</small>`:''}</a>`; }).join('')).join('');
  $('#built').textContent = 'built ' + (D.built.match(/\d{2}:\d{2}/)||[D.built])[0] + ' · ' + D.built_iso.slice(5);
}
const SHORT = {granola:'Granola', mail_teams_q3:'Mail + Teams Jul–Sep', mail_recent:'Mail', teams_recent:'Teams', slack:'Slack', calendar:'Calendar'};
function health(s){
  const lab = {ok:'OK', stale:'Stale', broken:'Broken', capped:'Capped'}[s.health] || s.health;
  const ic = {ok:'●', stale:'●', broken:'■', capped:'▲'}[s.health] || '●';
  return `<span class="src ${s.health}" onclick="location.hash='#sources'" title="${esc(s.note)}"><span class="dot"></span><b>${esc(SHORT[s.key]||s.source.split(' (')[0])}</b> ${lab} · ${esc(s.last_seen)}</span>`;
}
function stripOld(){
  return `<div class="strip"><span class="label">Sources</span>${D.coverage.sources.map(health).join('')}<span class="label" style="margin-left:auto">built ${esc(D.built)}</span></div>`;
}
function links(ls){ return (ls||[]).map(l => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a>`).join(' · '); }
function tag(t, cls){ return `<span class="tag ${cls||''}">${esc(t)}</span>`; }

// ---------------- Today
function viewToday(){
  const b = D.brief; const c = counts();
  if (!b) return strip() + '<div class="empty">No brief yet. Run /brief.</div>';
  const S = b.sections;
  const sec = (name, body) => body ? `<h2 class="sec">${esc(name)}</h2><div class="md">${md(body)}</div>` : '';
  const overdueDec = D.decisions.filter(d => d.status==='pending' && age(d.date) > 7).length;
  const tiles = `<div class="grid g4" style="margin-bottom:16px">
    <div class="tile"><div class="v">${c.open}</div><div class="l">commitments open</div><div class="n">${D.tasks.filter(t=>t.group==='active'&&t.origin!=='Current'&&!done.has(t.id)).length} carried over from Jul–Sep</div></div>
    <div class="tile"><div class="v">${c.wait}</div><div class="l">waiting on others</div><div class="n">${new Set(D.tasks.filter(t=>t.group==='waiting'&&t.person).map(t=>t.person)).size} people</div></div>
    <div class="tile"><div class="v">${c.pend}</div><div class="l">decisions pending</div><div class="n">${overdueDec} older than 7 days</div></div>
    <div class="tile"><div class="v">${D.meetings.filter(m=>m.status==='analysed').length}<span class="muted" style="font-size:16px">/${D.meetings.length}</span></div><div class="l">meetings analysed${D.meetings.filter(m=>m.status==='digested').length?` · <span style="color:var(--serious)">${D.meetings.filter(m=>m.status==='digested').length} awaiting triage</span>`:''}</div><div class="n">${D.coverage.sources.filter(s=>s.health!=='ok').length} source(s) need attention</div></div>
  </div>`;
  const bdate = (b.path.match(/(\d{4}-\d{2}-\d{2})/)||[])[1];
  const stale = bdate && bdate < D.built_iso ? `<div class="gap" style="margin:0 0 14px">This brief is for ${esc(bdate)}; today is ${esc(D.built_iso)}. Run <code>/brief</code> in Claude Code to refresh it.</div>` : '';
  return strip() + `<h1>${esc(b.title)}</h1>` + stale + `<div class="hero">${esc(b.today)}</div>` + tiles +
    `<div class="grid g2"><div>
      ${sec('Three things that matter', S['Three things that matter'])}
      ${sec('Decisions waiting on you', S['Decisions waiting on you'])}
      ${sec('People waiting on you', S['People waiting on you'])}
      ${sec('Prep', S['Prep'])}
    </div><div>
      ${todayAgenda() || sec('Shape of the day', S['Shape of the day'])}
      ${sec('Resolved since the last brief', S['Resolved since the last brief'])}
      ${sec('Drift', S['Drift'])}
      <p class="small muted" style="margin-top:18px">Sources for this brief: ${esc(b.sources_line)} · <a href="#library/${encodeURIComponent(b.path)}">open the brief file</a></p>
    </div></div>`;
}
function todayAgenda(){
  const E = (D.calendar.events||[]).filter(e => e.date===D.built_iso && !e.cancelled);
  if (!E.length) return '';
  const rows = E.map(e => `<tr><td class="muted" style="white-space:nowrap">${esc(e.time)}</td><td><b>${esc(e.subject)}</b>${e.attendees.length?`<div class="small muted">${esc(e.attendees.slice(0,5).join(', '))}${e.attendees.length>5?' +'+(e.attendees.length-5):''}</div>`:''}</td><td class="small" style="white-space:nowrap">${e.webLink?`<a href="${esc(e.webLink)}" target="_blank" rel="noopener">Outlook</a>`:''}</td></tr>`).join('');
  const hrs = Math.round(E.filter(e=>e.attendees.length).reduce((x,e)=>x+e.minutes,0)/6)/10;
  return `<h2 class="sec">Today's calendar · ${E.filter(e=>e.attendees.length).length} meetings · ${hrs} h</h2><div class="card" style="padding:4px 12px"><table class="list"><tbody>${rows}</tbody></table></div><p class="small muted" style="margin:6px 0 0"><a href="#calendar">Full calendar →</a></p>`;
}
function age(d){ const t = Date.parse(d); return isNaN(t) ? 0 : Math.floor((Date.parse(D.built_iso) - t)/86400000); }

// ---------------- Sources
function icon(sys, size){
  size = size || 28;
  const uri = sys.logo && D.logos[sys.logo];
  if (uri) return `<span class="ico has" style="width:${size}px;height:${size}px;--c:${sys.color}"><img src="${uri}" alt="${esc(sys.name)} logo"></span>`;
  return `<span class="ico" style="width:${size}px;height:${size}px;--c:${sys.color}"><span class="mono">${esc(sys.mono||sys.name[0])}</span></span>`;
}
function sysRows(sys){ return (D.coverage.sources||[]).filter(r => (sys.keys||[]).some(k => (r.key||'').startsWith(k))); }
function sysHealth(sys){
  const rows = sysRows(sys); if (!rows.length) return sys.streams && sys.streams.length ? 'planned' : 'planned';
  const order = ['broken','capped','stale','ok']; let worst = 'ok';
  for (const r of rows){ if (order.indexOf(r.health) < order.indexOf(worst)) worst = r.health; }
  return worst;
}
function sysLast(sys){ const rows = sysRows(sys).map(r=>r.last_seen).filter(Boolean).sort(); return rows[rows.length-1] || ''; }
function sysItems(sys){
  let n = 0;
  for (const st of (sys.streams||[])){
    if (st.source==='meetings') n += D.meetings.length;
    else if (st.source==='calendar') n += D.calendar.events.length;
    else if (st.source.startsWith('snap:')) n += (D.streams[st.source.slice(5)]||[]).reduce((x,t)=>x+t.rows.length,0);
  }
  return n;
}
const HL = {ok:'OK', stale:'Stale', broken:'Broken', capped:'Capped', planned:'Not pulled yet'};
function pill(h){ return `<span class="pill ${h}"><span class="dot"></span>${HL[h]||h}</span>`; }
function strip(){ return ''; }
function stripFull(){
  return `<div class="strip"><span class="label">Sources</span>${D.sources.map(sys => { const h = sysHealth(sys); return `<span class="src ${h}" onclick="location.hash='#sources/${sys.id}'" title="${esc(sys.kind)}">${icon(sys,16)}<b>${esc(sys.name)}</b> ${HL[h]} ${sysLast(sys)?'· '+esc(sysLast(sys)):''}</span>`; }).join('')}<span class="label" style="margin-left:auto">built ${esc(D.built)}</span></div>`;
}
function viewSources(id){
  if (id){ const sys = D.sources.find(x=>x.id===id); if (sys) return viewSystem(sys); }
  const rows = D.sources.map(sys => { const h = sysHealth(sys), win = sysRows(sys), items = sysItems(sys);
    const streams = (sys.streams||[]).map(st => `${esc(st.name)} ${streamCount(st).toLocaleString()}`).join(' · ');
    return `<tr class="click" onclick="location.hash='#sources/${sys.id}'">
      <td style="width:44px">${icon(sys,32)}</td>
      <td><b>${esc(sys.name)}</b><div class="small muted">${esc(sys.vendor)} · ${esc(sys.kind)}</div></td>
      <td>${pill(h)}</td>
      <td class="small" style="white-space:nowrap">${esc(sysLast(sys)||'—')}</td>
      <td class="small">${items?`<b>${items.toLocaleString()}</b> items${streams?`<div class="muted">${streams}</div>`:''}`:'<span class="muted">—</span>'}</td>
      <td class="small">${win.length?`${win.length} window${win.length===1?'':'s'}<div class="muted">${esc(win.map(r=>r.source.replace(/^[^(]*\(/,'').replace(/\)$/,'')).join(' · '))}</div>`:`<span class="muted">${esc(sys.connect)}</span>`}</td>
      <td class="small" style="white-space:nowrap"><a href="#sources/${sys.id}">Open →</a></td></tr>`; }).join('');
  const gaps = (D.coverage.gaps||[]).map(g => `<div class="gap">${esc(g)}</div>`).join('');
  return `<h1>Sources</h1><p class="muted small">Every system the assistant reads. Click a row for its pull windows and every item pulled. ${esc(D.coverage.freshness_rule||'')}</p>
    <div class="card" style="padding:4px 12px;margin-top:14px"><table class="list"><thead><tr><th></th><th>System</th><th>Status</th><th>Last seen</th><th>Pulled</th><th>Windows</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="small muted" style="margin:10px 2px"><b>Add a source:</b> authenticate the connector in Claude Code (<code>/mcp</code>), add a system to <code>inbox/sources.json</code> with the coverage keys it uses and its logo file in <code>assets/logos/</code>, and give <code>/brief</code> a pull step for it.</div>
    <h2 class="sec">Known gaps</h2>${gaps || '<div class="empty">None recorded.</div>'}
    <h2 class="sec">Sync log</h2><div class="card"><div class="small">Meetings digested: <b>${D.sync.digested}</b> · last digest run: ${esc(D.sync.last_run||'—')}</div><pre class="small" style="margin:10px 0 0;white-space:pre-wrap;color:var(--ink2)">${esc(D.sync.log)}</pre></div>`;
}
let sf = store('assist-sf', {});
function viewSystem(sys){
  const h = sysHealth(sys), rows = sysRows(sys);
  const windows = rows.map(r => `<tr><td>${esc(r.source)}</td><td>${esc(String(r.available))}</td><td>${esc(String(r.digested))}</td><td>${esc(String(r.analysed))}</td><td>${pill(r.health)}</td><td class="muted">${esc(r.last_seen||'')}</td><td class="small muted">${esc(r.note||'')}</td></tr>`).join('');
  const key = sys.id; const cur = sf[key] || {stream: (sys.streams[0]||{}).id, q:'', limit:150};
  const streamTabs = (sys.streams||[]).map(st => `<span class="chip ${cur.stream===st.id?'on':''}" onclick="sf['${key}']=Object.assign({},sf['${key}']||{},{stream:'${st.id}',limit:150});save('assist-sf',sf);render()">${esc(st.name)}<small>${streamCount(st).toLocaleString()}</small></span>`).join('');
  const st = (sys.streams||[]).find(x=>x.id===cur.stream);
  let body = '';
  if (st) body = streamBody(st, cur, key);
  const pulls = D.pulls.filter(p => sys.keys.some(k => p.title.toLowerCase().includes(k==='mail'?'live':k)));
  return strip() + `<div class="crumbs"><a href="#sources">Sources</a> / ${esc(sys.name)}</div>
    <div class="syshead" style="margin:6px 0 14px">${icon(sys,44)}<div><h1 style="margin:0">${esc(sys.name)}</h1><div class="sub">${esc(sys.vendor)} · ${esc(sys.kind)}</div></div><div style="margin-left:auto;text-align:right">${pill(h)}<div class="small muted" style="margin-top:4px">last seen ${esc(sysLast(sys)||'—')}</div></div></div>
    ${sys.streams.length?`<div class="chips"><span class="label small muted">Items pulled</span>${streamTabs}<input class="btn" style="width:240px;margin-left:10px" placeholder="filter items…" value="${esc(cur.q||'')}" oninput="sf['${key}']=Object.assign({},sf['${key}']||{stream:'${cur.stream}'},{q:this.value,limit:150});save('assist-sf',sf);renderKeep(this)"></div>${body}`:'<div class="empty">Nothing pulled from this system yet.</div>'}
    <h2 class="sec">Pull windows · ${rows.length}</h2>
    ${rows.length?`<div class="card" style="padding:4px 18px">${rows.map(r=>`<div class="row" style="grid-template-columns:1fr auto"><div><div><b>${esc(r.source)}</b> · ${esc(String(r.available))} available · ${esc(String(r.digested))} digested · ${esc(String(r.analysed))} analysed</div><div class="who">${esc(r.note||'')}</div></div><div style="text-align:right">${pill(r.health)}<div class="small muted" style="margin-top:4px">last seen ${esc(r.last_seen||'—')}</div></div></div>`).join('')}</div>`:'<div class="empty">Nothing pulled yet.</div>'}
    <h2 class="sec">How it is pulled</h2><div class="card"><div class="sub">${esc(sys.how)}</div><div class="small muted" style="margin-top:8px"><b>Auth:</b> ${esc(sys.auth)} · <b>Status:</b> ${esc(sys.connect)}</div></div>`;
}
function streamCount(st){
  if (st.source==='meetings') return D.meetings.length;
  if (st.source==='calendar') return D.calendar.events.length;
  if (st.source.startsWith('snap:')) return (D.streams[st.source.slice(5)]||[]).reduce((x,t)=>x+t.rows.length,0);
  return 0;
}
function streamBody(st, cur, key){
  const q = (cur.q||'').trim(); const re = q ? new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'i') : null;
  if (st.source==='meetings'){
    let list = D.meetings; if (re) list = list.filter(m => re.test(m.title+' '+m.with.join(' ')+' '+(m.calendar||'')));
    return `<div class="card" style="padding:4px 12px"><table class="list"><thead><tr><th>Date</th><th>Meeting</th><th>With</th><th>Status</th><th></th></tr></thead><tbody>${list.slice(0,cur.limit).map(m=>`<tr class="click" onclick="location.hash='#library/${m.id}'"><td class="muted">${esc(m.date)}</td><td><b>${esc(m.title)}</b>${m.calendar?`<div class="small muted">📅 ${esc(m.calendar)}</div>`:''}</td><td class="small">${esc(m.with.join(', '))}</td><td>${tag(m.status, m.status==='analysed'?'taken':'pending')}</td><td class="small" onclick="event.stopPropagation()"><a href="${esc(m.granola)}" target="_blank" rel="noopener">Granola</a></td></tr>`).join('')}</tbody></table>${more(list.length,cur,key)}</div>`;
  }
  if (st.source==='calendar'){
    let list = D.calendar.events; if (re) list = list.filter(e => re.test(e.subject+' '+e.attendees.join(' ')+' '+e.organizer));
    return `<div class="card" style="padding:4px 12px"><table class="list"><thead><tr><th>Date</th><th>Time</th><th>Event</th><th>Attendees</th><th>Granola</th><th></th></tr></thead><tbody>${list.slice(0,cur.limit).map(e=>`<tr><td class="muted">${esc(e.date)}</td><td class="muted">${esc(e.time)}</td><td><b>${esc(e.subject)}</b>${e.cancelled?' <span class="tag">cancelled</span>':''}</td><td class="small">${esc(e.attendees.slice(0,5).join(', '))}${e.attendees.length>5?' +'+(e.attendees.length-5):''}</td><td>${e.recorded?tag('recorded','taken'):(e.unrecorded?tag('not recorded','pending'):'')}</td><td class="small">${e.webLink?`<a href="${esc(e.webLink)}" target="_blank" rel="noopener">Outlook</a>`:''}</td></tr>`).join('')}</tbody></table>${more(list.length,cur,key)}</div>`;
  }
  if (st.source.startsWith('snap:')){
    const tables = D.streams[st.source.slice(5)] || [];
    if (!tables.length) return '<div class="empty">Nothing pulled for this stream yet.</div>';
    let shown = 0, html = '';
    for (const t of tables){
      let rows = t.rows; if (re) rows = rows.filter(r => re.test(r.c.join(' ')));
      if (!rows.length) continue;
      const take = Math.max(0, Math.min(rows.length, cur.limit - shown)); shown += take;
      html += `<h2 class="sec">${esc(t.title)} · ${esc(t.heading)} · ${rows.length} row${rows.length===1?'':'s'} <a class="small" href="#library/${encodeURIComponent(t.doc)}" style="font-weight:400;text-transform:none;letter-spacing:0">open snapshot (${esc(t.mtime)})</a></h2>
        <div class="card" style="padding:4px 12px"><table class="list"><thead><tr>${t.headers.map(x=>`<th>${esc(x)}</th>`).join('')}<th></th></tr></thead><tbody>${rows.slice(0,take).map(r=>`<tr>${r.c.map(c=>`<td class="small">${re?highlight(esc(c),q):esc(c)}</td>`).join('')}<td class="small" style="white-space:nowrap">${r.l.map(l=>`<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`).join(' · ')}</td></tr>`).join('')}</tbody></table>${rows.length>take?`<div class="small muted" style="padding:8px">${rows.length-take} more in this table</div>`:''}</div>`;
      if (shown >= cur.limit) break;
    }
    const total = tables.reduce((x,t)=>x+(re?t.rows.filter(r=>re.test(r.c.join(' '))).length:t.rows.length),0);
    return (html || '<div class="empty">No matches.</div>') + more(total, cur, key);
  }
  return '<div class="empty">Not pulled yet.</div>';
}
function more(total, cur, key){ return total > cur.limit ? `<div style="padding:10px 0"><button class="btn" onclick="sf['${key}']=Object.assign({},sf['${key}'],{limit:${cur.limit+300}});save('assist-sf',sf);render()">Show more (${(total-cur.limit).toLocaleString()} left)</button></div>` : ''; }
function renderKeep(input){ const v = input.value, pos = input.selectionStart; render(); const i = document.querySelector('input.btn[placeholder="filter items…"]'); if (i){ i.focus(); i.setSelectionRange(pos,pos); } }
function viewSourcesOld(){
  const C = D.coverage;
  const tiles = C.sources.map(s => {
    const av = parseInt(String(s.available).replace(/[^0-9]/g,'')) || 0, an = parseInt(String(s.analysed).replace(/[^0-9]/g,'')) || 0;
    const pct = av && an ? Math.min(100, Math.round(an/av*100)) : (String(s.analysed).startsWith('all') ? 100 : 0);
    return `<div class="tile"><div class="small ${s.health}" style="display:flex;gap:6px;align-items:center"><span class="dot"></span>${esc({ok:'OK',stale:'Stale',broken:'Broken',capped:'Capped'}[s.health]||s.health)} · last ${esc(s.last_seen)}</div>
      <div class="v" style="font-size:22px;margin-top:6px">${esc(s.source)}</div>
      <div class="l"><b>${esc(s.available)}</b> available · <b>${esc(s.digested)}</b> digested · <b>${esc(s.analysed)}</b> analysed</div>
      <div class="meter"><i style="width:${pct}%"></i></div>
      <div class="n">${esc(s.note)}</div></div>`;
  }).join('');
  const gaps = (C.gaps||[]).map(g => `<div class="gap">${esc(g)}</div>`).join('');
  const pulls = D.pulls.map(p => `<tr class="click" onclick="location.hash='#library/${encodeURIComponent(p.id)}'"><td>${esc(p.mtime)}</td><td>${esc(p.title)}</td><td class="muted">${p.words.toLocaleString()} words</td></tr>`).join('');
  return strip() + `<h1>Everything that went in</h1><p class="sub muted">Available = what the source holds in the window · Digested = copied here as metadata or summary · Analysed = read and turned into commitments, decisions and memory. ${esc(C.freshness_rule||'')}</p>
    <div class="grid gcards" style="margin-top:14px">${tiles}</div>
    <h2 class="sec">Known gaps</h2>${gaps || '<div class="empty">None recorded.</div>'}
    <h2 class="sec">Every pull, digest and analysis (${D.pulls.length})</h2>
    <div class="card" style="padding:4px 12px"><table class="list"><thead><tr><th>Updated</th><th>Document</th><th></th></tr></thead><tbody>${pulls}</tbody></table></div>
    <h2 class="sec">Sync</h2><div class="card"><div class="small">Meetings digested: <b>${D.sync.digested}</b> · last digest run: ${esc(D.sync.last_run||'—')}</div><pre class="small" style="margin:10px 0 0;white-space:pre-wrap;color:var(--ink2)">${esc(D.sync.log)}</pre></div>`;
}

// ---------------- Commitments
let tf = store('assist-tf', {group:'active', init:'', person:'', q:''});
function viewCommitments(){
  const groups = [['active','I owe'],['waiting','Owed to me'],['someday','Someday'],['done','Done']];
  const cnt = g => D.tasks.filter(t => t.group===g && (g==='done' ? true : !done.has(t.id))).length + (g==='active'||g==='waiting' ? 0 : 0);
  const inits = D.initiatives.filter(i => D.tasks.some(t => t.initiatives.includes(i)));
  const persons = [...new Set(D.tasks.filter(t=>t.group==='waiting'&&t.person).map(t=>t.person))].sort();
  let list = D.tasks.filter(t => t.group===tf.group || (tf.group==='done' && done.has(t.id)));
  if (tf.group!=='done') list = list.filter(t => !done.has(t.id) || tf.group==='done');
  if (tf.init) list = list.filter(t => t.initiatives.includes(tf.init));
  if (tf.person) list = list.filter(t => t.person===tf.person);
  if (tf.q) { const re = new RegExp(tf.q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'i'); list = list.filter(t => re.test(t.title+' '+t.context)); }
  const origins = [...new Set(list.map(t=>t.origin))];
  const section = o => list.filter(t=>t.origin===o).map(item).join('');
  const item = t => `<div class="item ${done.has(t.id)?'done':''}" id="${t.id}"><input type="checkbox" ${done.has(t.id)?'checked':''} onchange="toggle('${t.id}')" title="Tick when done; it goes to Changes to apply">
    <div><div class="t">${esc(t.title)}</div>${t.context?`<div class="c">${esc(t.context)}</div>`:''}<div class="m">${t.person?tag(t.person):''}${t.initiatives.map(i=>tag(i)).join('')}${links(t.links)}</div></div></div>`;
  return strip() + `<h1>Commitments</h1>
    <div class="chips">${groups.map(([g,l])=>`<span class="chip ${tf.group===g?'on':''}" onclick="setf('group','${g}')">${l}<small>${cnt(g)}</small></span>`).join('')}</div>
    <div class="chips"><span class="label small muted">Initiative</span>${inits.map(i=>`<span class="chip ${tf.init===i?'on':''}" onclick="setf('init','${esc(i)}')">${esc(i)}</span>`).join('')}</div>
    ${tf.group==='waiting'?`<div class="chips"><span class="label small muted">Person</span>${persons.map(p=>`<span class="chip ${tf.person===p?'on':''}" onclick="setf('person','${esc(p)}')">${esc(p)}</span>`).join('')}</div>`:''}
    <div class="chips"><input class="btn" style="width:280px" placeholder="filter…" value="${esc(tf.q)}" oninput="setf('q',this.value,true)">${(tf.init||tf.person||tf.q)?`<span class="chip" onclick="setf('clear')">clear</span>`:''}<span class="muted small" style="margin-left:auto">${list.length} shown</span></div>
    ${origins.map(o => `<h2 class="sec">${esc(o)} · ${list.filter(t=>t.origin===o).length}</h2><div class="card" style="padding:4px 18px">${section(o)}</div>`).join('') || '<div class="empty">Nothing here.</div>'}`;
}
function setf(k, v, keep){ if (k==='clear'){ tf.init=''; tf.person=''; tf.q=''; } else if (tf[k]===v && k!=='q' && k!=='group'){ tf[k]=''; } else { tf[k]=v; } save('assist-tf', tf); if (keep){ const m=$('#main'); const pos=m.scrollTop; render(); const i=m.querySelector('input.btn'); if(i){ i.focus(); i.setSelectionRange(i.value.length,i.value.length);} } else render(); }
function toggle(id){ done.has(id) ? done.delete(id) : done.add(id); save('assist-done', [...done]); render(); }

// ---------------- Decisions
let df = store('assist-df', {status:'pending', init:''});
function viewDecisions(){
  let list = D.decisions.filter(d => df.status==='all' || d.status===df.status);
  if (df.init) list = list.filter(d => d.initiatives.includes(df.init));
  const inits = D.initiatives.filter(i => D.decisions.some(d => d.initiatives.includes(i)));
  const rows = list.map(d => `<div class="row"><div class="d">${esc(d.date)}${d.status==='pending'?`<br><span class="${age(d.date)>7?'serious':''}" style="color:${age(d.date)>7?'var(--serious)':'inherit'}">${age(d.date)} d</span>`:''}</div>
     <div><div>${esc(d.decision)}</div><div class="who">${esc(d.owner)} · ${esc(d.status_note)}${d.source_text?' · '+esc(d.source_text):''} ${links(d.links)}</div><div class="m" style="margin-top:4px">${d.initiatives.map(i=>tag(i)).join(' ')}</div></div>
     <div>${tag(d.status, d.status)}</div></div>`).join('');
  return strip() + `<h1>Decisions</h1>
    <div class="chips">${[['pending','Pending'],['taken','Taken'],['all','All']].map(([k,l])=>`<span class="chip ${df.status===k?'on':''}" onclick="df.status='${k}';save('assist-df',df);render()">${l}<small>${k==='all'?D.decisions.length:D.decisions.filter(d=>d.status===k).length}</small></span>`).join('')}
    <span class="label small muted" style="margin-left:10px">Initiative</span>${inits.map(i=>`<span class="chip ${df.init===i?'on':''}" onclick="df.init=df.init==='${esc(i)}'?'':'${esc(i)}';save('assist-df',df);render()">${esc(i)}</span>`).join('')}<span class="muted small" style="margin-left:auto">${list.length} shown</span></div>
    <div class="card" style="padding:4px 18px">${rows || '<div class="empty">Nothing here.</div>'}</div>`;
}

// ---------------- Meetings
let mf = store('assist-mf', {month:'', status:'', init:''});
function viewMeetings(){
  const months = [...new Set(D.meetings.map(m=>m.date.slice(0,7)))].sort().reverse();
  let list = D.meetings.filter(m => (!mf.month || m.date.startsWith(mf.month)) && (!mf.status || m.status===mf.status) && (!mf.init || m.initiatives.includes(mf.init)));
  const inits = D.initiatives.filter(i => D.meetings.some(m => m.initiatives.includes(i)));
  const rows = list.map(m => `<tr class="click" onclick="location.hash='#library/${m.id}'"><td class="muted" style="white-space:nowrap">${esc(m.date)}</td><td><b>${esc(m.title)}</b>${m.calendar?`<div class="small muted">📅 ${esc(m.calendar)}${m.organizer?' · '+esc(m.organizer):''}</div>`:''}${m.with.length?`<div class="small muted">with ${esc(m.with.join(', '))}</div>`:''}</td><td class="small">${m.initiatives.slice(0,3).map(i=>tag(i)).join(' ')}</td><td class="muted small">${m.segments}</td><td>${tag(m.status, m.status==='analysed'?'taken':(m.status==='pending'||m.status==='digested'?'pending':''))}</td><td class="small" onclick="event.stopPropagation()"><a href="${esc(m.granola)}" target="_blank" rel="noopener">Granola</a>${m.transcript?` · <a href="${esc(m.transcript)}" target="_blank">transcript</a>`:''}</td></tr>`).join('');
  return strip() + `<h1>Meetings</h1>
    <div class="chips">${months.map(mo=>`<span class="chip ${mf.month===mo?'on':''}" onclick="mf.month=mf.month==='${mo}'?'':'${mo}';save('assist-mf',mf);render()">${mo}<small>${D.meetings.filter(m=>m.date.startsWith(mo)).length}</small></span>`).join('')}
    <span class="label small muted" style="margin-left:10px">Status</span>${['analysed','digested','pending','personal'].map(s=>`<span class="chip ${mf.status===s?'on':''}" onclick="mf.status=mf.status==='${s}'?'':'${s}';save('assist-mf',mf);render()">${s}<small>${D.meetings.filter(m=>m.status===s).length}</small></span>`).join('')}</div>
    <div class="chips"><span class="label small muted">Initiative</span>${inits.map(i=>`<span class="chip ${mf.init===i?'on':''}" onclick="mf.init=mf.init==='${esc(i)}'?'':'${esc(i)}';save('assist-mf',mf);render()">${esc(i)}</span>`).join('')}<span class="muted small" style="margin-left:auto">${list.length} shown · click a row for its summary</span></div>
    <div class="card" style="padding:4px 12px"><table class="list"><thead><tr><th>Date</th><th>Meeting</th><th>Initiatives</th><th>Segments</th><th>Status</th><th>Links</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// ---------------- Calendar
let cf = store('assist-cf', {range:'week', only:''});
function viewCalendar(){
  const E = D.calendar.events; const today = D.built_iso;
  if (!E.length) return strip() + '<h1>Calendar</h1><div class="empty">No calendar pulled yet. Run a full refresh.</div>';
  const addDays = (d,n) => { const x = new Date(d+'T00:00:00'); x.setDate(x.getDate()+n); return x.toISOString().slice(0,10); };
  const ranges = {week:[addDays(today,-((new Date(today+'T00:00:00').getDay()+6)%7)), addDays(today,7)], next2:[today, addDays(today,14)], past:[E[0].date, addDays(today,-1)], all:[E[0].date, E[E.length-1].date]};
  const [a,b] = ranges[cf.range] || ranges.week;
  let list = E.filter(e => e.date>=a && e.date<=b && !e.cancelled);
  if (cf.only==='unrecorded') list = list.filter(e => e.unrecorded);
  if (cf.only==='recorded') list = list.filter(e => e.recorded);
  if (cf.only==='meetings') list = list.filter(e => e.attendees.length);
  const days = [...new Set(list.map(e=>e.date))];
  const st = D.calendar.stats || {};
  const tiles = `<div class="grid g4" style="margin-bottom:16px">
    <div class="tile"><div class="v">${E.filter(e=>!e.cancelled).length}</div><div class="l">events pulled</div><div class="n">${E[0].date} → ${E[E.length-1].date}${D.calendar.pulled?' · pulled '+esc(D.calendar.pulled.slice(0,16).replace('T',' ')):''}</div></div>
    <div class="tile"><div class="v">${st.matched??'—'}<span class="muted" style="font-size:16px">/${st.notes??'—'}</span></div><div class="l">Granola notes matched to an event</div><div class="n">±${st.tolerance_minutes??12} min start tolerance</div></div>
    <div class="tile"><div class="v">${st.unrecorded_meetings_with_attendees??'—'}</div><div class="l">past meetings with attendees, not recorded</div><div class="n">no Granola note found</div></div>
    <div class="tile"><div class="v">${E.filter(e=>e.date>=today&&e.date<=addDays(today,6)&&!e.cancelled&&e.attendees.length).length}</div><div class="l">meetings in the next 7 days</div><div class="n">${Math.round(E.filter(e=>e.date>=today&&e.date<=addDays(today,6)&&!e.cancelled&&e.attendees.length).reduce((x,e)=>x+e.minutes,0)/60)} hours</div></div></div>`;
  const row = e => `<tr><td class="muted" style="white-space:nowrap">${esc(e.time)}</td><td><b>${esc(e.subject)}</b>${e.location&&!/teams/i.test(e.location)?`<div class="small muted">${esc(e.location)}</div>`:''}</td><td class="small">${e.attendees.length?esc(e.attendees.slice(0,6).join(', '))+(e.attendees.length>6?` +${e.attendees.length-6}`:''):'<span class="muted">—</span>'}</td><td class="small muted">${esc(e.organizer||'')}</td><td>${e.date<today||e.date===today&&e.time.slice(0,5)<new Date().toTimeString().slice(0,5)?(e.recorded?tag('recorded','taken'):(e.unrecorded?tag('not recorded','pending'):tag('no attendees'))):tag('upcoming')}</td><td class="small">${e.webLink?`<a href="${esc(e.webLink)}" target="_blank" rel="noopener">Outlook</a>`:''}${e.recorded?` · <a href="#meetings">note</a>`:''}</td></tr>`;
  const body = days.map(d => `<tr><td colspan="6" style="background:var(--panel2);font-weight:600;padding:8px">${esc(list.find(e=>e.date===d).day)}${d===today?' · today':''}</td></tr>` + list.filter(e=>e.date===d).map(row).join('')).join('');
  return strip() + `<h1>Calendar</h1>` + tiles +
    `<div class="chips">${[['week','This week'],['next2','Next 14 days'],['past','Past'],['all','All']].map(([k,l])=>`<span class="chip ${cf.range===k?'on':''}" onclick="cf.range='${k}';save('assist-cf',cf);render()">${l}</span>`).join('')}
    <span class="label small muted" style="margin-left:10px">Show</span>${[['','everything'],['meetings','with attendees'],['recorded','recorded in Granola'],['unrecorded','not recorded']].map(([k,l])=>`<span class="chip ${cf.only===k?'on':''}" onclick="cf.only='${k}';save('assist-cf',cf);render()">${l}</span>`).join('')}<span class="muted small" style="margin-left:auto">${list.length} events</span></div>
    <div class="card" style="padding:4px 12px"><table class="list"><thead><tr><th>Time</th><th>Event</th><th>Attendees</th><th>Organiser</th><th>Granola</th><th></th></tr></thead><tbody>${body || '<tr><td colspan="6" class="empty">Nothing in this range.</td></tr>'}</tbody></table></div>`;
}

// ---------------- People / Initiatives
function viewPeople(){
  const cards = D.people.map(p => `<div class="card click" onclick="location.hash='#library/${p.id}'"><h3>${esc(p.name)}</h3><div class="sub">${esc(p.role)}</div>
    <div class="m" style="margin:8px 0 6px;display:flex;gap:6px;flex-wrap:wrap">${p.threads?tag(p.threads+' open thread'+(p.threads>1?'s':''), 'pending'):tag('no open threads')}${p.relationship?tag(p.relationship.split(';')[0]):''}</div>
    ${p.last?`<div class="small muted">Last: ${esc(p.last)}</div>`:''}</div>`).join('');
  return strip() + `<h1>People</h1><p class="muted small">Sorted by open threads with you. Click for the full profile.</p><div class="grid gcards">${cards}</div>`;
}
function viewInitiatives(){
  const st = s => ({'on track':'taken','at risk':'pending','blocked':'pending','paused':''}[s]||'');
  const cards = D.projects.map(p => `<div class="card click" onclick="location.hash='#library/${p.id}'"><div style="display:flex;justify-content:space-between;gap:8px;align-items:start"><h3>${esc(p.name)}</h3>${tag(p.status||'—', st(p.status))}</div>
    <div class="sub">${esc(p.stands)}</div>
    <div class="m" style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">${p.pending?tag(p.pending+' decision'+(p.pending>1?'s':'')+' pending','pending'):''}${p.risks?tag(p.risks+' risks'):''}${p.owner?tag('owner: '+p.owner):''}</div>
    ${p.milestone?`<div class="small" style="margin-top:8px"><span class="muted">Next:</span> ${esc(p.milestone)}</div>`:''}</div>`).join('');
  return strip() + `<h1>Initiatives</h1><div class="grid gcards">${cards}</div>`;
}

// ---------------- Library
const LIB_ORDER = ['Briefs','Weekly reviews','Commitments','Decisions','Analyses','Pulls','Digests','Drafts','Memory','Initiatives','People','System','Meetings'];
function viewLibrary(id, term){
  const d = id && byId[id];
  const nav = LIB_ORDER.map(sec => { const ds = D.docs.filter(x => x.section===sec); if (!ds.length) return '';
    const limit = sec==='Meetings' ? 40 : 200;
    return `<h4>${sec} · ${ds.length}</h4>` + ds.slice(0,limit).map(x => `<a href="#library/${encodeURIComponent(x.id)}" class="${d&&d.id===x.id?'on':''}" title="${esc(x.title)}">${esc(x.title)}</a>`).join('') + (ds.length>limit?`<a href="#meetings" class="muted">… all ${ds.length} under Meetings</a>`:''); }).join('');
  let body;
  if (d){ let html = md(d.md); if (term) html = highlight(html, term);
    const chips = Object.entries(d.meta||{}).map(([k,v]) => tag(k+': '+v)).join(' ');
    body = `<div class="crumbs">${esc(d.section)} / ${esc(d.path)}${d.mtime?' · '+esc(d.mtime):''}</div>${chips?`<div class="chips">${chips}</div>`:''}<div class="md">${html}</div>`; }
  else body = `<div class="empty">Pick a document on the left, or search.</div>`;
  return `<div class="lib"><nav>${nav}</nav><div class="card">${body}</div></div>`;
}
function highlight(html, term){
  const re = new RegExp('(' + term.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + ')','gi');
  const tpl = document.createElement('template'); tpl.innerHTML = html;
  const w = document.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT); const nodes=[]; while (w.nextNode()) nodes.push(w.currentNode);
  for (const n of nodes){ if (!re.test(n.nodeValue)) continue; const s=document.createElement('span'); s.innerHTML = esc(n.nodeValue).replace(re,'<mark>$1</mark>'); n.replaceWith(...s.childNodes); }
  return tpl.innerHTML;
}

// ---------------- Search
function viewSearch(term){
  const re = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'i');
  const tasks = D.tasks.filter(t => re.test(t.title+' '+t.context)).slice(0,25);
  const decs = D.decisions.filter(d => re.test(d.decision+' '+d.owner)).slice(0,25);
  const docs = D.docs.filter(d => re.test(d.title) || re.test(d.md)).slice(0,60);
  const snip = (s) => { const i = s.search(re); return i<0 ? '' : '…'+esc(s.slice(Math.max(0,i-80), i+140).replace(/\n+/g,' '))+'…'; };
  return `<h1>${tasks.length+decs.length+docs.length} results for “${esc(term)}”</h1><div class="grid g2"><div>
    <h2 class="sec">Commitments · ${tasks.length}</h2><div class="card results">${tasks.map(t=>`<div class="r"><a href="#commitments" onclick="tf.q='${esc(term)}';tf.group='${t.group}';save('assist-tf',tf)">${highlight(esc(t.title),term)}</a><small>${t.group}</small><p>${highlight(esc(t.context),term)}</p></div>`).join('')||'<div class="empty">none</div>'}</div>
    <h2 class="sec">Decisions · ${decs.length}</h2><div class="card results">${decs.map(d=>`<div class="r"><a href="#decisions" onclick="df.status='all';save('assist-df',df)">${highlight(esc(d.decision),term)}</a><small>${d.date} · ${d.status}</small></div>`).join('')||'<div class="empty">none</div>'}</div>
    </div><div><h2 class="sec">Documents and meetings · ${docs.length}</h2><div class="card results">${docs.map(d=>`<div class="r"><a href="#library/${encodeURIComponent(d.id)}">${highlight(esc(d.title),term)}</a><small>${esc(d.section)}</small><p>${highlight(snip(d.md),term)}</p></div>`).join('')||'<div class="empty">none</div>'}</div></div></div>`;
}

// ---------------- Changes to apply
function changes(){
  const ds = [...done].map(id => D.tasks.find(t=>t.id===id)).filter(Boolean);
  $('#chbtn').textContent = `Changes to apply · ${ds.length}`;
  const text = ds.length ? 'In Assist/TASKS.md, mark these as done (today):\n' + ds.map(t=>`- ${t.title}`).join('\n') : '';
  $('#chpanel').innerHTML = ds.length ? `<div class="small muted" style="margin-bottom:8px">Ticked here only. Paste this into Claude to write it back to the files.</div><textarea readonly>${esc(text)}</textarea><div style="display:flex;gap:8px;margin-top:8px"><button class="btn primary" onclick="navigator.clipboard&&navigator.clipboard.writeText(${JSON.stringify(text)})">Copy</button><button class="btn" onclick="done.clear();save('assist-done',[]);render()">Clear ticks</button></div>` : '<div class="small muted">Tick a commitment and it appears here as text you can hand to Claude.</div>';
}
$('#chbtn').addEventListener('click', () => $('#changes').classList.toggle('open'));

// ---------------- Refresh (only when served by scripts/serve.py)
const SERVED = location.protocol.startsWith('http');
let rfState = null, rfTimer = null;
function refreshUI(){
  const el = $('#refresh'); if (!SERVED){ el.innerHTML = `<span class="btn" title="Open http://localhost:8765 to get a Refresh button that pulls new data" onclick="alert('Refresh works when the page is served by scripts/serve.py.\nOpen http://localhost:8765 instead of the file.')">↻</span>`; return; }
  const running = rfState && rfState.running;
  const last = rfState && rfState.finished ? ` · last ${rfState.ok?'ok':'failed'} ${rfState.finished.slice(11,16)}` : '';
  el.innerHTML = `<span class="rf" id="rf"><button class="btn ${running?'':'primary'}" onclick="document.getElementById('rf').classList.toggle('open')">${running?'<span class="spin">↻</span> Refreshing…':'↻ Refresh'}</button>
    <div class="menu"><button onclick="startRefresh('sync')">Pull new meetings and rebuild<small>Granola → digest → page. About a minute.</small></button>
    <button onclick="startRefresh('full')">Full refresh with Claude<small>Also mail, Teams, Slack and calendar, then a new brief. 5–10 minutes. Uses your Claude session.</small></button>
    ${rfState&&rfState.log?`<pre>${esc(rfState.log.slice(-3000))}</pre>`:''}${last?`<small style="display:block;padding:6px 10px;color:var(--ink3)">${esc(last)}</small>`:''}</div></span>`;
}
async function pollStatus(first){
  try { const r = await fetch('/status', {cache:'no-store'}); const st = await r.json(); const wasRunning = rfState && rfState.running; rfState = st; refreshUI();
    if (st.running){ clearTimeout(rfTimer); rfTimer = setTimeout(() => pollStatus(false), 2000); }
    else if (wasRunning && st.finished){ setTimeout(() => location.reload(), 800); }
  } catch(e){ /* server gone */ }
}
async function startRefresh(mode){
  document.getElementById('rf').classList.remove('open');
  const r = await fetch('/refresh?mode='+mode, {method:'POST'}); const j = await r.json();
  if (!j.started){ alert('Already running'); }
  pollStatus(true);
}

// ---------------- Router
function render(){
  const h = decodeURIComponent(location.hash.slice(1)) || 'today';
  const [view, ...rest] = h.split('/'); const id = rest.join('/');
  const term = $('#q').value.trim();
  const main = $('#main');
  let html;
  if (term && view!=='library'){ tabs(''); html = viewSearch(term); }
  else {
    tabs(view);
    html = {today:viewToday, sources:()=>viewSources(id), commitments:viewCommitments, decisions:viewDecisions, calendar:viewCalendar, meetings:viewMeetings, people:viewPeople, initiatives:viewInitiatives}[view]?.() ?? viewLibrary(id, term);
    if (view==='library') html = strip() + html;
  }
  main.innerHTML = html;
  main.querySelectorAll('.md a[href^="http"]').forEach(a => { a.target='_blank'; a.rel='noopener'; });
  changes();
  document.title = (TABS.find(t=>t[0]===view)?.[1] || (byId[id]?.title) || 'Assist') + ' · Assist';
  window.scrollTo(0,0);
}
$('#q').addEventListener('input', () => render());
document.addEventListener('keydown', e => { if (e.key==='/' && document.activeElement!==$('#q')){ e.preventDefault(); $('#q').focus(); } if (e.key==='Escape' && document.activeElement===$('#q')){ $('#q').value=''; $('#q').blur(); render(); } });
$('#theme').addEventListener('click', () => { const r=document.documentElement; const cur=r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'); r.dataset.theme=cur==='dark'?'light':'dark'; save('assist-theme', r.dataset.theme); });
try { const t = store('assist-theme', null); if (t) document.documentElement.dataset.theme = t; } catch(e){}
window.addEventListener('hashchange', () => { document.getElementById('side').classList.remove('open'); render(); });
document.getElementById('menu').addEventListener('click', () => document.getElementById('side').classList.toggle('open'));
render();
refreshUI(); if (SERVED) pollStatus(true);
save('assist-last-visit', D.built_iso);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
