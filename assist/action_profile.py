"""Every kind of action Sam takes at work, and how he actually takes them, measured from his own mail, chat, calendar,
meetings, documents and promises. Feeds the Action types page (System) and the Actions list, so suggested actions use the
action types and channels Sam really uses, with the people he uses them with.

Each catalogue entry says how it is measured (or that it is not measured yet), and whether SleePO can prepare it (a draft
to copy, a Claude hand-off, a meeting brief). The profile is computed on request from the database (cheap) and cached
for ten minutes. Message bodies are only counted (length, keywords); nothing is copied out of them.
"""
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import db
from .promptkit import USER   # the user in prompt text (assist/profile.py)

from .profile import sql_author as _me_author, sql_mentions as _me_named, zone as _zone   # the user (this module has its own profile())

try:
    from zoneinfo import ZoneInfo
    TZ = _zone()
except Exception:  # pragma: no cover
    TZ = timezone.utc

ME = db.ME_LOOSE   # the one definition, assist/db.py
CHASE = re.compile(r"\b(following up|follow up on|any update|chasing|gentle reminder|reminder|nudge|circling back|where are we on)\b", re.I)
ASK = re.compile(r"\b(can you( please)?|could you( please)?|please (send|share|review|prepare|update|confirm|draft|set up|schedule|check|add|look))\b", re.I)
SHARE = re.compile(r"sharepoint\.com|1drv\.ms|onedrive\.live\.com|teams\.microsoft\.com/l/file|docs\.google\.com", re.I)

# key, name, category, how SleePO can help (None = not yet), what is measured
CATALOGUE = [
    ("email_new", "Send an email", "Communicate", "email", "Sent mail that is not a reply, forward or calendar response"),
    ("email_reply", "Reply to an email", "Communicate", "email", "Sent mail starting Re:"),
    ("email_forward", "Forward an email", "Communicate", "email", "Sent mail starting FW:"),
    ("teams_dm", "Send a Teams message", "Communicate", "teams", "Your messages in Teams one-to-one chats"),
    ("teams_group", "Post in a Teams group or meeting chat", "Communicate", "teams", "Your messages in Teams group and meeting chats"),
    ("teams_channel", "Post in a Teams channel", "Communicate", "teams", "Your messages in Teams channels"),
    ("slack_dm", "Send a Slack message", "Communicate", "slack", "Your Slack direct messages"),
    ("slack_channel", "Post in a Slack channel", "Communicate", "slack", "Your messages in Slack channels"),
    ("meeting_schedule", "Schedule a meeting", "Meet", None, "Calendar events you organised"),
    ("meeting_respond", "Accept or decline an invite", "Meet", None, "Sent calendar responses"),
    ("meeting_hold", "Hold a meeting", "Meet", "prep", "Meetings recorded in Granola"),
    ("meeting_prep", "Prepare for a meeting", "Meet", "prep", "Meeting briefs SleePO wrote"),
    ("doc_create", "Create or update a document", "Create", "create", "Your files changed on this Mac or in SharePoint/OneDrive"),
    ("doc_share", "Share a document or link", "Create", None, "Mail and messages you sent with a SharePoint/OneDrive/Teams file link"),
    ("doc_review", "Review or comment on a document", "Create", "edit", "Not measured yet (document comments are not read)"),
    ("decide", "Make a decision", "Decide", "draft", "Not measured since decisions were retired (26 Oct 2026): decide steps in Tasks"),
    ("commit", "Commit to something", "Decide", None, "Promises you made (open items)"),
    ("ask", "Ask someone for something", "Delegate", "teams", "Mail and messages you sent with a direct ask (can you / please …)"),
    ("chase", "Follow up or chase", "Delegate", "teams", "Mail and messages you sent that follow up or chase"),
    ("approve", "Approve a request", "Admin", None, "Not measured yet (approvals happen in other tools)"),
]


def _london(ts):
    try:
        d = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(TZ)
    except ValueError:
        return None


def person_of(conversation):
    """The person a one-to-one chat is with, from however the pull named it ("DM Gray", "1:1 chat Gray Selby",
    "Chat with Gray Selby (budget)")."""
    t = re.sub(r"^\s*(DM|1:1 chat|1:1|Chat with|Direct message with)\s*[:\-]?\s*", "", conversation or "", flags=re.I)
    return re.sub(r"\s*\(.*\)\s*$", "", t).strip()


def _own(body):
    from .replies import _own_text
    try:
        return _own_text(body or "")
    except Exception:
        return body or ""


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def actions(con, since, until=None, text=False):
    """Every action Sam took between since and until (UTC datetimes), oldest first: the one list the Action types page
    counts and the task history clusters (assist/task_history.py). Each is {ref, key, tags, ts, who, words, item_id,
    label, url, thread, conversation, meeting_id} and, with text=True, its own words (clipped) for the history run.
    key is its CATALOGUE type; tags are the other types it also counts as (doc_share, ask, chase)."""
    lo, hi = _iso(since), _iso(until or datetime.now(timezone.utc))
    out = []

    def add(key, ts, who=(), words=None, tags=(), **kw):
        out.append({"key": key, "ts": ts, "who": [w for w in who if w and not ME.search(w)], "words": words, "tags": list(tags), **kw})

    def tags_of(body, own, links=""):
        return [t for t, hit in (("doc_share", SHARE.search(body or "") or SHARE.search(links or "")), ("ask", ASK.search(own or "")),
                                 ("chase", CHASE.search(own or ""))) if hit]

    # mail
    for r in con.execute("SELECT m.item_id, m.subject, m.sent_at, m.to_json, m.cc_json, m.body_text, m.conversation_id, m.web_link, i.url "
                         "FROM mail_messages m LEFT JOIN items i ON i.id=m.item_id WHERE m.folder='sentitems' AND m.sent_at >= ? AND m.sent_at <= ? "
                         "ORDER BY m.sent_at", (lo, hi)):
        subj = (r["subject"] or "").strip()
        to = [x.get("name") or x.get("address") for x in json.loads(r["to_json"] or "[]")]
        cc = [x.get("name") or x.get("address") for x in json.loads(r["cc_json"] or "[]")]
        own = _own(r["body_text"])
        base = {"ref": f"mail-{r['item_id']}", "item_id": r["item_id"], "label": subj or "(no subject)", "url": r["url"] or r["web_link"],
                "thread": r["conversation_id"], "cc": [w for w in cc if w and not ME.search(w)]}
        if text:
            base["text"] = re.sub(r"\s+", " ", own)[:400]
        if re.match(r"(?i)^(accepted|declined|tentative|tentatively accepted)\b", subj):
            add("meeting_respond", r["sent_at"], to, **base)
            continue
        key = "email_reply" if re.match(r"(?i)^re\s*:", subj) else "email_forward" if re.match(r"(?i)^(fw|fwd)\s*:", subj) else "email_new"
        add(key, r["sent_at"], to, len(own.split()), tags_of(r["body_text"], own), **base)
    # chat
    for r in con.execute("SELECT item_id, source_id, conversation_id, conversation_kind, conversation_name, sent_at, body_text, links_json, web_link "
                         f"FROM chat_messages WHERE sent_at >= ? AND sent_at <= ? AND {_me_author('author')} ORDER BY sent_at", (lo, hi)):
        kind = r["conversation_kind"] or ""
        src = r["source_id"] or ""
        who = [person_of(r["conversation_name"])] if kind in ("dm", "oneOnOne") else []
        if src.startswith("slack"):
            key = "slack_dm" if kind == "dm" else "slack_channel"
        else:
            key = "teams_dm" if kind in ("dm", "oneOnOne") else "teams_channel" if kind == "channel" else "teams_group"
        body = r["body_text"] or ""
        base = {"ref": f"chat-{r['item_id']}", "item_id": r["item_id"], "label": r["conversation_name"] or src, "url": r["web_link"],
                "conversation": r["conversation_id"] or r["conversation_name"]}
        if text:
            base["text"] = re.sub(r"\s+", " ", body)[:300]
        add(key, r["sent_at"], who, len(body.split()), tags_of(body, body, r["links_json"]), **base)
    # calendar and meetings
    for r in con.execute("SELECT id, ts, subject, url, payload FROM items WHERE kind='event' AND noise=0 AND ts >= ? AND ts <= ? ORDER BY ts", (lo, hi)):
        p = json.loads(r["payload"] or "{}")
        if p.get("isOrganizer") and p.get("attendees"):
            add("meeting_schedule", r["ts"], [re.sub(r"@.*", "", a).replace(".", " ").title() for a in p["attendees"]],
                ref=f"event-{r['id']}", item_id=r["id"], label=r["subject"] or "(meeting)", url=r["url"])
    for r in con.execute("SELECT id, title, starts_at, attendees, digest_md FROM meetings WHERE status != 'personal' AND starts_at >= ? AND starts_at <= ? "
                         "ORDER BY starts_at", (lo, hi)):
        base = {"ref": f"meeting-{r['id']}", "meeting_id": r["id"], "label": r["title"] or "(meeting)", "url": f"#/meetings/m-{r['id']}"}
        if text:
            base["text"] = re.sub(r"\s+", " ", r["digest_md"] or "")[:500]
        add("meeting_hold", r["starts_at"], json.loads(r["attendees"] or "[]"), **base)
    for r in con.execute("SELECT id, title, updated_at FROM documents WHERE section='Prep' AND updated_at >= ? AND updated_at <= ?", (lo, hi)):
        add("meeting_prep", r["updated_at"], ref=f"prep-{r['id']}", label=r["title"] or "Meeting brief")
    # documents
    for r in con.execute(f"SELECT id, ts, subject, url FROM items WHERE (source_id='local' OR (source_id='sharepoint' AND {_me_named('from_name')})) "
                         "AND ts >= ? AND ts <= ? ORDER BY ts", (lo, hi)):
        add("doc_create", r["ts"], ref=f"doc-{r['id']}", item_id=r["id"], label=r["subject"] or "(document)", url=r["url"])
    # promises
    try:
        for r in con.execute("SELECT id, title, origin_at, counterpart FROM loops WHERE kind='promise' AND origin_basis='source' AND origin_at >= ? AND origin_at <= ?", (lo, hi)):
            add("commit", r["origin_at"], [r["counterpart"]], ref=f"loop-{r['id']}", label=r["title"])
    except Exception:
        pass
    out.sort(key=lambda a: a["ts"] or "")
    return out


_CACHE = {"at": 0, "data": None}


def profile(con, days=30, fresh=False):
    if not fresh and _CACHE["data"] and time.time() - _CACHE["at"] < 600:
        return _CACHE["data"]
    now = datetime.now(timezone.utc)
    start, prev = now - timedelta(days=days), now - timedelta(days=2 * days)
    ev = defaultdict(list)   # key -> [(local datetime, counterpart names, words)]
    for a in actions(con, prev, now):   # the one action list (above); a sent mail or message also counts under its tags
        d = _london(a["ts"])
        if not d:
            continue
        ev[a["key"]].append((d, a["who"], a["words"]))
        for t in a["tags"]:
            ev[t].append((d, a["who"], None))

    # what SleePO suggested, by draft type, and what Sam did with it
    suggested = Counter()
    for (aj,) in con.execute("SELECT actions_json FROM todo WHERE created_at >= ?", (start.strftime("%Y-%m-%dT%H:%M:%SZ"),)):
        for a in json.loads(aj or "[]"):
            for x in (a.get("steps") or [a]):
                suggested[x.get("type")] += 1
    try:
        copied = con.execute("SELECT COUNT(*) FROM feedback WHERE target_type='action' AND copied=1 AND created_at >= ?", (start.strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchone()[0]
    except Exception:
        copied = None

    # trends only where the earlier window is covered by data (full mail and chat capture began in September)
    def earliest(sql):
        try:
            v = con.execute(sql).fetchone()[0]
            return _london(v) if v else None
        except Exception:
            return None
    covered = {"mail": earliest("SELECT MIN(sent_at) FROM mail_messages WHERE folder='sentitems'"),
               "chat": earliest(f"SELECT MIN(sent_at) FROM chat_messages WHERE {_me_author('author')}")}
    family = {k: ("mail" if k.startswith("email") or k == "meeting_respond" else "chat" if k.startswith(("teams", "slack")) else None) for k, *_ in CATALOGUE}
    prev_ok = lambda k: family[k] is None or (covered.get(family[k]) is not None and covered[family[k]] <= prev.astimezone(TZ) + timedelta(days=3))
    s_local = start.astimezone(TZ)
    out = []
    for key, name, cat, helps, how in CATALOGUE:
        e = ev.get(key, [])
        cur = [x for x in e if x[0] >= s_local]
        before = [x for x in e if x[0] < s_local]
        weeks = [0] * 8
        for d, _w, _n in e:
            k = int((now.astimezone(TZ) - d).days // 7)
            if 0 <= k < 8:
                weeks[7 - k] += 1
        hours = Counter(d.hour for d, _w, _n in cur)
        days_ = Counter(d.strftime("%a") for d, _w, _n in cur)
        people = Counter(w for _d, ws, _n in cur for w in ws)
        lengths = [n for _d, _w, n in cur if n]
        measured = not how.startswith("Not measured")
        out.append({"key": key, "name": name, "category": cat, "how": how, "measured": measured, "sleepo": helps,
                    "count": len(cur), "per_week": round(len(cur) / (days / 7), 1), "prev": len(before),
                    "trend": None if not before or not prev_ok(key) or family[key] is None and key not in ("meeting_hold", "meeting_schedule") else round((len(cur) - len(before)) / len(before) * 100),
                    "weeks": weeks, "last": max((d for d, _w, _n in e), default=None).isoformat() if e else None,
                    "peak_hours": [h for h, _ in hours.most_common(3)], "peak_days": [d for d, _ in days_.most_common(2)],
                    "people": [{"name": n, "count": c} for n, c in people.most_common(6)],
                    "median_words": round(statistics.median(lengths)) if lengths else None,
                    "suggested": suggested.get(helps, 0) if helps in ("email", "teams", "slack", "create", "edit", "draft") else None})
    out.sort(key=lambda x: (["Communicate", "Meet", "Create", "Decide", "Delegate", "Admin"].index(x["category"]), -x["count"]))

    # preferred channel per person (who Sam writes to, and how)
    chan = defaultdict(Counter)
    for key, label in (("email_new", "Email"), ("email_reply", "Email"), ("email_forward", "Email"), ("teams_dm", "Teams"), ("slack_dm", "Slack")):
        for d, ws, _n in ev.get(key, []):
            if d >= s_local:
                for w in ws:
                    chan[w][label] += 1
    by_person = sorted(({"name": n, "total": sum(c.values()), "channels": dict(c), "preferred": c.most_common(1)[0][0]} for n, c in chan.items()
                        if sum(c.values()) >= 3), key=lambda x: -x["total"])[:20]
    data = {"days": days, "computed": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "types": out, "by_person": by_person,
            "suggestions": {"by_type": dict(suggested), "copied": copied}}
    _CACHE.update(at=time.time(), data=data)
    return data


def context_lines(con):
    """A short section for the Actions list prompt: what Sam actually does, and how he reaches each person."""
    p = profile(con)
    top = [t for t in p["types"] if t["measured"] and t["count"]]
    L = [f"How {USER.first} actually acts (last 30 days; prefer these action types and channels, and match the channel to the person):"]
    L += [f"- {t['name']}: {t['count']} ({t['per_week']}/week)" + (f", typically ~{t['median_words']} words" if t["median_words"] else "")
          + (f", mostly {', '.join(t['peak_days'])}" if t["peak_days"] else "") for t in sorted(top, key=lambda x: -x["count"])[:12]]
    if p["by_person"]:
        L.append(f"Channel {USER.first} uses with each person (use it for drafts to them): " +
                 "; ".join(f"{x['name']}: {x['preferred']} ({', '.join(f'{k} {v}' for k, v in x['channels'].items())})" for x in p["by_person"][:15]))
    return "\n".join(L)
