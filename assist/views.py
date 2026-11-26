"""The app's shared view model ("bootstrap"), built from the database: api.snapshot() reads it for the calendar,
meetings, documents and source lists. (The classic page and the static export it fed were retired on 22 Oct 2026.)
"""
import base64
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import initiatives as initiatives_mod
from . import profile
from . import db

ASSIST = db.ASSIST
GRANOLA = ASSIST.parent / "Granola Export"
sys.path.insert(0, str(db.APP / "scripts"))
import build_ui as legacy  # noqa: E402  (brief parser, timezone helper)

TZ = legacy.TZ
SYSTEM_STREAMS = {"granola": ["granola"], "outlook": ["outlook.inbox", "outlook.sent"], "calendar": ["calendar"], "teams": ["teams"],
                  "slack": ["slack"], "acme-kb": ["acme-kb"], "public-docs": ["public-docs"], "jira": ["jira"], "sharepoint": ["sharepoint"], "salesforce": ["salesforce"]}
STREAM_LABEL = {"local": "Files", "granola": "Meeting notes", "outlook.inbox": "Inbox", "outlook.sent": "Sent", "calendar": "Events", "teams": "Messages",
                "slack": "Messages", "acme-kb": "Notes", "public-docs": "Pages", "jira": "Issues", "sharepoint": "Documents", "salesforce": "Pipeline", "teams-transcripts": "Transcripts"}


def local(ts):
    try:
        ts = re.sub(r"\.\d+", "", ts or "")
        if not re.search(r"(Z|[+-]\d{2}:\d{2})$", ts):
            ts += "Z"
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(TZ) if TZ else dt
    except Exception:
        return None


def fmt(ts, f="%Y-%m-%d %H:%M"):
    d = local(ts)
    return d.strftime(f) if d else (ts or "")


def logos():
    out = {}
    folder = db.APP / "assets" / "logos"
    for f in sorted(folder.glob("*")) if folder.exists() else []:
        if f.suffix.lower() in (".svg", ".png") and f.stat().st_size > 200:
            mime = "image/svg+xml" if f.suffix.lower() == ".svg" else "image/png"
            out.setdefault(f.stem, "data:%s;base64,%s" % (mime, base64.b64encode(f.read_bytes()).decode()))
    return out


def initiatives_for(con, ref_type, ref_id):
    return [r["name"] for r in con.execute(
        "SELECT i.name FROM mentions m JOIN initiatives i ON i.id=m.entity_id WHERE m.ref_type=? AND m.ref_id=? AND m.entity_type='initiative'",
        (ref_type, ref_id))]


HOST_LABEL = [("granola", "Granola"), ("teams.microsoft", "Teams"), ("outlook", "mail"), ("office", "mail"), ("slack", "Slack"),
              ("sharepoint", "SharePoint"), ("atlassian", "Jira"), ("acmecloud", "KB")]


JOIN_RX = re.compile(r"https://(?:teams\.microsoft\.com/(?:l/meetup-join|meet)/|[\w.-]*zoom\.us/j/|meet\.google\.com/)[^\s<>\"')\]]+")


def _agenda(p):
    from .relevance import agenda
    try:
        return agenda(p)[:4000]
    except Exception:
        return ""


def reply(p):
    """Sam's answer to the invite: accepted, tentative, not answered or organizer. Calendar.app records it; an event only the
    connector has seen says just showAs, where tentative covers both a tentative reply and none."""
    r = p.get("response")
    if r:
        return {"none": "not answered", "declined": "declined"}.get(r, r)
    if p.get("isOrganizer"):
        return "organizer"
    return "tentative" if p.get("showAs") == "tentative" else ""


def join_url(p):
    """The online-meeting join link: stored join_url, else the first Teams/Zoom/Meet link in the invitation text."""
    if p.get("join_url"):
        return p["join_url"]
    m = JOIN_RX.search((p.get("summary") or "") + " " + (p.get("location") or ""))
    return m.group(0) if m else ""


def link_label(label, url):
    """Name a source link by its system when the stored label is generic."""
    if label and label.lower() not in ("src", "source", "items"):
        return label
    u = (url or "").lower()
    return next((name for key, name in HOST_LABEL if key in u), "source")


def clip(text, n):
    """Plain-text excerpt: markdown emphasis removed, cut at a word boundary."""
    t = re.sub(r"\*\*|__|`", "", text or "").strip()
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0].rstrip(",;:·—-") + "…"


def bootstrap(con):
    now = datetime.now(TZ) if TZ else datetime.now()
    built = now.strftime("%a %d %b %Y, %H:%M %Z")
    built_iso = now.strftime("%Y-%m-%d")
    ini_rows = list(con.execute("SELECT * FROM initiatives WHERE COALESCE(active, 1)=1 ORDER BY weight DESC, name"))  # folded ones have active=0
    ini_names = [r["name"] for r in ini_rows if r["match_regex"]]

    # ---- commitments -> tasks
    tasks = []
    for r in con.execute("SELECT * FROM commitments ORDER BY CASE WHEN origin='Current' OR origin IS NULL THEN 0 ELSE 1 END, created_at DESC, id DESC"):
        links = [{"label": link_label(l["label"], l["url"]), "url": l["url"] or ""} for l in
                 con.execute("SELECT * FROM fact_sources WHERE fact_type='commitment' AND fact_id=?", (r["id"],)) if l["url"]]
        done = r["status"] in ("done", "dropped")
        group = "done" if done else {"owed_by_me": "active", "owed_to_me": "waiting", "someday": "someday"}.get(r["kind"], "active")
        tasks.append({"id": f"t-{r['id']}", "title": r["title"], "context": r["context"] or "", "links": links, "group": group, "kind": r["kind"],
                      "origin": r["origin"] or "Current", "person": r["counterparty"], "done": done, "due": r["due"],
                      "initiatives": initiatives_for(con, "commitment", r["id"])})

    # ---- meetings (+ docs)
    meetings, docs = [], []
    tdir = GRANOLA / "transcripts"
    by_short = {}
    for t in tdir.glob("*.md") if tdir.exists() else []:
        m = re.search(r"\[([A-Za-z0-9]{6})\]\.md$", t.name)
        if m:
            by_short[m.group(1)] = t
    import urllib.parse
    # how long each recording ran (its last transcript line), the end of a recording with no calendar event
    heard = {r[0]: r[1] for r in con.execute("SELECT meeting_id, MAX(last_t) FROM meeting_speakers GROUP BY meeting_id")}
    for r in con.execute("SELECT m.*, i.external_id, i.url AS granola, i.text AS granola_summary, e.subject AS cal_subject, e.url AS outlook "
                         "FROM meetings m JOIN items i ON i.id=m.note_item_id LEFT JOIN items e ON e.id=m.event_item_id ORDER BY m.starts_at DESC"):
        names = json.loads(r["attendees"] or "[]")
        names = [n for n in names if not profile.is_me(n)]
        t = by_short.get(r["external_id"][-6:])
        local_t = "../Granola%20Export/transcripts/" + urllib.parse.quote(t.name) if t else ""
        mid = f"m-{r['id']}"
        r = dict(r)
        if not (r["title"] or "").strip() or r["title"].strip().lower() in ("untitled", "new note"):
            r["title"] = r["cal_subject"] or "Untitled meeting"
        r["title"] = r["title"].strip()
        when = fmt(r["starts_at"], "%a %d %b %Y, %H:%M")
        md = f"# {r['title']}\n\n**{when}**  ·  with {', '.join(names) or 'no other attendees recorded'}  ·  {r['segments'] or 0} transcript segments  ·  [Granola]({r['granola']})"
        md += (f"  ·  [transcript](#/meetings/{mid})" if local_t else "") + "\n\n"   # the in-app transcript view, never the raw file
        if r["cal_subject"]:
            md += f"**Calendar:** {r['cal_subject']} · organiser {r['organizer'] or ''}" + (f" · [open in Outlook]({r['outlook']})" if r["outlook"] else "") + "\n\n"
        if r["status"] == "personal":
            md += "_Personal meeting; not analysed by design._\n"
        elif r["digest_md"]:   # the summary only: the triage checklist is internal (open items are extracted automatically)
            from .relevance import digest_summary
            md += digest_summary(r["digest_md"]) + "\n"
        else:
            if (r["granola_summary"] or "").strip():
                md += ("_Granola's own summary. The assistant has not analysed this meeting yet; the next full refresh will, "
                       "and Granola can mishear names and numbers._\n\n" + re.sub(r"(?m)^# ", "### ", r["granola_summary"].strip()) + "\n")
            else:
                md += "_No notes yet. The next full refresh analyses this meeting._\n"
        ini = initiatives_for(con, "meeting", r["id"]) or initiatives_mod.regex_names(con, (r["title"] or "") + " " + (r["digest_md"] or "")[:4000])
        _st = local(r["starts_at"]); _en = local(r["ends_at"]) if r["ends_at"] else None
        if not _en and _st and heard.get(r["id"]):
            _en = _st + timedelta(seconds=heard[r["id"]])
        meetings.append({"id": mid, "start": _st.strftime("%Y-%m-%dT%H:%M") if _st else "", "end": _en.strftime("%Y-%m-%dT%H:%M") if _en else "",
                         "event_item_id": r["event_item_id"], "match": r["match_quality"] or "", "date": fmt(r["starts_at"], "%Y-%m-%d"), "when": when, "title": r["title"], "with": names, "segments": r["segments"] or 0,
                         "status": r["status"], "granola": r["granola"] or "", "transcript": local_t, "calendar": r["cal_subject"] or "",
                         "organizer": r["organizer"] or "", "outlook": r["outlook"] or "", "initiatives": ini if r["status"] != "personal" else []})
        docs.append({"id": mid, "section": "Meetings", "title": r["title"], "path": "Granola Export/transcripts", "mtime": fmt(r["starts_at"], "%Y-%m-%d"),
                     "meta": {}, "md": md, "words": len(md.split())})

    # ---- people / initiatives (+ docs)
    people = []
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM people")}
    reports = {}
    for r in con.execute("SELECT manager_id, COUNT(*) n FROM people WHERE manager_id IS NOT NULL GROUP BY manager_id"):
        reports[r["manager_id"]] = r["n"]
    me = con.execute("SELECT id FROM people WHERE is_me=1").fetchone()
    my_org = set()
    if me:
        frontier = [me["id"]]
        while frontier:
            nxt = [r["id"] for r in con.execute(f"SELECT id FROM people WHERE manager_id IN ({','.join('?'*len(frontier))})", frontier)]
            my_org.update(nxt); frontier = nxt
    avatar_dir = db.db_path().parent / "avatars"
    def avatar_uri(fname):
        f = avatar_dir / fname if fname else None
        return ("data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()) if f and f.exists() else ""
    meet_counts = {}
    for r in con.execute("SELECT attendees FROM meetings"):
        for n in json.loads(r["attendees"] or "[]"):
            meet_counts[n] = meet_counts.get(n, 0) + 1
    # open items with each person (the register) and when Sam last had contact (mail, chat, meetings), by identity
    open_items, last_contact = {}, {}
    try:
        for r in con.execute("SELECT person_id, COUNT(*) FROM loops WHERE status='open' AND person_id IS NOT NULL GROUP BY person_id"):
            open_items[r[0]] = r[1]
        for r in con.execute("SELECT m.entity_id, MAX(i.ts) FROM mentions m JOIN items i ON i.id=m.ref_id WHERE m.ref_type='item' AND m.entity_type='person' "
                             "AND i.kind IN ('mail','sent','chat','note') AND i.noise=0 AND i.ts <= ? GROUP BY m.entity_id", (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),)):
            last_contact[r[0]] = r[1]
    except Exception:   # tables not there yet
        pass
    for r in con.execute("SELECT * FROM people ORDER BY name"):
        text = r["profile_md"] or ""
        threads = len(re.findall(r"^- \[ \]", text.split("## Open threads", 1)[1].split("\n## ", 1)[0], re.M)) if "## Open threads" in text else 0
        recent = re.search(r"## Recent interactions\n(.*?)(?:\n## |\Z)", text, re.S)
        last = ""
        if recent:
            lines = [l.strip()[2:] for l in recent.group(1).splitlines() if l.strip().startswith("- ")]
            last = legacy.clean(lines[0])[:160] if lines else ""
        orgname = con.execute("SELECT name FROM orgs WHERE id=?", (r["org_id"],)).fetchone() if r["org_id"] else None
        status = "me" if r["is_me"] else ("active" if r["org_source"] else ("external" if r["relationship"] and re.search(r"partner|CTS|contoso|Margie|investor|external", r["relationship"] or "", re.I) else "not on org chart"))
        pid = f"p-{r['id']}"
        people.append({"id": pid, "name": r["name"], "title": r["title"] or r["role"] or "", "role": r["role"] or "", "department": r["department"] or "",
                       "location": r["location"] or "", "manager": names.get(r["manager_id"], ""), "reports": reports.get(r["id"], 0),
                       "my_org": r["id"] in my_org, "status": status, "relationship": r["relationship"] or "", "updated": r["updated_at"] or "",
                       "threads": threads, "last": last, "open_items": open_items.get(r["id"], 0), "last_contact": last_contact.get(r["id"], ""), "meetings": meet_counts.get(r["name"], 0), "kb": r["kb_url"] or "", "has_profile": bool(text), "owns": "",
                       "avatar": avatar_uri(r["avatar"]) if "avatar" in r.keys() else "",
                       "affiliation": r["affiliation"] or "unclassified", "org": orgname["name"] if orgname else "", "affiliation_note": r["affiliation_note"] or "",
                       "directs": [names[x["id"]] for x in con.execute("SELECT id FROM people WHERE manager_id=? ORDER BY name", (r["id"],))],
                       "profile": re.sub(r"^# .*\n", "", text, count=1) if text else ""})
        if text or r["org_source"]:
            av = avatar_uri(r["avatar"]) if "avatar" in r.keys() else ""
            hdr = (f'<img src="{av}" alt="" style="width:72px;height:72px;border-radius:50%;object-fit:cover;float:right;margin:0 0 8px 12px">\n\n' if av else "") + f"# {r['name']}\n\n**{r['title'] or r['role'] or ''}** · {r['department'] or ''} · {r['location'] or ''}"
            hdr += (f" · reports to {names.get(r['manager_id'])}" if r["manager_id"] else "") + (f" · {reports.get(r['id'])} direct reports" if reports.get(r['id']) else "")
            hdr += (f" · [emery yates]({r['kb_url']})" if r["kb_url"] else "") + "\n\n"
            body = re.sub(r"^# .*\n", "", text, count=1) if text else "_No assistant profile yet; org data only._"
            docs.append({"id": pid, "section": "People", "title": r["name"], "path": f"memory/people/{r['name']}.md", "mtime": (r["updated_at"] or "")[:10],
                         "meta": {"title": r["title"] or ""}, "md": hdr + body, "words": len(body.split())})
    people.sort(key=lambda x: (x["status"] != "me", not x["my_org"], -x["threads"], x["name"]))
    projects = []
    for r in ini_rows:
        if not r["profile_md"]:
            continue
        text = r["profile_md"]
        stands = re.search(r"## Where it stands\n(.*?)(?:\n## |\Z)", text, re.S)
        pend = re.search(r"## Decisions pending\n(.*?)(?:\n## |\Z)", text, re.S)
        risks = re.search(r"## Risks\n(.*?)(?:\n## |\Z)", text, re.S)
        iid = f"i-{r['id']}"
        projects.append({"id": iid, "name": r["name"], "status": r["status"] or "", "owner": r["owner"] or "", "milestone": r["next_milestone"] or "",
                         "updated": r["updated_at"] or "", "stands": clip(legacy.clean(" ".join(l.strip("- ").strip() for l in (stands.group(1) if stands else "").splitlines() if l.strip())), 420),
                         "pending": len([l for l in (pend.group(1) if pend else "").splitlines() if l.strip().startswith("- ")]),
                         "risks": len([l for l in (risks.group(1) if risks else "").splitlines() if l.strip().startswith("- ")]), "weight": r["weight"]})
        docs.append({"id": iid, "section": "Initiatives", "title": r["name"], "path": f"memory/projects/{r['slug']}.md", "mtime": (r["updated_at"] or "")[:10],
                     "meta": {"status": r["status"] or "", "weight": str(r["weight"])}, "md": text, "words": len(text.split())})

    # ---- documents
    for r in con.execute("SELECT * FROM documents ORDER BY section, updated_at DESC"):
        docs.append({"id": r["id"], "section": r["section"], "title": r["title"], "path": r["path"] or "", "mtime": (r["updated_at"] or "")[:16].replace("T", " "),
                     "meta": json.loads(r["meta"] or "{}"), "md": r["body_md"], "words": len(r["body_md"].split())})

    # ---- brief (latest /brief run)
    brief = None
    run = con.execute("SELECT * FROM runs WHERE agent IN ('claude-code:/brief', 'assist:brief') AND output_md IS NOT NULL ORDER BY started_at DESC LIMIT 1").fetchone()
    if run:
        text = run["output_md"]
        actions = []
        m = re.search(r"```actions\s*\n([\s\S]*?)\n```", text)
        if m:   # proposed actions (JSON) travel separately and are not rendered as a section
            try:
                actions = [a for a in json.loads(m.group(1)) if isinstance(a, dict) and a.get("label")][:2]
            except ValueError:
                actions = []
            text = text.replace(m.group(0), "")
        title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "Brief")
        today = (re.search(r"^\*\*Today:\*\*\s*(.+)$", text, re.M) or [None, ""])[1]
        src = (re.search(r"^_Sources:(.+?)_\s*$", text, re.M) or [None, ""])[1]
        sections = {}
        for chunk in re.split(r"\n(?=## )", text):
            if chunk.startswith("## "):
                head, body = chunk.split("\n", 1) if "\n" in chunk else (chunk, "")
                sections[head[3:].strip()] = body.strip()
        inp = json.loads(run["input_summary"] or "{}")
        brief = {"title": title, "today": (today or "").strip(), "sources_line": (src or "").strip(), "sections": sections, "actions": actions,
                 "path": "briefs/" + inp.get("brief", (re.search(r"(\d{4}-\d{2}-\d{2})", title) or [None, run["started_at"][:10]])[1] + ".md") if not inp.get("brief") else "briefs/" + inp["brief"]}

    # ---- calendar
    events = []
    recorded = {r["event_item_id"]: f"m-{r['id']}" for r in con.execute("SELECT id, event_item_id FROM meetings WHERE event_item_id IS NOT NULL")}
    nowutc = datetime.now(timezone.utc)
    unrec = 0
    skipped: dict[str, int] = {}
    # Past meetings with attendees that still should not count as "not recorded". Calendar.app records Sam's own reply
    # (assist/applecal.py); for events only the connector has seen, showAs=tentative is the proxy for "invited, never accepted".
    virtual = re.compile(r"teams|zoom|webex|meet\.google|https?://(?!maps\.)", re.I)
    in_person = re.compile(r"\b(lunch|dinner|breakfast|drinks|in[- ]person|topgolf)\b", re.I)
    def skip_reason(p, st, en, loc):
        if p.get("isAllDay") or (en - st).total_seconds() >= 86400 or p.get("showAs") in ("free", "oof"):
            return "all-day / free"
        if in_person.search(p.get("subject") or "") or "maps." in loc or (loc and not virtual.search(loc)):
            return "in person"
        if reply(p) in ("tentative", "not answered"):
            return reply(p)
        return ""
    recorded_starts = {local(r["ts"]).strftime("%Y-%m-%dT%H:%M") for r in con.execute(
        "SELECT ts FROM items WHERE kind='event' AND id IN (SELECT event_item_id FROM meetings WHERE event_item_id IS NOT NULL)") if local(r["ts"])}
    missed_starts: set[str] = set()
    for r in con.execute("SELECT * FROM items WHERE kind='event' ORDER BY ts"):
        p = json.loads(r["payload"] or "{}")
        st, en = local(r["ts"]), local(p.get("end", r["ts"]))
        if not st or not en:
            continue
        att = [legacy.name_of(a) if hasattr(legacy, "name_of") else a for a in (p.get("attendees") or []) if a and not db.ME_ADDRESS.search(a)]
        att = [re.sub(r"@.*$", "", a).replace(".", " ").title() if "@" in a else a for a in att]
        past = en.astimezone(timezone.utc) < nowutc
        skip = ""
        if past and att and r["id"] not in recorded and not r["noise"]:
            slot = st.strftime("%Y-%m-%dT%H:%M")
            skip = skip_reason(p, st, en, r["thread"] or "") or ("clash with recorded" if slot in recorded_starts else "duplicate" if slot in missed_starts else "")
            if skip:
                skipped[skip] = skipped.get(skip, 0) + 1
            else:
                missed_starts.add(slot)
        is_unrec = past and bool(att) and r["id"] not in recorded and not r["noise"] and not skip
        unrec += is_unrec
        events.append({"id": p.get("id", r["external_id"]), "subject": r["subject"] or "(no subject)", "date": st.strftime("%Y-%m-%d"), "day": st.strftime("%a %d %b"),
                       "time": st.strftime("%H:%M") + "–" + en.strftime("%H:%M"), "minutes": int((en - st).total_seconds() // 60),
                       "organizer": re.sub(r"@.*$", "", p.get("organizer") or "").replace(".", " ").title(), "attendees": att, "cancelled": bool(r["noise"]),
                       "mine": bool(p.get("isOrganizer")), "webLink": r["url"] or "", "location": r["thread"] or "", "recorded": r["id"] in recorded, "meeting_id": recorded.get(r["id"], ""),
                       "start": st.strftime("%Y-%m-%dT%H:%M"), "end": en.strftime("%Y-%m-%dT%H:%M"), "join_url": join_url(p), "all_day": (en - st).total_seconds() >= 86400 and st.strftime("%H:%M") == "00:00",
                       "unrecorded": is_unrec, "skip": skip, "showAs": p.get("showAs", ""), "reply": reply(p),
                       "agenda": _agenda(p)})   # the invite's own text, without the Teams join block and dial-in details
    cal_pull = con.execute("SELECT MAX(finished_at) FROM pulls WHERE source_id='calendar'").fetchone()[0] or ""
    notes_total = con.execute("SELECT COUNT(*) FROM meetings").fetchone()[0]
    matched = con.execute("SELECT COUNT(*) FROM meetings WHERE event_item_id IS NOT NULL").fetchone()[0]
    calendar = {"events": events, "pulled": cal_pull,
                "stats": {"notes": notes_total, "events": len(events), "matched": matched, "unmatched_notes": notes_total - matched,
                          "unrecorded_meetings_with_attendees": unrec, "unrecorded_skipped": skipped, "tolerance_minutes": 12}}

    # ---- sources, coverage rows (one per pull window), streams (items per pull)
    src_rows = list(con.execute("SELECT * FROM sources ORDER BY sort, id"))
    systems, cov_rows, streams = {}, [], {}
    for s in src_rows:
        sysid = s["system"]
        if sysid not in systems:
            systems[sysid] = {"id": sysid, "name": s["name"].split(" · ")[0], "vendor": s["vendor"], "color": s["color"], "mono": s["mono"], "logo": s["logo"],
                              "kind": s["kind"], "how": s["how"], "auth": s["auth"], "connect": s["connect"], "keys": [sysid], "streams": []}
        count = con.execute("SELECT COUNT(*) FROM items WHERE source_id=?", (s["id"],)).fetchone()[0]
        source_key = "meetings" if s["id"] == "granola" else ("calendar" if s["id"] == "calendar" else f"snap:{s['id']}")
        systems[sysid]["streams"].append({"id": s["id"], "name": STREAM_LABEL.get(s["id"], s["name"]), "source": source_key if count or s["id"] in ("granola", "calendar") else "none"})
        pulls = list(con.execute("SELECT * FROM pulls WHERE source_id=? ORDER BY finished_at DESC, id DESC", (s["id"],)))
        for p in pulls:
            cov_rows.append({"key": sysid, "source": p["note"] or f"{s['name']} ({(p['window_from'] or '')[:10]} – {(p['window_to'] or '')[:10]})",
                             "available": p["available"] if p["available"] is not None else "", "digested": p["pulled"] if p["pulled"] is not None else "",
                             "analysed": p["pulled"] if p["pulled"] is not None else "", "health": s["health"] or "ok",
                             "last_seen": (p["window_to"] or p["finished_at"] or "")[:10], "note": s["note"] or ""})
        if s["id"] not in ("granola", "calendar"):
            tables = []
            for p in pulls:
                rows = list(con.execute("SELECT * FROM items WHERE source_id=? AND pull_id=? ORDER BY ts DESC", (s["id"], p["id"])))
                if not rows:
                    continue
                tables.append({"file": "", "doc": "", "title": p["note"] or s["name"], "mtime": (p["finished_at"] or "")[:16].replace("T", " "),
                               "heading": f"{len(rows)} items", "headers": ["When", "From", "Subject", "Gist", "Where", "Noise"],
                               "rows": [{"c": [fmt(r["ts"], "%d %b %Y" if s["id"] == "acme-kb" else "%d %b %H:%M"), r["from_name"] or "", r["subject"] or "",
                                               ((r["text"] or "").split("\n", 1)[0][:200] if s["id"] == "acme-kb" else (r["text"] or "")), r["thread"] or "", "noise" if r["noise"] else ""],
                                         "l": ([{"label": "open", "url": r["url"]}] if r["url"] else [])} for r in rows]})
            if tables:
                streams[s["id"]] = tables
    from . import gaps as gap_notes   # the gaps a pull reported in the last few days (assist/gaps.py)
    gaps = gap_notes.current(con)
    coverage = {"sources": cov_rows, "gaps": gaps, "updated": built,
                "freshness_rule": "ok = last seen within 2 days of the build; stale = older; broken = the source cannot be read; capped = read, but a search limit was hit"}
    pulls_list = [{"id": d["id"], "title": d["title"], "mtime": d["mtime"], "words": d["words"]} for d in docs if d["section"] in ("Pulls", "Analyses")]
    last_run = con.execute("SELECT agent, finished_at, output_json FROM runs ORDER BY id DESC LIMIT 5").fetchall()
    sync = {"digested": con.execute("SELECT COUNT(*) FROM meetings WHERE status IN ('digested','analysed')").fetchone()[0],
            "last_run": last_run[0]["finished_at"] if last_run else None,
            "log": "\n".join(f"{r['finished_at'] or ''}  {r['agent']}  {r['output_json'] or ''}" for r in last_run)}
    return {"built": built, "built_iso": built_iso, "brief": brief, "tasks": tasks, "meetings": meetings, "people": people,
            "projects": projects, "coverage": coverage, "pulls": pulls_list, "sync": sync, "docs": docs, "initiatives": ini_names,
            "calendar": calendar, "logos": logos(), "sources": list(systems.values()), "streams": streams, "db": str(db.db_path())}
