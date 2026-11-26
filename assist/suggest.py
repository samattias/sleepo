"""Suggested questions for Ask SleePO (the chat's welcome screen): the questions Sam keeps asking, sharpened with what is
true right now (the next meeting, the last one, who has the most open with him, what is pending, what closes this month).

Read only, deterministic and fast (no model): the counts come from the tables the app shows (loops, todo, calendar
events, meetings, initiatives, Salesforce deals), so a hint never disagrees with the page it points at. Each suggestion
has the question sent to the chat (`prompt`), a short `label`, why it is suggested now (`hint`, with the number behind
it), a `group` and an `icon` key; `score` orders them, so the ones with the most behind them come first. Page-specific
suggestions (this person, this meeting) are made in the app, which knows the page.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from . import profile

from . import pipeline
from .person_page import _shown

LONDON = profile.zone()
PERSONAL = profile.PERSONAL   # the user's personal meetings are out of scope (the profile)
SAM = db.ME_ADDRESS   # the one definition, assist/db.py
ONE_TO_ONE = profile.ONE_TO_ONE   # "Sam <> Bryn 1:1" → "Bryn" (the user's first name: assist/profile.py)
GROUPS = [("today", "Today"), ("people", "People"), ("open", "Open items"), ("numbers", "Numbers and bets"), ("reflect", "Reflect")]


def _utc(s):
    s = (s or "").replace("Z", "")[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _when(dt, now):
    """"today 14:00", "tomorrow 09:30", "Thu 15 Oct 14:00" in London time."""
    d, n = dt.astimezone(LONDON), now.astimezone(LONDON)
    day = "today" if d.date() == n.date() else "tomorrow" if d.date() == n.date() + timedelta(days=1) else d.strftime("%a %-d %b")
    return f"{day} {d:%H:%M}"


def _clip(s, n=46):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def build(con, now=None):
    now = now or datetime.now(timezone.utc)
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []

    def add(group, icon, label, prompt, hint=None, score=0, key=None):
        out.append({"id": key or re.sub(r"\W+", "-", label.lower()).strip("-")[:48], "group": group, "icon": icon, "label": label,
                    "prompt": prompt, "hint": hint, "score": score})

    names = {a.lower(): n for a, n in con.execute("SELECT a.alias, p.name FROM people_aliases a JOIN people p ON p.id=a.person_id WHERE a.alias LIKE '%@%'")}

    # ---- today: focus, the next meeting, the last one
    actions = con.execute("SELECT COUNT(*) FROM todo WHERE status='open'").fetchone()[0]
    add("today", "focus", "What should I focus on today?", "What should I focus on today, and why? Rank the few things that matter most.",
        f"{_plural(actions, 'action')} ranked" if actions else None, 90, "focus")
    for r in con.execute("SELECT ts, payload FROM items WHERE kind='event' AND noise=0 AND ts >= ? AND ts <= ? ORDER BY ts",
                         (iso(now - timedelta(minutes=10)), iso(now + timedelta(days=3)))):
        p = json.loads(r["payload"] or "{}")
        subject = (p.get("subject") or "").strip()
        others = [a for a in (p.get("attendees") or []) if a and not SAM.search(a)]
        st = _utc(p.get("start") or r["ts"])
        if not subject or not others or not st or PERSONAL.search(subject) or p.get("isCancelled") or p.get("isAllDay") or p.get("showAs") in ("free", "oof"):
            continue
        who = [names.get(a.lower()) or re.sub(r"@.*$", "", a).replace(".", " ").title() for a in others]
        with_ = ", ".join(who[:4]) + (f" and {len(who) - 4} more" if len(who) > 4 else "")
        when = _when(st, now)
        bare = ONE_TO_ONE.sub(" ", subject).strip()
        title = f"my 1:1 with {who[0].split()[0]}" if len(others) == 1 and (bare.lower() in who[0].lower() or ONE_TO_ONE.search(subject)) else _clip(subject, 40)
        add("today", "meeting", f"Prep me for {title}",
            f"Prep me for my meeting “{subject}” ({when}) with {with_}: what is open with them, what I should push for, and what to watch out for.",
            f"next meeting · {when}", 95 if when.startswith("today") else 75, "next-meeting")
        break
    m = con.execute("SELECT title, starts_at FROM meetings WHERE status IN ('analysed', 'digested') AND starts_at <= ? AND COALESCE(title, '') != '' "
                    "ORDER BY starts_at DESC LIMIT 5", (iso(now),)).fetchall()
    m = next((x for x in m if not PERSONAL.search(x["title"])), None)
    if m and _utc(m["starts_at"]):
        when = _when(_utc(m["starts_at"]), now)
        add("today", "asked", "What was asked of me in my last meeting?",
            f"In my meeting “{m['title']}” ({when}), what was asked of me, what did I commit to, and what was decided?",
            f"{_clip(m['title'], 40)} · {when}", 60, "last-meeting")

    # ---- people: who has the most open with Sam (the CEO always offered when anything is open with him)
    open_by = con.execute("SELECT p.id, p.name, p.title, COUNT(*) AS n FROM loops l JOIN people p ON p.id=l.person_id "
                          "WHERE l.status IN ('open','snoozed') AND l.dup_of IS NULL AND COALESCE(p.is_me, 0)=0 GROUP BY p.id ORDER BY n DESC, p.name").fetchall()
    picked = list(open_by[:2])
    ceo = next((r for r in open_by if re.search(r"\bCEO\b|chief executive", r["title"] or "", re.I)), None)
    if ceo and ceo not in picked:
        picked.append(ceo)
    for r in picked:
        first = r["name"].split()[0]
        add("people", "person", f"What is open between me and {first}?",
            f"What is open between me and {r['name']}? Group it into what I owe, what they owe me and what is waiting on a decision.",
            f"{_plural(r['n'], 'open item')}" + (" · CEO" if r is ceo else ""), 50 + min(r["n"], 20) + (12 if r is ceo else 0), f"open-with-{r['id']}")
    waits = con.execute("SELECT COUNT(*), SUM(origin_at <= ?) FROM loops WHERE kind='waiting' AND status='open' AND dup_of IS NULL",
                        (iso(now - timedelta(days=14)),)).fetchone()
    if waits[0]:
        add("people", "waiting", "Who owes me what, and what should I chase?",
            "Who owes me what? List what I am waiting on, oldest first, and which ones I should chase this week and how.",
            f"{waits[0]} waiting" + (f" · {waits[1]} over 14 days" if waits[1] else ""), 38 + min(waits[1] or 0, 20), "chase")
    add("people", "reach", "Who should I be in touch with more?",
        "Which of my key people have I been in touch with less than usual lately, and who should I reach out to this week?", None, 24, "reach")

    # ---- open items: replies, promises due, pending decisions, the stale ones
    replies = con.execute("SELECT COUNT(*) FROM loops WHERE kind='reply' AND status='open' AND dup_of IS NULL").fetchone()[0]
    add("open", "reply", "Which emails need a reply from me?",
        "Which emails and messages need a reply from me, most important first, with a one-line suggested answer for each?",
        f"{_plural(replies, 'reply', 'replies')} owed" if replies else None, 44 + replies * 3 if replies else 14, "replies")
    week_end = (now.astimezone(LONDON).date() + timedelta(days=7)).isoformat()
    promises = con.execute("SELECT COUNT(*), SUM(due IS NOT NULL AND due <= ?) FROM loops WHERE kind='promise' AND status='open' AND dup_of IS NULL",
                           (week_end,)).fetchone()
    if promises[0]:
        add("open", "promise", "What do I owe people this week?",
            "What have I promised people that is due this week or overdue, and what is the quickest way to close each?",
            (f"{promises[1]} due this week · " if promises[1] else "") + f"{promises[0]} promises open", 42 + min((promises[1] or 0) * 4, 30), "promises")
    dec = con.execute("SELECT COUNT(*), MIN(origin_at) FROM loops WHERE kind='decision' AND status='open' AND dup_of IS NULL").fetchone()
    if dec[0]:
        oldest = (now - _utc(dec[1])).days if _utc(dec[1]) else None
        add("open", "decision", "Which decisions have been pending longest?",
            "Which decisions are pending with me, oldest first? For each: what is the call, who is waiting on it, and what do you recommend?",
            f"{dec[0]} pending" + (f" · oldest {oldest} days" if oldest else ""), 40 + min(oldest or 0, 30) // 2, "decisions")
    stale = con.execute("SELECT COUNT(*) FROM loops WHERE status='open' AND dup_of IS NULL AND suggestion='decide_or_drop'").fetchone()[0]
    if stale:
        add("open", "drop", "What should I decide or drop?",
            "Which open items have gone stale? For each, recommend whether to close it, chase it or drop it, with one line of reasoning.",
            f"{stale} gone stale", 30 + min(stale, 30) // 2, "stale")

    # ---- numbers and bets: the last quarter, what closes this month, the quietest big bet
    today = now.astimezone(LONDON).date()
    q = (today.month - 1) // 3 + 1
    last_q, last_y = (q - 1, today.year) if q > 1 else (4, today.year - 1)
    prev_q, prev_y = (last_q - 1, last_y) if last_q > 1 else (4, last_y - 1)
    add("numbers", "numbers", f"How did Q{last_q} go by region versus Q{prev_q}?",
        f"How did Q{last_q} {last_y} go by region versus Q{prev_q} {prev_y}? New business, renewals and win rate, with what stands out.",
        None, 34, "quarter")
    try:
        deals = pipeline.listing(con)["opportunities"]
    except Exception:   # no Salesforce pull yet
        deals = []
    month = today.strftime("%Y-%m")
    closing = [d for d in deals if (d["close_date"] or "").startswith(month)]
    overdue = [d for d in deals if d["overdue"]]
    if closing or overdue:
        acv = sum(d["acv_usd"] for d in closing)
        add("numbers", "deal", f"Which deals close in {today:%B}?",
            f"Which deals are due to close in {today:%B %Y}, and which overdue deals are still open? Which are at risk, and what would move them?",
            " · ".join(x for x in [f"{_plural(len(closing), 'deal')} · ${acv / 1000:,.0f}k ACV" if closing else "", f"{len(overdue)} overdue" if overdue else ""] if x),
            32 + min(len(closing), 15), "closing")
        add("numbers", "sheet", f"Export {today:%B}'s closing deals to Excel",
            f"Make an Excel workbook of the deals due to close in {today:%B %Y} and the overdue deals still open: account, deal, stage, "
            f"close date, ACV in USD, forecast category and region, sorted by close date.",
            f"{_plural(len(closing) + len(overdue), 'deal')} · makes an .xlsx", 27, "closing-xlsx")
    bets = con.execute(f"SELECT i.id, i.name, i.weight, (SELECT COUNT(DISTINCT m.ref_id) FROM mentions m JOIN items it ON it.id=m.ref_id "
                       f"WHERE m.ref_type='item' AND m.entity_type='initiative' AND m.entity_id=i.id AND {_shown('m')} AND it.ts >= ? AND it.noise=0) AS n "
                       f"FROM initiatives i WHERE COALESCE(i.active, 1)=1 AND i.merged_into IS NULL ORDER BY i.weight DESC, n ASC LIMIT 1",
                       (iso(now - timedelta(days=14)),)).fetchone()
    if bets:
        add("numbers", "bet", f"Is {bets['name']} on track?",
            f"Is {bets['name']} on track? What has moved in the last two weeks, what is stuck, and what should I do about it?",
            f"weight {bets['weight']} · {_plural(bets['n'], 'item')} in 14 days", 30 + (bets["weight"] or 0) * 2, "bet")

    # ---- reflect: the plan, the ideas, the time
    add("reflect", "v2mom", "How am I doing against my V2MOM?",
        "How am I doing against my V2MOM measures? Be candid: where am I on track, behind, or without evidence either way?", None, 26, "v2mom")
    meetings = con.execute("SELECT COUNT(*) FROM meetings WHERE status != 'personal' AND starts_at >= ?", (iso(now - timedelta(days=14)),)).fetchone()[0]
    add("reflect", "idea", "What new ideas came up in my meetings?",
        "What new product ideas or innovation topics came up in my meetings over the last two weeks, who raised them, and which are worth pursuing?",
        f"{_plural(meetings, 'meeting')} in 14 days" if meetings else None, 22, "ideas")
    add("reflect", "time", "Where is my time going versus my bets?",
        "Where has my time gone over the last two weeks (meetings, mail, chat) compared with the weights of my bets? Where am I over- or under-invested?",
        None, 21, "time")
    add("reflect", "doc", "Write my weekly update as a Word document",
        f"Write my weekly update for {USER.manager_first} as a Word document: what moved on each bet this week, what is at risk, the decisions "
        "I need from him, and what I am doing next. Short, in my voice.", "makes a .docx", 23, "weekly-docx")

    out.sort(key=lambda x: -x["score"])
    return {"groups": [{"key": k, "label": v} for k, v in GROUPS], "items": out}
