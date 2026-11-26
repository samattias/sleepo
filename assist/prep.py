"""Meeting prep: which upcoming meetings need a brief, and everything the database knows that is relevant to one.

  assist prep-upcoming [--days N] [--missing]   upcoming meetings worth preparing (default: today + 2 working days)
  assist prep-context <event_id>                the context pack /prep writes a brief from (markdown, with sources)

Deterministic plumbing only: this module gathers and ranks, the /prep skill (Claude) judges and writes.
Briefs are stored as documents in section "Prep" with meta.event_id, so the UI can pair them with calendar events.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import db
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from . import profile

try:
    from zoneinfo import ZoneInfo
    TZ = profile.zone()
except Exception:  # pragma: no cover
    TZ = timezone.utc

PERSONAL = profile.PERSONAL   # the user's personal meetings are out of scope (the profile)
SAM = db.ME_ADDRESS   # the one definition, assist/db.py
CANCELLED = re.compile(r"^\s*(cancel+ed\s*:|キャンセル済み)", re.I)   # a cancellation re-sent under the title, isCancelled not set
# travel and logistics on a trip itinerary (28 Oct 2026: the work trip's "Head to the lodging" and "Free" slots got briefs)
LOGISTICS = re.compile(r"^\s*(head to|move to|check[- ]?(in|out)\b|free\s*$|waiting time|national holiday|sightseeing|flight\b|"
                       r"train\b|transfer\b|travel\b|block\s*:)|\bsightseeing\b|\bmeeting place\b", re.I)


def _utc(s):
    s = (s or "").replace("Z", "")[:19]
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if s else None


def _name(addr):
    return re.sub(r"@.*$", "", addr).replace(".", " ").replace("_", " ").title() if "@" in (addr or "") else (addr or "")


def _working_day_end(days):
    d = datetime.now(TZ).date()
    left = days
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return datetime.combine(d, datetime.max.time()).replace(tzinfo=TZ).astimezone(timezone.utc)


def _stale(con, brief, attendee_addresses):
    """A brief is out of date when the people in the meeting wrote, shared or met since it was written (mail, chat incl. shared
    files, meeting notes), when it is more than 18 hours old, or when it was written by an earlier version of the rules."""
    from .prepgen import PROMPT_VERSION
    at = brief.get("updated_at") or ""
    if not at or at < (datetime.now(timezone.utc) - timedelta(hours=18)).strftime("%Y-%m-%dT%H:%M:%SZ"):
        return True
    if brief.get("prompt_version") != PROMPT_VERSION:
        return True
    ids = {pid for pid in (db.resolve_person(con, a) or db.resolve_person(con, _name(a)) for a in attendee_addresses) if pid}
    if not ids:
        return False
    q = (f"SELECT 1 FROM mentions m JOIN items i ON i.id=m.ref_id WHERE m.ref_type='item' AND m.entity_type='person' "
         f"AND m.entity_id IN ({','.join('?' * len(ids))}) AND i.kind IN ('mail','sent','chat','note') AND i.noise=0 "
         f"AND (i.ts > ? OR i.pulled_at > ?) LIMIT 1")
    return con.execute(q, [*ids, at, at]).fetchone() is not None


def _briefs(con):
    out = {}
    for r in con.execute("SELECT id, title, meta, updated_at FROM documents WHERE section='Prep'"):
        m = json.loads(r["meta"] or "{}")
        if m.get("event_id"):
            prev = out.get(m["event_id"])
            if not prev or (r["updated_at"] or "") > prev["updated_at"]:
                out[m["event_id"]] = {"doc_id": r["id"], "title": r["title"], "updated_at": r["updated_at"] or "", "generated": m.get("generated", ""),
                                      "prompt_version": m.get("prompt_version", "")}
    return out


def _join(p):
    from .views import join_url   # Teams / Zoom / Meet link: stored join_url, else the first one in the invitation
    try:
        return join_url(p) or ""
    except Exception:
        return ""


def upcoming(con, days=2, missing=False):
    """Meetings from now until the end of `days` working days that are worth a brief."""
    now, until = datetime.now(timezone.utc), _working_day_end(days)
    briefs = _briefs(con)
    seen, out = set(), []
    for r in con.execute("SELECT * FROM items WHERE kind='event' AND ts >= ? AND ts <= ? ORDER BY ts",
                         ((now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), until.strftime("%Y-%m-%dT%H:%M:%SZ"))):
        p = json.loads(r["payload"] or "{}")
        st, en = _utc(p.get("start") or r["ts"]), _utc(p.get("end"))
        if not st or not en or en < now:
            continue
        subject = (p.get("subject") or r["subject"] or "").strip()
        att = [a for a in (p.get("attendees") or []) if a and not SAM.search(a)]
        org = p.get("organizer") or ""
        why_not = ("cancelled" if p.get("isCancelled") or CANCELLED.match(subject) else "all-day / free" if p.get("isAllDay") or p.get("showAs") in ("free", "oof") or (en - st).total_seconds() >= 86400
                   else "personal" if PERSONAL.search(subject) else "travel" if LOGISTICS.search(subject)
                   else "no one else invited" if not att and (not org or SAM.search(org)) else "")
        if why_not or not subject:
            continue
        key = (subject.lower(), st.strftime("%Y-%m-%dT%H:%M"))   # recurring series can repeat in the pull
        if key in seen:
            continue
        seen.add(key)
        eid = p.get("id") or r["external_id"]
        b = briefs.get(eid)
        if missing and b and not (missing == "stale" and _stale(con, b, att)):
            continue
        out.append({"event_id": eid, "item_id": r["id"], "subject": subject, "start": st.isoformat(), "end": en.isoformat(),
                    "local": st.astimezone(TZ).strftime("%a %d %b, %H:%M") + "–" + en.astimezone(TZ).strftime("%H:%M"),
                    "attendees": [_name(a) for a in att], "attendee_addresses": att, "organizer": _name(org),
                    "location": p.get("location") or r["thread"] or "", "web_link": p.get("webLink") or r["url"] or "",
                    "join_url": _join(p), "brief": b})
    return out


# ---------------------------------------------------------------- context pack
def _person(con, who):
    pid = db.resolve_person(con, who) or db.resolve_person(con, _name(who))
    return con.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone() if pid else None


def _clip(t, n):
    t = re.sub(r"\s+\n", "\n", (t or "").strip())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


# ---------------------------------------------------------------- what kind of meeting it is (Sam, 28 Oct 2026)
# A brief follows the meeting's purpose and Sam's part in it: a 1:1 with someone in his team is their update, what they
# owe, his asks and follow-ups; the ELT is his update (last week, this week); a large session needs three lines.
# prepgen.SHAPES holds one brief shape per kind.
KINDS = {
    "team_1on1": "1:1 with someone in your team",
    "manager_1on1": "1:1 with your manager",
    "peer_1on1": "1:1 with a colleague",
    "external": f"meeting with people outside {USER.company}",
    "you_lead": "a meeting you run",
    "team_leads": "a meeting your team runs",
    "forum": "leadership forum: you give the product update",
    "contributor": "a meeting someone else runs: you contribute",
    "large": "a large session: you mostly listen",
    "social": "a social occasion",
}
FORUM = re.compile(r"\b(ELT|SLT|exec\w*|leadership|staff meeting|QBR|board meeting)\b", re.I)
SOCIAL = re.compile(r"^\s*(dinner|lunch|breakfast|drinks|reception|party|coffee)\b", re.I)
OUTSIDE = re.compile(r"^\s*visit\b|-(san|sama)\b|\bpartner meeting\b|\binterview\b|\bcustomer\b", re.I)   # their people are not on the invite
LARGE = 15


def classify(subject, relations, organiser):
    """The kind of meeting (a KINDS key). relations: how each attendee other than Sam relates to him, 'manager' | 'team' |
    'internal' | 'external'; organiser: 'me' or one of those."""
    n = len(relations)
    if SOCIAL.match(subject or ""):
        return "social"
    if n >= LARGE and organiser != "me":
        return "large"
    if "external" in relations or OUTSIDE.search(subject or ""):
        return "external"
    if n == 1:
        return {"manager": "manager_1on1", "team": "team_1on1"}.get(relations[0], "peer_1on1")
    if organiser == "me":
        return "you_lead"
    if FORUM.search(subject or ""):
        return "forum"
    return "team_leads" if organiser == "team" else "contributor"


def _org_ids(con):
    """(Sam's person id, his manager's, everyone in his organisation at any depth)."""
    me = con.execute("SELECT id, manager_id FROM people WHERE is_me=1 ORDER BY id LIMIT 1").fetchone()
    if not me:
        return None, None, set()
    team, todo = set(), [me["id"]]
    while todo:
        for r in con.execute("SELECT id FROM people WHERE manager_id=? AND COALESCE(active, 1)=1", (todo.pop(),)):
            if r["id"] not in team:
                team.add(r["id"])
                todo.append(r["id"])
    return me["id"], me["manager_id"], team


def _relation(con, who, org):
    from . import relevance as R
    from .entities import INTERNAL, registrable
    if SAM.search(who or ""):
        return "me"
    me, manager, team = org
    p = R.resolve(con, who)
    if p and p["id"] == manager:
        return "manager"
    if p and p["id"] in team:
        return "team"
    if "@" in (who or ""):
        return "internal" if registrable(who.split("@", 1)[1].lower()) in INTERNAL else "external"
    return "internal" if p else "external"


def _part(con, earlier):
    """Sam's part in earlier meetings of this series (relevance.previous_occurrences: a recording counts only when it shares
    someone with the invite): how many in 90 days, his share of the words, who spoke most."""
    since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = [m["id"] for m in earlier if (m["starts_at"] or "") >= since]
    if not ms:
        return []
    q = ",".join("?" * len(ms))
    mine = [r[0] for r in con.execute(f"SELECT share FROM meeting_speakers WHERE is_me=1 AND meeting_id IN ({q})", ms) if r[0] is not None]
    top = con.execute(f"SELECT name, is_me, COUNT(*) n FROM (SELECT meeting_id, name, is_me, MAX(share) FROM meeting_speakers WHERE meeting_id IN ({q}) "
                      f"GROUP BY meeting_id) GROUP BY name ORDER BY n DESC LIMIT 1", ms).fetchone()
    out = [f"- Held {'once' if len(ms) == 1 else f'{len(ms)} times'} in the last 90 days."]
    if mine:
        out.append(f"- You spoke {round(100 * sum(mine) / len(mine))}% of the words on average"
                   + (f"; {'you' if top['is_me'] else top['name']} spoke most in {top['n']} of {len(mine)}" if top and top["n"] else "") + ".")
    return out


def meeting_type(con, ev, organiser_address="", earlier=()):
    """(kind, markdown lines for the pack): the kind of meeting and the evidence for it; earlier: its earlier occurrences."""
    org = _org_ids(con)
    rel = [(a, _relation(con, a, org)) for a in (ev["attendee_addresses"] or ev["attendees"])]
    rel = [(a, r) for a, r in rel if r != "me"]
    organiser = _relation(con, organiser_address, org) if organiser_address else "internal"
    kind = classify(ev["subject"], [r for _, r in rel], organiser)
    words = {"manager": "your manager", "team": "in your team", "internal": "Acme", "external": f"outside {USER.company}"}
    who = "; ".join(f"{_name(a) if '@' in a else a} ({words[r]})" for a, r in rel[:12]) + (f"; {len(rel) - 12} more" if len(rel) > 12 else "")
    L = ["## This meeting (what kind it is: write the brief in its shape)", f"**meeting_type:** {kind} · {KINDS[kind]}",
         f"- Organised by {'you' if organiser == 'me' else _name(organiser_address) or 'someone else'} · {len(rel)} others invited: {who or 'nobody'}"]
    L += _part(con, earlier)
    return kind, L + [""]


def _week_lines(con, start, since):
    """For Sam's own update (the ELT, his 1:1 with his manager): what he did since `since`, where each bet stands, and his
    focus in the meeting's week (open tasks, meetings ahead)."""
    from . import initiatives as ini, tasks
    L = [f"## Your week (for your update: what you did since {since[:10]}, where each bet stands, what is ahead)",
         f"Anything about individuals (roles, performance, departures, pay) is private: keep it out of what {USER.first} says to a group."]
    hist = con.execute("SELECT DISTINCT h.id, h.title, h.done_when, i.name AS bet, h.area FROM history_tasks h LEFT JOIN initiatives i ON i.id=h.initiative_id "
                       "JOIN history_actions a ON a.task_id=h.id WHERE h.status='done' AND a.ts >= ? AND a.ts < ? ORDER BY h.finished_at DESC LIMIT 14",
                       (since, start)).fetchall()
    L.append("### What you did (Tasks › History, rebuilt from your sent mail, messages, meetings and documents; whole weeks only)")
    L += [f"- {h['title']} · {h['bet'] or h['area'] or 'not filed'}" + (f" · towards: {_clip(h['done_when'], 140)}" if h["done_when"] else "") for h in hist] or ["- none built for these days yet"]
    built = con.execute("SELECT MAX(week) FROM history_weeks WHERE status='ok'").fetchone()[0]
    if built:
        after = (datetime.fromisoformat(built) + timedelta(days=7)).strftime("%Y-%m-%d")
        held = con.execute("SELECT DISTINCT m.title, substr(m.starts_at, 1, 10) d FROM meetings m LEFT JOIN items n ON n.id=m.note_item_id "
                           "WHERE m.status != 'personal' AND COALESCE(n.retention, '') != 'hr_legal' AND m.starts_at >= ? AND m.starts_at >= ? "
                           "AND m.starts_at < ? ORDER BY m.starts_at LIMIT 15", (after, since, start)).fetchall()   # people/HR notes stay out
        if held:
            L.append(f"### Meetings you held from {after} (not in the history yet)")
            L += [f"- {m['d']} · {_clip(m['title'], 90)}" for m in held]
    done = con.execute("SELECT title, closed_at FROM tasks WHERE status='done' AND closed_at >= ? AND closed_at < ? ORDER BY closed_at DESC LIMIT 10",
                       (since, start)).fetchall()
    if done:
        L.append("### Tasks and steps you closed")
        L += [f"- {d['closed_at'][:10]} · {_clip(d['title'], 120)}" for d in done]
    L.append("### Where each bet stands (initiative pages)")
    for r in ini.active(con):
        s = ini._summary(con, r)
        u = s["last_update"] or s["draft"]
        L.append(f"- {r['name']} ({s['health'] or 'no status'})" + (f": {_clip(u['status'], 320)} Next: {_clip(u['next'], 160)}" if u else ""))
    try:
        open_t = [t for t in tasks.listing(con, closed_days=0, write=False)["tasks"] if t["status"] == "open"][:6]
    except Exception:
        open_t = []
    if open_t:
        L.append("### Your open tasks, most important first")
        L += [f"- {tasks.line(t, 'T' + str(t['id']))}" for t in open_t]
    st = _utc(start) or datetime.now(timezone.utc)
    week_end = (st.astimezone(TZ) + timedelta(days=7 - st.astimezone(TZ).weekday())).replace(hour=0, minute=0, second=0).astimezone(timezone.utc)
    ahead = []
    for r in con.execute("SELECT subject, ts, payload FROM items WHERE kind='event' AND ts > ? AND ts < ? ORDER BY ts",
                         (st.strftime("%Y-%m-%dT%H:%M"), week_end.strftime("%Y-%m-%dT%H:%M"))):
        p = json.loads(r["payload"] or "{}")
        subj = (p.get("subject") or r["subject"] or "").strip()
        if (subj and not p.get("isCancelled") and not CANCELLED.match(subj) and not LOGISTICS.search(subj) and not PERSONAL.search(subj)
                and not SOCIAL.match(subj) and [a for a in p.get("attendees") or [] if not SAM.search(a)] and subj not in [a[1] for a in ahead]):
            ahead.append(((_utc(p.get("start") or r["ts"]) or st).astimezone(TZ).strftime("%a %d %b %H:%M"), subj))
    if ahead:
        L.append("### Meetings ahead this week")
        L += [f"- {d} · {_clip(s, 90)}" for d, s in ahead[:16]]
    return L + [""]


def context(con, event_id, info=None):
    """The context pack (markdown). info, when given, is filled with the meeting's kind (KINDS), decided here in code."""
    ev = next((e for e in upcoming(con, days=10) if e["event_id"] == event_id or str(e["item_id"]) == str(event_id)), None)
    if not ev:
        r = con.execute("SELECT * FROM items WHERE kind='event' AND (external_id=? OR payload LIKE ?)", (event_id, f'%"{event_id}"%')).fetchone()
        if not r:
            return f"No calendar event {event_id} in the database."
        p = json.loads(r["payload"] or "{}")
        ev = {"event_id": event_id, "item_id": r["id"], "subject": p.get("subject") or r["subject"] or "", "local": r["ts"],
              "attendees": [_name(a) for a in p.get("attendees") or [] if not SAM.search(a)], "attendee_addresses": [a for a in p.get("attendees") or [] if not SAM.search(a)],
              "organizer": _name(p.get("organizer") or ""), "location": p.get("location") or "", "web_link": p.get("webLink") or "", "brief": None}
    L = [f"# Context pack · {ev['subject']}", f"**When:** {ev['local']} · **Organiser:** {ev['organizer'] or '—'} · **Where:** {ev['location'] or '—'}"
         + (f" · [Outlook]({ev['web_link']})" if ev["web_link"] else ""), f"**event_id:** {ev['event_id']}", ""]
    from . import relevance as R
    _ev_row = con.execute("SELECT ts, payload FROM items WHERE id=?", (ev["item_id"],)).fetchone()
    _payload = json.loads(_ev_row["payload"] or "{}") if _ev_row else {}
    _agenda = R.agenda(_payload)
    _start = ev.get("start") or (_ev_row["ts"] if _ev_row else "")
    L.append("## The invite (the organiser's own words: start the brief from this purpose)")
    L.append(_agenda if _agenda else "- no description in the invite")
    L.append("")
    _type_at = len(L)   # "This meeting" goes here, once the people are known (below)

    # people in the room
    people, names = [], set()
    for a in ev["attendee_addresses"] or ev["attendees"]:
        p = R.resolve(con, a)
        if p and p["id"] not in [x["id"] for x in people]:
            people.append(p)
            names.update({p["name"], p["name"].split()[0]})
        elif not p:
            names.add(_name(a))
    L.append(f"## Who's in the room ({len(ev['attendees'])})")
    for p in people:
        org = con.execute("SELECT name FROM orgs WHERE id=?", (p["org_id"],)).fetchone() if p["org_id"] else None
        mgr = con.execute("SELECT name FROM people WHERE id=?", (p["manager_id"],)).fetchone() if p["manager_id"] else None
        L.append(f"### {p['name']} — {p['title'] or p['role'] or ''}" + (f" · {p['affiliation']}" if p["affiliation"] else "") + (f" · {org['name']}" if org else "")
                 + (f" · reports to {mgr['name']}" if mgr else ""))
        if p["profile_md"]:
            L.append(re.sub(r"(?m)^#{1,3} ", "#### ", _clip(re.sub(r"^# .*\n", "", p["profile_md"]), 1600)))
    unknown = [a for a in ev["attendees"] if not any(a.split()[0].lower() in x["name"].lower() for x in people)]
    if unknown:
        L.append("Not in the people database: " + ", ".join(unknown))
    L.append("")

    # match by identity: full names always, a first name only when nobody else in the company has it (4 Daniels, 2 Scotts)
    matcher = R.Matcher(con, people)
    first = set(matcher.first)
    mentions = matcher.text
    kind, _type_lines = meeting_type(con, ev, _payload.get("organizer") or "",
                                     R.previous_occurrences(con, ev["subject"], _start or "9999", matcher, limit=30))
    L[_type_at:_type_at] = _type_lines
    if info is not None:
        info.update(kind=kind, people=[p["id"] for p in people], topic=f"{ev['subject']} {_agenda}"[:2000])

    # related bets
    bets = []
    for i in con.execute("SELECT name, weight, match_regex, next_milestone FROM initiatives WHERE match_regex IS NOT NULL ORDER BY weight DESC"):
        try:
            if re.search(i["match_regex"], ev["subject"]):
                bets.append(i)
        except re.error:
            pass
    if bets:
        L.append("## Bets this touches")
        L += [f"- {b['name']} (weight {b['weight']})" + (f" · next: {b['next_milestone']}" if b["next_milestone"] else "") for b in bets]
        L.append("")

    # where each bet stands (initiative pages: health, latest weekly update, open counts)
    try:
        from . import initiatives as _ini
        _lines = _ini.context_for(con, " ".join([ev["subject"], _agenda] + list(ev.get("attendees") or [])), max_n=3)
        if _lines:
            L.append("## Initiatives this meeting touches (where each bet stands)")
            L += [f"- {x}" for x in (_lines if isinstance(_lines, list) else str(_lines).splitlines()) if str(x).strip()]
            L.append("")
    except Exception:
        pass

    # open items: one list, from the register (assist/loops.py) that the daily brief and Actions use
    subj_words = ({w for w in re.findall(r"[A-Za-z]{4,}", ev["subject"].lower())} - {"with", "sync", "meeting", "call", "review", "weekly", "update"}
                  - set(R.first_name_counts(con)))   # a first name in the title is a person, not a topic
    try:
        from . import loops
        pids = {p["id"] for p in people}
        open_items = [loops._row(con, l) for l in con.execute("SELECT * FROM loops WHERE status='open' ORDER BY origin_at")
                      if l["person_id"] in pids or mentions(" ".join(str(l[k] or "") for k in ("title", "detail", "counterpart")))
                      or (l["kind"] == "decision" and any(w in (l["title"] or "").lower() for w in subj_words))]
        L.append("## Open items with these people or on this topic (DECIDE OR DROP = past its age limit; LIKELY DONE = evidence suggests "
                 "it was done: check the communication below)")
        L += [loops.line(l, f"L{l['id']}") + " " + " ".join(f"[{x.get('label') or 'src'}]({x['url']})" for x in (l.get("links") or [])[:2] if x.get("url"))
              for l in open_items[:30]] or ["- none"]
        L.append("")
        from . import tasks
        L += tasks.block(con, pids)
    except Exception as e:
        L += [f"- open items could not be read ({e})", ""]

    # earlier occurrences of this same meeting: what was left open last time matters most
    prev = R.previous_occurrences(con, ev["subject"], _start or "9999", matcher)
    if prev:
        L.append("## Earlier occurrences of this same meeting (what was left open last time matters most)")
        for m in prev:
            u = con.execute("SELECT url FROM items WHERE id=?", (m["note_item_id"],)).fetchone()
            L.append(f"### {m['title']} · {(m['starts_at'] or '')[:10]}" + (f" · [Granola]({u['url']})" if u and u["url"] else ""))
            L.append(re.sub(r"(?m)^#{1,4} ", "#### ", _clip(R.meeting_notes(con, m), 1400)) or "_no notes_")
        L.append("")
    if kind in ("forum", "manager_1on1"):   # Sam gives his update: since the last one (a week back, two at most)
        st = _utc(_start) or datetime.now(timezone.utc)
        last = _utc(prev[0]["starts_at"]) if prev else None
        since = last if last and last >= st - timedelta(days=14) else st - timedelta(days=7)
        L += _week_lines(con, st.strftime("%Y-%m-%dT%H:%M:%SZ"), since.strftime("%Y-%m-%dT%H:%M:%SZ"))

    addrs = {a.lower() for a in ev["attendee_addresses"] if "@" in a}
    for p in people:
        addrs |= {r["alias"] for r in con.execute("SELECT alias FROM people_aliases WHERE person_id=? AND alias LIKE '%@%'", (p["id"],))}
    L.append("## Email addresses (for email and Teams actions)")
    book = {}
    for p in people:
        mails = [r["alias"] for r in con.execute("SELECT alias FROM people_aliases WHERE person_id=? AND alias LIKE '%@%'", (p["id"],))]
        if mails:
            book[p["name"]] = mails[0]
    for a in ev["attendee_addresses"]:
        if "@" in a and a.lower() not in {v.lower() for v in book.values()}:
            book[_name(a)] = a
    L += [f"- {n}: {e}" for n, e in book.items()] or ["- none known"]
    L.append("")

    # everything Sam and each person said to each other recently: meetings, mail both ways, Teams, Slack
    from . import prep_history
    known = {r["alias"].lower() for p in people for r in con.execute("SELECT alias FROM people_aliases WHERE person_id=?", (p["id"],))}
    extra = [a for a in ev["attendee_addresses"] if "@" in a and a.lower() not in known and not R.resolve(con, a)]
    L += prep_history.history(con, people, extra, _start or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              exclude_meetings={m["id"] for m in prev})
    L.append("## Related by topic (search across mail, chat, meetings, transcripts, and documents, whoever wrote them)")
    _kw = R.keywords(ev["subject"], _agenda, con=con)
    L += (R.topic_lines(con, _kw, limit=10) or ["- nothing found"]) if _kw else ["- no topic in the title or invite (a people meeting): rely on the sections above"]
    L.append("")
    # external organisations in the room: Salesforce deals and last contact (company and deal data only)
    try:
        from . import entities
        orgs = []
        for a in ev["attendee_addresses"] or []:
            oid = entities.org_for_domain(con, entities.domain_of(a), {}, create=False)
            if oid and oid not in orgs:
                orgs.append(oid)
        if orgs:
            L.append("## Organisations in the room")
            for oid in orgs:
                o = entities.org_summary(con, oid)
                opps = [x for x in o["opportunities"] if x.get("is_open") is not False]
                L.append(f"### {o['name']} ({o['kind']}) · last mail/meeting contact {(o['last_activity'] or 'none on record')[:10]}")
                L += [f"- Deal: {x.get('sale_type') or ''} · {x.get('stage') or ''} · {x.get('currency') or ''} {x.get('acv') or 0:,.0f} ACV · closes {x.get('close_date') or '—'}"
                      for x in opps[:6]] or ["- no open Salesforce deals"]
                for t in entities.timeline(con, "org", oid, limit=6):
                    L.append(f"- {t['ts'][:10]} · {t['label']} · {t['title'][:120]}")
            L.append("")
    except Exception:
        pass
    from . import prep_docs
    L += prep_docs.links_section(prep_docs.shared_links(con, addrs, first, mentions))
    L += prep_docs.section(prep_docs.find(con, ev["subject"], addrs, first, mentions))
    L.append("## Existing brief")
    L.append(f"- {ev['brief']['doc_id']} (updated {ev['brief']['updated_at'][:16]})" if ev.get("brief") else "- none yet")
    return "\n".join(L)
