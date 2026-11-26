"""What hovering an Ask SleePO chip shows (Sam, 17 Nov 2026: "click on them and go back to the context or ... hover over them and
see a snapshot of the context"). The chip names one thing SleePO holds by kind and id (assist/page_context.py chip); preview()
is that thing as it is now, in a few lines: a conversation's last messages, an email thread's last messages and the draft, a
bet's status, a topic's state, a task's steps, a person's latest exchanges and next meeting, a meeting's notes or brief, a
company's open deals, a document's summary, a roadmap entry. Built in code from the tables the pages read, never from the
browser; reads only. The chip's href (page_context.href) is where clicking it goes.

Shape: the chip's own fields, plus kicker (what it is, one line), at (its date), facts ([label, value]), text (a short
paragraph), md (a Markdown excerpt the card renders: a meeting's notes, a brief), lines_label and lines ([{who, when, text,
mine, done}]), draft_text (the reply being written), url (the real file, for a document) and reads (what the chat reads with
the first question, the chip's detail unless that is something else, as for a person, whose detail is their role).
"""
import json
import re
from datetime import datetime, timezone

from . import page_context as P

LINES = 4


def _clip(s, n):
    return P._clip(s, n)


def _head_md(text, n=700, lines=12, title=False):
    """The first whole lines of a Markdown text, up to n characters: an excerpt the card renders, never cut mid-line. title:
    the text opens with its own title (a brief's "# Prep · …"), which the card's header already says."""
    out, size = [], 0
    body = (text or "").replace("\r\n", "\n").lstrip()
    if title and body.startswith("# "):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    for line in body.split("\n"):
        if not line.strip() and (not out or not out[-1].strip()):
            continue
        if size + len(line) > n or len(out) >= lines:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out).strip()


def _first(name):
    """A first name to show: "Gray" for Gray Selby, "Ash" for Glen Yates (an initial is skipped)."""
    toks = (name or "").split()
    return next((t for t in toks if len(t.rstrip(".")) > 1), toks[0] if toks else "")


def _secs(a, b):
    try:
        f = lambda s: datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        return abs((f(a) - f(b)).total_seconds())
    except ValueError:
        return 1e9


def _same_message(a, b):
    """Two rows that are one message stored twice by two pulls (the Messages page shows it once: same sender, same second, or
    the same words within 5 minutes, one text a cut-off of the other)."""
    if (a["author"] or "") != (b["author"] or ""):
        return False
    x, y = (re.sub(r"[\s.…]+$", "", re.sub(r"\s+", " ", r["body_text"] or "")).strip() for r in (a, b))
    return a["sent_at"] == b["sent_at"] or (_secs(a["sent_at"], b["sent_at"]) <= 300 and bool(x) and (x.startswith(y) or y.startswith(x)))


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def preview(con, kind, ref):
    """The snapshot for one chip, or None when SleePO holds no such thing (a personal meeting, a deleted task). Reads only."""
    c = P.chip(con, kind, ref)
    if not c:
        return None
    out = {**c, "kicker": P.KINDS.get(c["kind"], c["kind"]), "at": "", "facts": [], "text": "", "md": "", "lines_label": "", "lines": [],
           "draft_text": "", "url": "", "reads": c.get("detail") or ""}
    fn = BUILDERS.get(c["kind"])
    try:
        out.update(fn(con, c) or {})
    except Exception:   # the chip still says what it is; the card shows what it has
        pass
    out["facts"] = [list(f) for f in out["facts"] if f[1] not in (None, "")]   # [label, value] or [label, value, a date the card shows after it]
    return out


# ---------------------------------------------------------------- one builder per kind
_CONV = {"dm": "direct message", "oneOnOne": "direct message", "group": "group chat", "channel": "channel", "meeting": "meeting chat"}


def _message(con, c):
    from . import message_chat
    from .chat_reply import SAM
    m = con.execute("SELECT item_id, source_id, conversation_id, conversation_name, conversation_kind, sent_at FROM chat_messages WHERE item_id=?",
                    (int(c["ref"]),)).fetchone()
    m = dict(m)
    ids = message_chat.around(con, m, before=2 * LINES, after=0)
    rows = {r["item_id"]: r for r in con.execute(
        f"SELECT item_id, author, sent_at, body_text FROM chat_messages WHERE item_id IN ({','.join('?' * len(ids))})", ids)}
    kept = []
    for i in ids:
        r = rows.get(i)
        if r and not (kept and _same_message(kept[-1], r)):
            kept.append(r)
    lines = []
    for r in kept[-LINES:]:
        mine = bool(SAM.search(r["author"] or ""))
        lines.append({"who": "You" if mine else _first(r["author"]) or "Someone", "when": r["sent_at"] or "", "text": _clip(r["body_text"], 220), "mine": mine})
    key, val = ("conversation_id", m["conversation_id"]) if m["conversation_id"] else ("conversation_name", m["conversation_name"])
    newer, prev = 0, kept[-1] if kept else None   # messages after it, each counted once (as the Messages page shows them)
    for r in con.execute(f"SELECT author, sent_at, body_text FROM chat_messages WHERE {key}=? AND source_id=? AND sent_at > ? ORDER BY sent_at LIMIT 500",
                         (val, m["source_id"], m["sent_at"] or "")):
        newer += 0 if prev and _same_message(prev, r) else 1
        prev = r
    app = "Slack" if m["source_id"] == "slack" else "Teams"
    return {"kicker": f"{app} · {_CONV.get(m['conversation_kind'] or '', 'conversation')}", "at": m["sent_at"] or "",
            "lines_label": "Up to the message it was asked about" if newer else "Latest messages", "lines": lines,
            "facts": [["Since then", f"{newer} newer message{'s' if newer != 1 else ''}" if newer else ""]]}


# what a quoted email's text carries that says nothing in a glance: a signature's "[Employee photo]<https://…>", bare links
_JUNK = re.compile(r"\[[^\]\n]{0,40}\]\s*<https?://[^>\s]+>|<https?://[^>\s]+>|\[(?:image|icon|cid:[^\]]*)[^\]]{0,30}\]", re.I)


def _tidy(text):
    return re.sub(r"\s+", " ", _JUNK.sub(" ", text or "")).strip()


def _names(raw, n=3):
    xs = [x.get("name") or x.get("address") or "" for x in json.loads(raw or "[]") if isinstance(x, dict)]
    xs = [x for x in xs if x]
    return ", ".join(xs[:n]) + (f" +{len(xs) - n}" if len(xs) > n else "")


def _email(con, c):
    from . import profile, threadparse
    m = con.execute("SELECT subject, from_name, from_address, to_json, cc_json, received_at, sent_at, body_text, has_attachments FROM mail_messages "
                    "WHERE item_id=?", (int(c["ref"]),)).fetchone()
    at = m["received_at"] or m["sent_at"] or ""
    msgs = threadparse.split(m["body_text"], m["from_name"] or m["from_address"] or "", at, _names(m["to_json"], 99))
    lines = []
    for x in msgs[-3:]:
        mine = profile.mentions_me(x.get("from") or "")
        lines.append({"who": "You" if mine else _first(x.get("from")) or "Someone", "when": at if x.get("latest") else "",
                      "when_text": "" if x.get("latest") else _clip(x.get("date"), 40), "text": _clip(_tidy(x.get("text")), 260), "mine": mine})
    files = con.execute("SELECT COUNT(*) FROM mail_attachments WHERE item_id=?", (int(c["ref"]),)).fetchone()[0]
    return {"kicker": "Email", "at": at, "lines_label": f"The thread · {len(msgs)} message{'s' if len(msgs) != 1 else ''}" if len(msgs) > 1 else "The email",
            "lines": lines, "draft_text": _clip(P._draft(con, int(c["ref"])), 420),
            "facts": [["From", m["from_name"] or m["from_address"]], ["To", _names(m["to_json"])], ["Cc", _names(m["cc_json"], 2)],
                      ["Files", f"{files} attached" if files else ""]]}


def _initiative(con, c):
    from . import topics
    r = con.execute("SELECT id, name, goal, weight FROM initiatives WHERE slug=?", (c["ref"],)).fetchone()
    u = con.execute("SELECT health, status_line, next, approved_at FROM initiative_updates WHERE initiative_id=? AND approved_at IS NOT NULL "
                    "ORDER BY approved_at DESC LIMIT 1", (r["id"],)).fetchone()
    tasks = con.execute("SELECT COUNT(*) FROM tasks WHERE initiative_id=? AND parent_id IS NULL AND status IN ('open','snoozed')", (r["id"],)).fetchone()[0]
    tops = []
    try:
        tops = [dict(t) for t in con.execute(f"SELECT title, last_ts, ask FROM topics WHERE {topics._latest(con)} AND initiative_id=? ORDER BY rank LIMIT 3", (r["id"],))]
    except Exception:
        pass
    return {"kicker": "Initiative" + (f" · {u['health']}" if u and u["health"] else ""), "at": u["approved_at"] if u else "",
            "text": (u["status_line"] if u else "") or r["goal"] or "",
            "facts": [["Goal", _clip(r["goal"], 160) if u else ""], ["Next", _clip(u["next"], 200) if u else ""], ["Weight", str(r["weight"] or "")],
                      ["Open tasks", str(tasks) if tasks else ""]],
            "lines_label": "Top of mind" if tops else "", "lines": [{"who": "", "when": t["last_ts"] or "", "text": t["title"]} for t in tops]}


def _topic(con, c):
    from . import tasks
    t = con.execute("SELECT * FROM topics WHERE id=?", (int(c["ref"]),)).fetchone()
    ini = con.execute("SELECT name FROM initiatives WHERE id=?", (t["initiative_id"],)).fetchone() if t["initiative_id"] else None
    area = {a["key"]: a["name"] for a in tasks.areas(con)}.get(t["area"]) if t["area"] else None
    task = con.execute("SELECT title FROM tasks WHERE id=? AND status != 'deleted'", (t["task_id"],)).fetchone() if t["task_id"] else None
    counts = ", ".join(f"{n} {w}{'s' if n != 1 else ''}" for n, w in ((t["meetings"], "meeting"), (t["mails"], "email"), (t["chats"], "message")) if n)
    pinned = "pinned_at" in t.keys() and t["pinned_at"]
    return {"kicker": "Top of mind" + (" · pinned" if pinned else "") + (" · private" if t["private"] else ""), "at": t["last_ts"] or "",
            "text": t["summary"] or "",
            "facts": [["On you", t["ask"]], ["Raised by", t["raised_by"]], ["Filed under", (ini["name"] if ini else area) or ""], ["Came up in", counts],
                      ["Task", task["title"] if task else ""]]}


_STEP = {"done": True, "dropped": True}


def _task(con, c):
    from . import tasks
    t = con.execute("SELECT * FROM tasks WHERE id=?", (int(c["ref"]),)).fetchone()
    top = con.execute("SELECT * FROM tasks WHERE id=?", (t["parent_id"],)).fetchone() if t["parent_id"] else None
    head = top or t
    ini = con.execute("SELECT name FROM initiatives WHERE id=?", (head["initiative_id"],)).fetchone() if head["initiative_id"] else None
    area = {a["key"]: a["name"] for a in tasks.areas(con)}.get(head["area"]) if head["area"] else None
    steps = [dict(s) for s in con.execute("SELECT title, owner, due, status FROM tasks WHERE parent_id=? AND status NOT IN ('deleted','dismissed','expired') "
                                         "ORDER BY position, id", (head["id"],))]
    left = [s for s in steps if s["status"] not in _STEP]
    shown = (left + [s for s in steps if s["status"] in _STEP])[:5]
    status = {"open": "open", "snoozed": "snoozed", "suggested": "suggested", "done": "done", "dropped": "dropped"}.get(t["status"], t["status"])
    return {"kicker": ("Step" if top else "Task") + f" · {status}",
            "text": t["why"] or "",
            "facts": [["Part of", top["title"] if top else ""], ["Done when", head["done_when"]], ["Filed under", (ini["name"] if ini else area) or "Not filed"],
                      ["Due", t["due"] or ""], ["Owner", t["owner"] if top else ""]],
            "lines_label": f"Steps · {len(steps) - len(left)} of {len(steps)} done" if steps else "",
            "lines": [{"who": s["owner"] or "You", "when": s["due"] or "", "text": s["title"], "done": s["status"] in _STEP} for s in shown]}


def _person(con, c):
    from . import entities
    p = con.execute("SELECT p.id, p.name, p.title, p.department, p.location, o.name AS org FROM people p LEFT JOIN orgs o ON o.id=p.org_id WHERE p.id=?",
                    (int(c["ref"]),)).fetchone()
    now = _now()
    nxt, latest = None, []
    for x in entities.timeline(con, "person", p["id"], limit=12):
        if P._personal(x.get("title")) or x["kind"] in ("doc", "opportunity"):
            continue
        if (x["ts"] or "") > now:
            nxt = x if x["kind"] == "event" else nxt   # newest first: the last one seen is the soonest
        elif len(latest) < 3:
            latest.append({"who": "You" if x.get("mine") else _first(x.get("from")) or x.get("label") or "", "when": x["ts"] or "",
                           "text": _clip(x.get("title") or x.get("snippet"), 160), "mine": bool(x.get("mine")), "kind": x.get("label") or x["kind"]})
    tasks = con.execute("SELECT COUNT(DISTINCT t.id) FROM mentions m JOIN tasks t ON t.id=m.ref_id WHERE m.ref_type='task' AND m.entity_type='person' "
                        "AND m.entity_id=? AND t.status IN ('open','snoozed')", (p["id"],)).fetchone()[0]
    return {"kicker": "Person", "reads": "Their profile, what is open with them, meetings and recent exchanges", "facts": [["Role", p["title"]], ["Company", p["org"]], ["Team", p["department"]], ["Based in", p["location"]],
                                          ["Open tasks with them", str(tasks) if tasks else ""],
                                          ["Next meeting", nxt["title"] if nxt else "", nxt["ts"] if nxt else ""]],
            "lines_label": "Latest with them" if latest else "", "lines": latest}


def _meeting(con, c):
    r = con.execute("SELECT id, title, starts_at, ends_at, note_item_id FROM meetings WHERE id=?", (int(c["ref"]),)).fetchone()
    note = con.execute("SELECT text FROM items WHERE id=?", (r["note_item_id"],)).fetchone() if r["note_item_id"] else None
    spoke = []
    try:
        spoke = [f"{'You' if s['is_me'] else _first(s['name'])} {round((s['share'] or 0) * 100)}%"
                 for s in con.execute("SELECT name, is_me, share FROM meeting_speakers WHERE meeting_id=? ORDER BY share DESC LIMIT 4", (r["id"],))]
    except Exception:
        pass
    return {"kicker": "Meeting · recorded", "at": r["starts_at"] or "", "end": r["ends_at"] or "",
            "facts": [["Who spoke", " · ".join(spoke)]], "md": _head_md(note["text"] if note else "")}


def _event(con, c):
    from . import prep
    from . import relevance as R
    e = con.execute("SELECT external_id, subject, ts, payload FROM items WHERE kind='event' AND external_id=?", (c["ref"],)).fetchone()
    p = json.loads(e["payload"] or "{}")
    who = []
    for a in p.get("attendees") or []:
        from .profile import mentions_me
        if mentions_me(a):
            continue
        try:
            x = R.resolve(con, a)
        except Exception:
            x = None
        who.append(x["name"] if x else a.split("@")[0].replace(".", " ").title())
    end = p.get("end") or ""
    end = end + "Z" if end and not re.search(r"(Z|[+-]\d\d:?\d\d)$", end) and (p.get("start_tz") or "UTC") == "UTC" else end
    b = prep._briefs(con).get(e["external_id"])
    d = con.execute("SELECT body_md FROM documents WHERE id=?", (b["doc_id"],)).fetchone() if b else None
    reply = {"organizer": "You organise it", "accepted": "Accepted", "tentativelyAccepted": "Tentative", "tentative": "Tentative",
             "notResponded": "Not answered", "none": "Not answered", "declined": "Declined"}.get(p.get("response") or "", "")
    return {"kicker": "Meeting" + (" · brief ready" if d and d["body_md"] else ""), "at": e["ts"] or "", "end": end,
            "facts": [["Invited", ", ".join(who[:5]) + (f" +{len(who) - 5}" if len(who) > 5 else "")], ["Where", _clip(p.get("location"), 60)], ["Your reply", reply]],
            "md": _head_md(d["body_md"] if d else "", title=True)}


def _company(con, c):
    from . import companies
    p = companies.page(con, int(c["ref"]))
    deals = [d for d in p["deals"] if d.get("is_open")]
    people = [x["name"] for x in p["people"][:3]]

    def money(d):
        try:
            v = float(d.get("acv") or 0)
        except (TypeError, ValueError):
            v = 0
        return f"{d.get('currency') or 'USD'} {v:,.0f}" if v else ""
    if deals:
        lines = [{"who": money(d), "when": d.get("close_date") or "", "text": _clip(" · ".join(x for x in (d.get("name"), d.get("stage")) if x), 120)}
                 for d in deals[:LINES]]
        label = f"Open deals · {len(deals)}"
    else:
        lines = [{"who": x.get("from") or x.get("label") or "", "when": x.get("ts") or "", "text": _clip(x.get("title") or x.get("label"), 140), "mine": bool(x.get("mine"))}
                 for x in p["activity"] if not P._personal(x.get("title"))][:3]
        label = "Latest" if lines else ""
    return {"kicker": c["sub"] or "Company", "facts": [["Their people", ", ".join(people) + (f" +{p['people_total'] - len(people)}" if p.get("people_total", 0) > len(people) else "")],
                                                      ["Our people", ", ".join(x["name"] for x in p["our_people"][:3])],
                                                      ["Bets", ", ".join(x["name"] for x in p["initiatives"][:3])]],
            "lines_label": label, "lines": lines}


def _document(con, c):
    from . import doccards
    d = P._doc_row(con, c["ref"])
    card = doccards.card(con, c["ref"]) or {}
    text = card.get("summary") or _clip(d["text"], 320)
    return {"kicker": P._DOC_FROM[c["ref"].split("-")[0]] + (f" · {card['kind']}" if card.get("kind") else "")
            + (" · superseded" if card.get("is_current") == 0 else ""), "at": d["ts"],
            "text": text, "url": d["url"] if (d["url"] or "").startswith("http") else "",
            "facts": [["File", d["name"] if card.get("title") and card["title"] != d["name"] else ""], ["Where", _clip(d["where"], 120)], ["By", d["author"]],
                      ["Sensitivity", card.get("sensitivity") if card.get("sensitivity") in ("confidential", "hr-legal", "personal") else ""]],
            "lines_label": "Key facts" if card.get("facts") else "", "lines": [{"who": "", "when": "", "text": _clip(f, 200)} for f in (card.get("facts") or [])[:3]]}


def _owners(raw):
    try:
        v = json.loads(raw or "")
        return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
    except ValueError:
        return raw or ""


def _roadmap(con, c):
    r = con.execute("SELECT * FROM roadmap_items WHERE id=?", (c["ref"],)).fetchone()
    when = r["start_q"] + (f" to {r['end_q']}" if r["end_q"] and r["end_q"] != r["start_q"] else "") if r["start_q"] else ""
    return {"kicker": "Roadmap · " + r["id"],
            "text": r["headline"] or r["value"] or "",
            "facts": [["When", when], ["Status", (r["status"] or "").replace("_", " ")], ["Owners", _owners(r["owners"])], ["Confidence", r["confidence"]],
                      ["Customers", _clip(r["customers"], 120)], ["Detail", _clip(r["detail"], 220) if len((r["detail"] or "").strip()) > 3 else ""]]}


BUILDERS = {"message": _message, "email": _email, "initiative": _initiative, "topic": _topic, "task": _task, "person": _person,
            "meeting": _meeting, "event": _event, "company": _company, "document": _document, "roadmap": _roadmap}
