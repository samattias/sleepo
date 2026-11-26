"""The Actions page: what to do next, split into reactive and proactive (Sam, 25 Nov 2026: "get rid of the dashboard page ...
a page with ... my reactive and proactive action. So reactive is like responding to an email ... my needs reply list and any
other thing based on calls ... and follow-ups, and proactive would be recommendations based on calls, commitments, etc.,
that I haven't done yet, so potentially draft emails or messages"). It replaced Today, the board of widgets.

Reactive: someone is waiting on the user.
  emails     mail that needs a response (replies.inbox, the one definition), with the recommended reply when one is ready
  messages   Teams and Slack messages the user owes an answer (the register's chat reply items)
  followups  the steps proposed from what was said in the user's recorded meetings (tasks of origin meeting citing the
             meeting, G<id>; assist/followup.py), the last FOLLOWUP_DAYS
Proactive: what SleePO recommends the user start.
  send       emails and Teams/Slack messages SleePO has written for steps of the user's tasks and suggestions
             (new_mail.recommended, the Drafts folder's list, plus message actions), most important first
  promises   what the user said they would do and has not done (the register's promises, as tasks of origin register)
  next       the other suggested next steps (chases, decisions, preparation, documents), ranked by the Tasks frame

A view, never a list of its own (CLAUDE.md: Tasks is the one list): every row is an email, a register item or a task step,
each shown once (the first section that holds it), and what the user does on a row acts on that thing through its own
routes. Reads only: building it writes nothing (/api/events would reload every tab).
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import db, org
from .promptkit import USER

FOLLOWUP_DAYS = 14   # follow-ups from meetings older than this are left to Tasks (suggestions expire at 30 days)
EMAIL_DAYS = 14      # the Inbox's own window for Needs response
STALE_DAYS = 3       # waiting longer than this is marked
LONG_OVERDUE = 7     # a date gone by more than this is likely overtaken: shown, not pushed to the top


def _rank(score, due, ts, suggested, today, now):
    """A row's score adjusted for freshness: a suggestion loses a little each day it waits (they expire at 30 days), and one
    whose date went by LONG_OVERDUE days ago loses its date's lift and more, so what is current comes first."""
    days = _due_days(due, today)
    if days is not None and days < -LONG_OVERDUE:
        score -= 14
    if suggested:
        score -= min(_days_since(ts, now) or 0, 30) * 0.4
    return score


def _now():
    return datetime.now(timezone.utc)


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _days_since(ts, now):
    try:
        t = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).days


def _due_days(due, today):
    try:
        return (datetime.fromisoformat(due[:10]).date() - datetime.fromisoformat(today).date()).days if due else None
    except ValueError:
        return None


def _due_tag(due, today):
    """'Overdue', 'Due today', 'Due tomorrow' or 'Due 27 Nov' for a date within a week, 'Was due 6 Nov' for one more than
    LONG_OVERDUE days gone (likely overtaken: not hot); None otherwise. And whether it is hot."""
    days = _due_days(due, today)
    if days is None:
        return None, False
    if days < -LONG_OVERDUE:
        return "Was due " + datetime.fromisoformat(due[:10]).strftime("%-d %b"), False
    if days < 0:
        return "Overdue", True
    if days == 0:
        return "Due today", True
    if days == 1:
        return "Due tomorrow", True
    if days <= 7:
        return "Due " + datetime.fromisoformat(due[:10]).strftime("%-d %b"), False
    return None, False


def _names(con, addrs):
    """Recipients as the names SleePO knows ("Quinn Irving"), the address where it knows none; and the first one's person id."""
    out, first = [], None
    for a in addrs or []:
        if not isinstance(a, str):
            continue
        pid = db.resolve_person(con, a)
        r = con.execute("SELECT name FROM people WHERE id=?", (pid,)).fetchone() if pid else None
        out.append(r["name"] if r else a)
        first = first or pid
    return ", ".join(out), first


# ------------------------------------------------------------------------------------------------ reactive
def emails(con, ceo, now=None):
    """Mail waiting on a response from the user: the Inbox's Needs response list, most important first (the CEO, then someone
    outside the company, then the longest waiting), with whether SleePO's recommended reply is ready."""
    from . import replies
    now = now or _now()
    try:
        ready = {r[0]: r[1] for r in con.execute("SELECT item_id, mode FROM reply_predrafts WHERE status='ok'")}
    except Exception:
        ready = {}
    out = []
    for m in replies.inbox(con, EMAIL_DAYS):
        if not m.get("needs_reply") or m.get("answered"):
            continue
        addr = (m.get("from_address") or "").lower()
        pid = db.resolve_person(con, addr) or db.resolve_person(con, m.get("from_name") or "")
        response = ready.get(m["id"]) if ready.get(m["id"]) in ("replyall", "forward") else m.get("response")
        waited = _days_since(m.get("received_at"), now) or 0
        tags, score = [], 0
        if pid and pid in ceo:
            tags.append("CEO")
            score += 6
        elif addr and "@" in addr and org.primary_domain() and not org.is_primary_address(addr):
            tags.append(f"Outside {USER.company}" if USER.company else "External")
            score += 4
        if response == "forward":
            tags.append("Forward")
        if m["id"] in ready:
            tags.append("Draft ready")
        if waited > STALE_DAYS:
            tags.append(f"Waiting {waited} days")
        out.append({"key": f"e-{m['id']}", "kind": "email", "title": m.get("subject") or "(no subject)",
                    "line": _clip(m.get("preview") or "", 160), "why": m.get("reply_why") or "",
                    "who": m.get("from_name") or m.get("from_address") or "", "person_id": pid, "app": "outlook",
                    "ts": m.get("received_at"), "tags": tags, "hot": waited > STALE_DAYS or score >= 6, "ready": m["id"] in ready,
                    "open": f"/inbox?open={m['id']}", "item_id": m["id"], "attachments": bool(m.get("has_attachments")),
                    "_score": score + min(waited, 5)})
    out.sort(key=lambda r: r["ts"] or "", reverse=True)
    out.sort(key=lambda r: -r["_score"])
    return out


def messages(con, now=None):
    """Teams and Slack messages the user owes an answer: the register's open chat reply items (snoozed ones once due)."""
    now = now or _now()
    out = []
    try:
        rows = con.execute("SELECT l.*, c.source_id AS app, c.conversation_name, c.body_text, c.sent_at, c.author FROM loops l "
                           "LEFT JOIN chat_messages c ON c.item_id=l.fact_id WHERE l.kind='reply' AND l.fact_type='chat' "
                           "AND (l.status='open' OR (l.status='snoozed' AND COALESCE(l.snooze_until, '') <= ?)) "
                           "ORDER BY COALESCE(l.origin_at, l.created_at) DESC", (_iso(now),)).fetchall()
    except Exception:
        return []
    for r in rows:
        waited = _days_since(r["origin_at"] or r["created_at"], now) or 0
        tags = [f"Waiting {waited} days"] if waited > STALE_DAYS else []
        out.append({"key": f"m-{r['id']}", "kind": "message", "title": r["counterpart"] or r["author"] or r["title"],
                    "line": _clip(r["body_text"] or r["detail"] or r["title"], 160), "why": r["conversation_name"] or "",
                    "who": r["counterpart"] or r["author"] or "", "person_id": r["person_id"],
                    "app": "slack" if r["app"] == "slack" else "teams", "ts": r["sent_at"] or r["origin_at"] or r["created_at"],
                    "tags": tags, "hot": waited > STALE_DAYS, "open": f"/messages?open={r['fact_id']}",
                    "item_id": r["fact_id"], "loop_id": r["id"]})
    return out


# ------------------------------------------------------------------------------------------------ task steps
def _moves(listing):
    """Every step the user could take next from Tasks, as (step, task): steps of open and suggested tasks that are the user's
    (no owner, or a hand-off still to send), open or suggested, and a task with no steps as its own step."""
    seen = set()
    for t in listing["tasks"] + [s for s in listing["suggestions"] if not s.get("parent_id")]:
        if t["status"] not in ("open", "suggested"):
            continue
        steps = [s for s in t.get("subtasks") or [] if s["status"] in ("open", "suggested")]
        if not t.get("subtasks") or not [s for s in t["subtasks"] if s["status"] not in ("dismissed", "expired", "deleted")]:
            steps = [t]   # a task with no steps is its own step
        for s in steps:
            if s["id"] in seen or (s["owner"] and not s.get("handoff")):
                continue
            seen.add(s["id"])
            yield s, t
    for s in listing["suggestions"]:   # suggested steps on tasks the user has (the listing gives them on their own)
        if s.get("parent_id") and s["id"] not in seen and not s["owner"]:
            seen.add(s["id"])
            yield s, {"id": s["parent_id"], "title": s.get("parent_title") or "", "status": "open", "initiative": s.get("initiative"),
                      "area_name": s.get("area_name"), "weight": s.get("weight"), "due": None, "priority": None}


def _meeting_source(s):
    """The meeting a step was proposed from (a source G<id>), as (meeting id, its label and moment, link), else None."""
    for src in s.get("sources") or []:
        ref = str(src.get("ref") or "")
        if re.fullmatch(r"G\d+", ref):
            return int(ref[1:]), src.get("label") or "", src.get("url") or ""
    return None


def _step_kind(s):
    """What doing the step means, from its actions: (label, the first email or message action's index)."""
    for i, a in enumerate(s.get("actions") or []):
        if a.get("type") == "email" and not a.get("sent") and not a.get("excluded"):
            return ("Reply ready" if a.get("reply_to") else "Email ready"), i
        if a.get("type") in ("teams", "slack") and (a.get("message") or a.get("body")):
            return ("Slack message ready" if a["type"] == "slack" else "Teams message ready"), i
    for a in s.get("actions") or []:
        if a.get("type") == "create":
            return "Document", None
    return {"decide": "Decide", "chase": "Chase", "prep": "Prepare", "reply": "Reply", "create": "Document"}.get(s.get("kind") or "", ""), None


def _step_row(s, t, kind, today):
    label, idx = _step_kind(s)
    due = s.get("due") or (t.get("due") if s is t else None)
    due_tag, hot = _due_tag(due, today)
    suggested = s["status"] == "suggested" or t["status"] == "suggested"
    tags = [x for x in (label, due_tag) if x]
    if not suggested:
        tags.append("On your list")
    filed = t.get("initiative") or t.get("area_name") or ""
    a = (s.get("actions") or [])[idx] if idx is not None else None
    draft = f"t-{s['id']}-{idx}" if a and a.get("type") == "email" and not a.get("reply_to") else None
    return {"key": f"s-{s['id']}", "kind": kind, "title": s["title"], "line": _clip(s.get("why") or "", 200),
            "task": t["title"] if s is not t else "", "task_id": t["id"], "step_id": s["id"], "filed": filed,
            "who": ", ".join(s.get("people") or []) if s is not t else ", ".join(t.get("people") or []),
            "person_id": s.get("owner_person_id"), "ts": s.get("created_at"), "due": due, "tags": tags, "hot": hot,
            "suggested": suggested, "status": s["status"], "open": f"/tasks?open={s['id']}", "draft": draft,
            "action": ({k: a.get(k) for k in ("type", "label", "to", "cc", "subject", "channel", "user")} if a else None),
            "sources": [{"label": x.get("label") or x.get("ref") or "Source", "url": x.get("url") or ""}
                        for x in (s.get("sources") or []) if isinstance(x, dict)][:3]}


def followups(con, moves, today, now=None):
    """Steps proposed from what was said in the user's meetings of the last FOLLOWUP_DAYS, newest meeting first, then in the
    order the follow-up gave them."""
    now = now or _now()
    since = _iso(now - timedelta(days=FOLLOWUP_DAYS))
    out = []
    for s, t in moves:
        src = _meeting_source(s)
        if s.get("origin") != "meeting" or not src or (s.get("created_at") or "") < since or (s.get("kind") == "prep"):
            continue
        mid, label, url = src
        m = con.execute("SELECT title, starts_at FROM meetings WHERE id=?", (mid,)).fetchone()
        r = _step_row(s, t, "followup", today)
        title = (m["title"] if m else "") or re.sub(r"^Meeting:\s*", "", label.split(" · ")[0])
        moment = label.split(" · ", 1)[1] if " · " in label else ""
        r.update(meeting={"id": mid, "title": title, "at": m["starts_at"] if m else None, "url": f"/meetings?open=m-{mid}"},
                 said={"label": _clip(moment, 160), "url": url} if moment else None)
        r["_at"] = (m["starts_at"] if m else "") or s.get("created_at") or ""
        out.append(r)
    out.sort(key=lambda r: (r["_at"], -(r["step_id"])), reverse=True)
    return out


# ------------------------------------------------------------------------------------------------ proactive
def send(con, moves, taken, today, now=None):
    """Emails and Teams/Slack messages SleePO has written for the user's steps, not yet sent: the Drafts folder's recommended
    emails (new_mail.recommended: ranked, the top ones marked to send first) and the message actions, by the same frame."""
    from . import new_mail, tasks
    now = now or _now()
    out = []
    for r in new_mail.recommended(con):
        if f"s-{r['step_id']}" in taken:
            continue
        a = r["action"]
        who, pid = _names(con, a.get("to"))
        due_tag, hot = _due_tag(r.get("due"), today)
        tags = ["Email ready"] + ([due_tag] if due_tag else []) + ([] if r["suggested"] else ["On your list"])
        out.append({"key": f"s-{r['step_id']}", "kind": "send", "title": a.get("subject") or r["step_title"],
                    "line": _clip(a.get("body") or "", 200), "task": r["task_title"], "task_id": r["task_id"], "step_id": r["step_id"],
                    "filed": r.get("filed") or "", "who": who, "person_id": pid, "app": "outlook",
                    "ts": r["ts"], "due": r.get("due"), "tags": tags, "hot": hot or (r["level"] == "high" and (_due_days(r.get("due"), today) or 0) >= -LONG_OVERDUE),
                    "level": r["level"], "rank_why": r.get("rank_why") or [], "suggested": r["suggested"],
                    "open": f"/inbox?draft={r['key']}", "draft": r["key"], "index": r["index"],
                    "action": {k: a.get(k) for k in ("type", "label", "to", "cc", "subject")}, "sources": r.get("sources") or [],
                    "_score": _rank(r["score"], r.get("due"), r["ts"], r["suggested"], today, now)})
        taken.add(f"s-{r['step_id']}")
    ceo = tasks._ceo_ids(con)
    for s, t in moves:
        if f"s-{s['id']}" in taken:
            continue
        label, idx = _step_kind(s)
        if idx is None or (s.get("actions") or [])[idx].get("type") not in ("teams", "slack"):
            continue
        r = _step_row(s, t, "send", today)
        a = s["actions"][idx]
        r.update(app=a["type"], line=_clip(a.get("message") or a.get("body") or "", 200), index=idx,
                 who=a.get("user") or (f"#{a['channel'].lstrip('#')}" if a.get("channel") else r["who"]), level="normal",
                 _score=_rank(tasks._score({**t, "next_due": s.get("due"), "priority": s.get("priority") or t.get("priority")}, today, ceo),
                              r["due"], r["ts"], r["suggested"], today, now))
        out.append(r)
        taken.add(r["key"])
    out.sort(key=lambda r: r["ts"] or "", reverse=True)
    out.sort(key=lambda r: -r["_score"])
    return out


def promises(con, moves, taken, today, now=None):
    """What the user said they would do and has not done: the register's promises, as tasks (origin register), with whom and
    when it was said. Overdue and due soon first, then the newest."""
    now = now or _now()
    out = []
    for s, t in moves:
        if f"s-{s['id']}" in taken or s.get("origin") != "register" or (s.get("kind") or "do") not in ("do", "reply", "create"):
            continue
        loop = con.execute("SELECT counterpart, person_id, origin_at, said_json, due FROM loops WHERE id=?", (s["loop_id"],)).fetchone() \
            if s.get("loop_id") else None
        r = _step_row(s, t, "promise", today)
        if loop:
            r["who"] = loop["counterpart"] or r["who"]
            r["person_id"] = loop["person_id"] or r["person_id"]
            r["made"] = loop["origin_at"]
            said = json.loads(loop["said_json"] or "null")
            if isinstance(said, dict) and said.get("url"):
                r["said"] = {"label": _clip(said.get("label") or said.get("quote") or "", 160), "url": said["url"]}
            if not r.get("due") and loop["due"]:
                r["due"] = loop["due"]
                tag, hot = _due_tag(loop["due"], today)
                if tag:
                    r["tags"].insert(0, tag)
                    r["hot"] = r["hot"] or hot
        made = _days_since(r.get("made") or s.get("created_at"), now) or 0
        if made > 7:
            r["tags"].append(f"Promised {made} days ago")
        days = _due_days(r.get("due"), today)
        r["_score"] = _rank((20 if r["hot"] else 0) + (6 if days is not None and days <= 7 else 0) - min(made, 30) / 10,
                            r.get("due"), r.get("made") or r["ts"], r["suggested"], today, now)
        out.append(r)
        taken.add(r["key"])
    out.sort(key=lambda r: r.get("made") or r["ts"] or "", reverse=True)
    out.sort(key=lambda r: -r["_score"])
    return out


def nexts(con, moves, taken, today, now=None):
    """The other suggested next steps (the assistant's pass, drafts, chases from the register, preparation): one row per step,
    ranked by the Tasks frame (the bet's weight, the date, the priority, the CEO)."""
    from . import tasks
    now = now or _now()
    ceo = tasks._ceo_ids(con)
    out = []
    for s, t in moves:
        if f"s-{s['id']}" in taken or not (s["status"] == "suggested" or t["status"] == "suggested"):
            continue
        r = _step_row(s, t, "next", today)
        r["_score"] = _rank(tasks._score({**t, "next_due": s.get("due") or t.get("due"), "priority": s.get("priority") or t.get("priority")}, today, ceo),
                            r["due"], r["ts"], r["suggested"], today, now)
        out.append(r)
        taken.add(r["key"])
    out.sort(key=lambda r: r["ts"] or "", reverse=True)
    out.sort(key=lambda r: -r["_score"])
    return out


# ------------------------------------------------------------------------------------------------ the page
def build(con, now=None):
    """{reactive: {emails, messages, followups}, proactive: {send, promises, next}, counts}. Reads only."""
    from . import tasks
    now = now or _now()
    today = now.astimezone().date().isoformat()
    ceo = tasks._ceo_ids(con)
    listing = tasks.listing(con, write=False)
    moves = list(_moves(listing))
    fu = followups(con, moves, today, now)
    taken = {r["key"] for r in fu}
    out = {"reactive": {"emails": emails(con, ceo, now), "messages": messages(con, now), "followups": fu},
           "proactive": {"send": send(con, moves, taken, today, now)}}
    out["proactive"]["promises"] = promises(con, moves, taken, today, now)
    out["proactive"]["next"] = nexts(con, moves, taken, today, now)
    for side in ("reactive", "proactive"):
        for rows in out[side].values():
            for r in rows:
                for k in [k for k in r if k.startswith("_")]:
                    r.pop(k)
    out["counts"] = {side: sum(len(v) for v in out[side].values()) for side in ("reactive", "proactive")}
    return out
