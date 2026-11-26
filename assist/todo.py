"""Actions: a prioritised to-do list of what Sam should deal with now and today, each with ready-made actions.

The server assembles a context pack from the database (calendar and meeting briefs, mail that needs a reply, recent
direct messages, the open-items register, initiatives, Sam's priorities and the company soul
page). Every source carries a short reference (E12, M3, C7, ...). One headless Claude run with NO tools
(--tools "" --strict-mcp-config) turns it into a ranked JSON list; nothing in an email or message can make it act.
The references are mapped back to links here, and the list is merged with what is already stored so that done,
dismissed and snoozed items stay that way. Actions use the same shape as brief actions (components/Actions.tsx), so
email becomes an Outlook draft, Teams opens prefilled, Slack becomes a draft: nothing is ever sent.
"""
import json
import os
import re
import subprocess
import threading
import urllib.parse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .promptkit import USER   # the user in prompt text (assist/profile.py)

SAM = db.ME_STRICT   # the user's address (assist/profile.py)
MAX_ITEMS = 12
PROMPT_VERSION = "todo-2026-10-13c"   # + soul rules in full (were cut off) and the CPO soul; earlier: deliverables as create actions


def _clip(t, n):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _read(rel, n):
    p = db.ASSIST / rel
    return _clip(p.read_text(), n) if p.exists() else ""


def context(con):
    """Return (text, refs): the pack the model reads, and ref -> {label, url, item_id} for linking sources."""
    from . import soul, views
    now = datetime.now(views.TZ) if getattr(views, "TZ", None) else datetime.now()
    b = views.bootstrap(con)
    refs, L = {}, []
    L.append(f"NOW: {now.strftime('%A %d %B %Y, %H:%M')} ({USER.tz}). {USER.name}, {USER.role_short} of {USER.company}.")

    L.append(f"\n## {USER.first}'s priorities and how to read people (excerpts)")
    L.append("Strategy and weights: " + _read("memory/context/strategy.md", 1800))
    L.append("Me: " + _read("memory/context/me.md", 1200))
    L.append(soul.block("todo", level=3))
    prefs = (db.ASSIST / "memory" / "context" / "preferences.md")
    if prefs.exists():
        m = re.search(r"## Calendar and meetings.*?(?=\n## )", prefs.read_text(), re.S)
        if m:
            L.append("Calendar and meeting preferences (follow when proposing times, invites or meetings): " + _clip(m.group(0), 1400))

    L.append("\n## Calendar: today and the next working day (K = meeting)")
    try:
        from . import prep
        upcoming = prep.upcoming(con, 2)
    except Exception:
        upcoming = []
    for i, e in enumerate(upcoming[:16], 1):
        ref = f"K{i}"
        refs[ref] = {"label": e["subject"], "url": "#/prep?event=" + urllib.parse.quote(str(e["event_id"]), safe=""), "event_id": e["event_id"]}
        L.append(f"[{ref}] {e['local']} · {e['subject']} · with {', '.join(e.get('attendees') or [])[:160]} · brief: {'ready' if e.get('brief') else 'NONE'}")

    L.append(f"\n## Mail waiting on {USER.first}, last 10 days: it asks {USER.him} for something and {USER.he} has not answered (E = email; reply_to is the id "
             "for an Outlook reply draft)")
    from . import replies
    try:
        inbox = replies.inbox(con, days=10)
    except Exception:
        inbox = []
    for m in [m for m in inbox if m["needs_reply"]][:25]:
        ref = f"E{m['id']}"
        refs[ref] = {"label": f"Mail: {m['subject']}", "url": f"#/mail?open={m['id']}", "item_id": m["id"]}
        L.append(f"[{ref}] {m['received_at'][:16]} from {m['from_name']} <{m['from_address']}> · {m['subject']} · reply_to={m['graph_id']}"
                 f" · {m['reply_why']}\n    {m['preview']}")
    # the rest of the unanswered mail from colleagues (FYIs, group mail, copied, addressed to someone else): background only
    fyi = [m for m in inbox if not m["needs_reply"] and m["reply_why"] and m["latest"]][:15]
    if fyi:
        L.append(f"\n## Other recent mail {USER.first} is on: CONTEXT ONLY, not waiting on {USER.him} (never propose replying to these)")
    for m in fyi:
        ref = f"E{m['id']}"
        refs[ref] = {"label": f"Mail: {m['subject']}", "url": f"#/mail?open={m['id']}", "item_id": m["id"]}
        L.append(f"[{ref}] {m['received_at'][:10]} from {m['from_name']} · {m['subject']} · {m['reply_why']} · {_clip(m['preview'], 160)}")

    L.append(f"\n## Direct and group messages where the last word is not {USER.first}'s, last 4 days (M = message; only those marked "
             f"ASKS {USER.FIRST} wait on {USER.him}, the others are context)")
    since = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute("SELECT m.item_id, m.source_id, m.conversation_name, m.conversation_kind, m.author, m.sent_at, m.body_text, m.web_link "
                       "FROM chat_messages m WHERE m.sent_at >= ? AND m.conversation_kind IN ('dm','group','meeting') ORDER BY m.sent_at", (since,)).fetchall()
    last = {}
    for r in rows:
        last[(r["source_id"], r["conversation_name"])] = r
    n = 0
    for (src, conv), r in sorted(last.items(), key=lambda kv: kv[1]["sent_at"], reverse=True):
        if (r["author"] or "").lower().startswith("sam") or n >= 20:
            continue
        n += 1
        ref = f"M{r['item_id']}"
        refs[ref] = {"label": f"{src.title()}: {conv}", "url": r["web_link"] or f"#/messages?open={r['item_id']}", "item_id": r["item_id"]}
        ok, why = replies.chat_asked(r)
        L.append(f"[{ref}] {src} · {conv} · {r['sent_at'][:16]} · {'ASKS ' + USER.FIRST if ok else 'context: ' + why} · {r['author']}: {_clip(r['body_text'], 700)}")

    # the addresses of the people Sam writes to most (last 60 days), so a new message is addressed rather than [FILL: recipient]
    since60 = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = {}
    for r in con.execute("SELECT to_json, cc_json FROM mail_messages WHERE folder='sentitems' AND sent_at >= ?", (since60,)):
        for x in json.loads(r["to_json"] or "[]") + json.loads(r["cc_json"] or "[]"):
            a_ = (x.get("address") or "").lower()
            if a_ and not SAM.search(a_):
                count[a_] = (count.get(a_, (0, x.get("name") or a_))[0] + 1, x.get("name") or a_)
    top = sorted(count.items(), key=lambda kv: -kv[1][0])[:30]
    if top:
        L.append(f"\n## Addresses of the people {USER.first} writes to most (use these in \"to\"; never guess one)")
        L.append("; ".join(f"{n} <{a_}>" for a_, (_, n) in top))

    try:   # how Sam actually acts: the action types and channels he uses, and with whom (assist/action_profile.py)
        from . import action_profile
        L.append("\n## " + action_profile.context_lines(con))
    except Exception:
        pass

    # files and folders people shared as links, newest first: the originals Sam opens (decks, docs, folders)
    files, seen = [], set()
    for r in con.execute("SELECT author, conversation_name, sent_at, links_json FROM chat_messages WHERE sent_at >= ? AND links_json LIKE '%http%' "
                         "ORDER BY sent_at DESC", ((datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),)):
        for l in json.loads(r["links_json"] or "[]"):
            u = (l.get("url") or "").strip()
            key = re.sub(r"[?&]e=\w+", "", u)
            if re.search(r"sharepoint\.com|1drv\.ms|teams\.microsoft\.com/l/file|docs\.google\.com", u) and key not in seen:
                seen.add(key)
                files.append((l.get("title") or u.split("/")[-1].split("?")[0], u, r["author"], r["conversation_name"], r["sent_at"]))
    # a shared folder: list the files Assist knows inside it (SharePoint), newest first, ahead of the folder itself
    inside = []
    for t, u, who, conv, ts in [f for f in files if ":f:" in f[1]]:
        for r in con.execute("SELECT subject, url, ts FROM items WHERE source_id='sharepoint' AND kind='doc' AND thread LIKE ? ORDER BY ts DESC LIMIT 6",
                             ("%/" + t,)):
            if r["url"] and r["url"] not in {x[1] for x in inside}:
                inside.append((r["subject"], r["url"], who, f"{conv} (file in the shared folder {t})", r["ts"]))
    files = inside + files
    if files:
        L.append("\n## Files shared as links, last 10 days (F = file; link the original in any action about it; prefer a file over the folder it sits in)")
        for i, (t, u, who, conv, ts) in enumerate(files[:30], 1):
            ref = f"F{i}"
            refs[ref] = {"label": f"File: {_clip(t, 80)}", "url": u}
            L.append(f"[{ref}] {t} · shared by {who} in {conv} · {ts[:16]} · url: {u}")

    # Sam's working documents of the last 30 days (his own files on this Mac, SharePoint/OneDrive, attachments he received):
    # a deliverable he owes often already exists as a draft, and the create action should build on it ("doc")
    since30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs = [(f"{'lf' if r['source_id'] == 'local' else 'sp'}-{r['id']}", r["subject"], "on this Mac" if r["source_id"] == "local" else "SharePoint/OneDrive", r["ts"])
            for r in con.execute("SELECT id, source_id, subject, ts FROM items WHERE kind='doc' AND source_id IN ('local','sharepoint') AND ts >= ? "
                                 "AND (subject LIKE '%.pptx' OR subject LIKE '%.docx' OR subject LIKE '%.xlsx' OR subject LIKE '%.pdf') ORDER BY ts DESC LIMIT 40", (since30,))]
    docs += [(f"ma-{r['id']}", r["name"], f"attachment from {r['from_name']}", r["ts"]) for r in con.execute(
        "SELECT a.id, a.name, m.from_name, COALESCE(m.received_at, m.sent_at) AS ts FROM mail_attachments a JOIN mail_messages m ON m.item_id=a.item_id "
        "WHERE a.is_inline=0 AND COALESCE(m.received_at, m.sent_at) >= ? AND (a.name LIKE '%.pptx' OR a.name LIKE '%.docx' OR a.name LIKE '%.xlsx') "
        "ORDER BY ts DESC LIMIT 20", (since30,))]
    seen_names = set()
    docs = [d for d in sorted(docs, key=lambda d: d[3], reverse=True) if not (d[1].lower() in seen_names or seen_names.add(d[1].lower()))][:40]
    if docs:
        L.append(f"\n## {USER.first}'s working documents, last 30 days (D = document; its id goes in a create action's \"doc\" when the deliverable should build on it)")
        for i, (did, name, where, ts) in enumerate(docs, 1):
            ref = f"D{i}"
            refs[ref] = {"label": f"Document: {_clip(name, 80)}", "url": f"#/documents?open={did}", "doc": did}
            L.append(f"[{ref}] {name} · {where} · {ts[:10]} · id {did}")

    # the shared register of open items (assist/loops.py): promises, waits and pending decisions, with real start dates
    from . import loops
    # possible duplicates are left out: the item they repeat is listed
    open_ = [l for l in loops.listing(con, include_closed_days=0) if l["status"] == "open" and l["kind"] != "reply" and l.get("suggestion") != "duplicate"]
    for kind, head in (("promise", f"What {USER.first} owes (L)"), ("waiting", f"Owed to {USER.first}: candidates to chase (L)"), ("decision", "Decisions pending (L)")):
        rows = sorted([l for l in open_ if l["kind"] == kind], key=lambda l: (l.get("due") or "9999", l.get("origin_at") or ""))
        if rows:
            L.append(f"\n## {head} · DECIDE OR DROP marks items past their age limit")
        for l in rows[:40]:
            ref = f"L{l['id']}"
            refs[ref] = {"label": f"Open item: {_clip(l['title'], 80)}", "url": f"#/loops?open={l['id']}", "loop_id": l["id"]}
            L.append(loops.line(l, ref))

    L.append("\n## Initiatives (status · next milestone)")
    for p in b.get("projects", [])[:12]:
        L.append(f"- {p['name']} ({p.get('status') or '—'}, weight {p.get('weight')}): next {_clip(p.get('milestone'), 160)}")

    done = con.execute("SELECT title, status FROM todo WHERE status IN ('done','dismissed') AND updated_at >= ? ORDER BY updated_at DESC LIMIT 40",
                       ((datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchall()
    if done:
        L.append(f"\n## Already handled or dismissed by {USER.first} this week — do not propose these again")
        L += [f"- ({r['status']}) {r['title']}" for r in done]
    from . import feedback
    lessons = feedback.action_lessons(con)
    if lessons:
        L.append("\n" + lessons)
    return "\n".join(L), refs


INSTRUCTIONS = f"""You are {USER.first}'s chief of staff. From the context below, produce {USER.first}'s prioritised action list for right now:
the {MAX_ITEMS} or fewer things most worth {USER.his} attention today, ranked. Think like a {USER.role_short}'s chief of staff: what is someone
blocked on, what does the CEO/board/a customer/a partner need, what date passes today or tomorrow, what meeting is coming
and needs preparing, what was promised and is slipping, what to chase. Prefer fewer, sharper items. Skip noise.

Read the context as the company soul says: statements are claims; when an item rests on one person's word or a
transcript, say so in "why". Rank as the {USER.role_short} soul says: work only the {USER.role_short} can do (strategy, the CEO and board, pricing,
partner terms, org design) before work a direct report could own; for the latter, the first action delegates it.

Deliverables: when someone asked {USER.first} to produce something (a plan, proposal, business case, analysis, budget, org design,
deck, one-pager) or {USER.he} promised one, the item is category "content" and its FIRST action is a "create" action that builds the
document itself, not a message saying it will come. Choose the format by how it will be used: pptx when it will be presented
or walked through in a meeting, docx when it is read, sent or signed off, xlsx for a model, budget or numbers to work through
(a plan with a budget can be a pptx plus an xlsx: two create actions). Give a real outline drawn from the context: what was
asked (cover every question in the request), what is known, the options and the decision asked for. Put the request's ref
(E, M or L) in refs so it travels with the action. If one of {USER.first}'s working documents (D) is an earlier version of the same
deliverable, set "doc" to it. A message sending the result is a later step, only when someone is waiting for it.

What is NOT an action:
- Replying to mail or messages that do not ask {USER.first} for anything. Only mail under "Mail waiting on {USER.first}" and messages marked
  ASKS {USER.FIRST} can be the reason for a reply item. Mail {USER.he} is copied on, group announcements, FYIs and mail addressed to someone
  else ("CONTEXT ONLY", "context:") are background for other items, never a reply to propose.
- Each open item marked DECIDE OR DROP on its own. Those are old or past their date. If they matter, propose at most ONE item
  "Decide or drop …" naming the two to four that most need a call; an item whose date has passed is not urgent. Only raise a
  stale item on its own when someone is blocked on it now.
- Preparing a meeting whose brief is "ready": the brief already carries the agenda and asks. Propose prep only when {USER.first} must
  produce something for it (a deck, a document, a decision) or the brief is NONE.

Return ONLY a JSON array (no prose, no code fence). Each element:
{{"title": "short imperative, e.g. 'Reply to Arden on MCP seat licensing'",
  "why": "one or two sentences: why now, what happens if ignored; name who is waiting",
  "priority": "now" | "today" | "this_week",
  "category": "reply" | "content" | "chase" | "check" | "decide" | "prep" | "other",
  "effort_min": integer estimate,
  "due": "YYYY-MM-DD" or null,
  "refs": ["E123", "L45", ...]  // the [refs] this item is based on; at least one
  "closes": ["L45"]  // the refs this item FINISHES when {USER.first} does it: the mail or message it answers, the promise it delivers,
                     // the decision it takes, the wait it chases. Leave out refs that are only background. May be empty.
  "actions": [ ... 1 to 3 concrete next steps ... ]}}

Action shapes (use exactly these keys; nothing is sent, {USER.first} reviews every draft):
- Every action may carry "links": [{{"label": "Deck: 20261008_Combined_Offering_Alignment", "url": "<exact url from an F line or a source>"}}].
  When an action asks {USER.first} to read, check, review, approve, present or forward a document, deck or folder, it MUST link it, so
  {USER.first} can open the real file in one click. Copy the URL exactly from the context; never invent or shorten one.
- Email reply/new: {{"type":"email","label":"Reply to Arden","to":["arden.foster@acme.example"],"subject":"…","body":"…","reply_to":"<reply_to id from the E line, for replies>",
  "intent":"for replies: what the reply must say, in one or two sentences, e.g. 'Agree to defer the 2024 claim; ask Bryn for the 2025/26 topics by Fri 16 Oct'"}}
  ({USER.first}'s reply writer drafts the final text from the full thread with this intent; "body" is a short first draft)
- Teams message:  {{"type":"teams","label":"Message Gray on Teams","to":["gray.selby@acme.example"],"message":"…"}}
- Slack message:  {{"type":"slack","label":"Nudge Rowan on Slack","user":"Rowan Lowell","message":"…"}}
- Create a deliverable: {{"type":"create","label":"Build the P&E structure deck","app":"cowork","format":"pptx"|"docx"|"xlsx",
  "title":"2026-27 Product & Engineering structure","audience":"Milo, Friday 1:1",
  "outline":["Slide or section: what goes in it", "… 5 to 10 entries"],
  "doc":"<id of a D document to build on, when one is the same piece of work; else leave out>",
  "prompt":"what it must achieve for the audience, the key points and numbers to cover, what to leave out"}}
  Claude Cowork builds the file from a context pack (the request in full, meetings, documents, people) that SleePO gathers
  when {USER.first} presses the button, so the prompt and outline set the shape; they need not repeat the whole context.
- Think/draft in Claude: {{"type":"draft","label":"Think through the pricing options","app":"chat","prompt":"…"}}
Match how {USER.first} works (the "How {USER.first} actually acts" section): use the channel {USER.he} uses with that person (Teams for someone {USER.he}
messages on Teams, email for someone {USER.he} emails), keep drafts near {USER.his} usual length for that channel, prefer the action
types {USER.he} actually takes, and only propose a meeting when a message will not do.
One message action = one recipient: its "label", "to"/"user" and greeting name the same person. When an item needs
messages to several people (ask Finley for the draft, then tell Milo the date), give one message action per person,
in the order {USER.first} should send them; never address one person's message to someone else.
Only use email addresses that appear in the context; otherwise leave "to" empty and write [FILL: recipient]. Write drafts in
{USER.first}'s voice: short, direct, decision-first, no filler. Use [FILL: …] for anything you do not know. For a "check" or "decide"
item an action may be a draft prompt. Never invent facts; never promise dates on {USER.first}'s behalf without [FILL: date].
The [E12]/[L45]-style codes are for "refs" only: never write them in titles, "why" or drafts — name the thing instead (e.g. "your commitment to send the deck").
"""


def _parse(text):
    m = re.search(r"\[[\s\S]*\]", text or "")
    if not m:
        raise ValueError("no JSON array in the model output")
    items = json.loads(m.group(0))
    return [x for x in items if isinstance(x, dict) and x.get("title")][:MAX_ITEMS]


def _clean_actions(acts, known_urls=None, known_docs=None):
    ok = {"create", "edit", "draft", "email", "teams", "slack"}
    out = []
    for a in acts or []:
        if isinstance(a, dict) and a.get("type") in ok and a.get("label"):
            for k in ("to", "cc"):   # recipients are always a list (a writer sometimes returns one string)
                v = a.get(k)
                if isinstance(v, str):
                    a[k] = [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]
                elif v is not None and not isinstance(v, list):
                    a.pop(k)
            # links to the documents the action is about: only URLs that appear in the context (no invented links)
            a["links"] = [{"label": str(l.get("label") or "Open")[:90], "url": l["url"]} for l in (a.get("links") or [])
                          if isinstance(l, dict) and isinstance(l.get("url"), str) and l["url"].startswith("https://")
                          and (known_urls is None or l["url"] in known_urls)][:3]
            if not a["links"]:
                a.pop("links")
            if a["type"] == "email":
                a["to"] = [x for x in a.get("to") or [] if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", x)]
            if a.get("format") not in ("pptx", "docx", "xlsx", "md"):
                a.pop("format", None)
            a["outline"] = [str(x)[:300] for x in a.get("outline") or [] if isinstance(x, (str, int, float)) and str(x).strip()][:12] if isinstance(a.get("outline"), list) else []
            if not a["outline"]:
                a.pop("outline")
            if a.get("doc") and not (isinstance(a["doc"], str) and re.fullmatch(r"(lf|sp|ma|kb)-\d+", a["doc"]) and (known_docs is None or a["doc"] in known_docs)):
                a.pop("doc")   # only documents that were in the context
            for k in ("title", "audience", "intent"):
                if k in a:
                    a[k] = str(a[k])[:300] if a[k] else None
                    if not a[k]:
                        a.pop(k)
            out.append(a)
    return out[:3]


def _keys(sources):
    """What an action is about, as comparable keys: the open items (L) and the messages (I) it finishes when it says so,
    else everything it cites."""
    s = _targets(sources) or sources
    return {f"L{x['loop_id']}" for x in s if x.get("loop_id")} | {f"I{x['item_id']}" for x in s if x.get("item_id")}


def loops_for(con, sources):
    """Ids of the open-items register entries an action is about: its L refs, and the reply loops of the mail and
    messages it cites (E and M refs)."""
    ids = {s["loop_id"] for s in sources if s.get("loop_id")}
    items = [s["item_id"] for s in sources if s.get("item_id")]
    if items:
        q = ",".join("?" * len(items))
        ids |= {r[0] for r in con.execute(f"SELECT id FROM loops WHERE fact_type IN ('mail','chat') AND fact_id IN ({q})", items)}
    return ids


HANDLED_DAYS = 7   # how long an action Sam marked done or dismissed keeps a re-proposal of it hidden


def _handled_since():
    return (datetime.now(timezone.utc) - timedelta(days=HANDLED_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _handled(con):
    """What the actions Sam marked done or dismissed in the last 7 days were about: a reworded re-proposal of the same
    thing stays hidden instead of coming back as new."""
    return [k for k in (_keys(json.loads(r["sources_json"] or "[]")) for r in con.execute(
        "SELECT sources_json FROM todo WHERE status IN ('done','dismissed') AND updated_at >= ?", (_handled_since(),))) if k]


def store(con, items, refs, run_id=None, known_urls=None):
    now = db.now()
    keep = set()
    handled, recent = _handled(con), _handled_since()
    for rank, x in enumerate(items, 1):
        tid = db.fingerprint(x["title"])   # the id is the title: next week's "Prep for the weekly call" is this week's row
        keep.add(tid)
        closes = set(x.get("closes") or []) if isinstance(x.get("closes"), list) else set()
        sources = [{"ref": r, **refs[r], "closes": r in closes} for r in dict.fromkeys([*(x.get("refs") or []), *closes]) if r in refs]
        row = con.execute("SELECT status, snooze_until, updated_at FROM todo WHERE id=?", (tid,)).fetchone()
        # Sam's done or dismissed holds for HANDLED_DAYS, like a reworded re-proposal; after that the same title is a new action
        status = row["status"] if row and row["status"] in ("done", "dismissed") and (row["updated_at"] or "") >= recent else \
            ("snoozed" if row and row["status"] == "snoozed" and (row["snooze_until"] or "") > now else "open")
        k = _keys(sources)
        if status == "open" and k and any(len(k & h) * 2 >= len(k) for h in handled):
            status = "superseded"   # the same thing (at least half its sources) Sam marked done or dismissed this week, reworded
        con.execute("INSERT INTO todo (id, run_id, rank, priority, category, title, why, effort_min, due, sources_json, actions_json, status, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id, rank=excluded.rank, priority=excluded.priority, "
                    "category=excluded.category, why=excluded.why, effort_min=excluded.effort_min, due=excluded.due, sources_json=excluded.sources_json, "
                    "actions_json=excluded.actions_json, status=excluded.status, "
                    "created_at=CASE WHEN todo.status IN ('done','dismissed') AND excluded.status NOT IN ('done','dismissed') "
                    "THEN excluded.created_at ELSE todo.created_at END, "   # an old done title proposed again is new
                    "updated_at=CASE WHEN excluded.status IN ('done','dismissed') THEN todo.updated_at ELSE excluded.updated_at END",   # keep when Sam acted
                    (tid, run_id, rank, x.get("priority") if x.get("priority") in ("now", "today", "this_week") else "today",
                     x.get("category") or "other", x["title"].strip(), x.get("why"), x.get("effort_min") if isinstance(x.get("effort_min"), int) else None,
                     x.get("due"), json.dumps(sources), json.dumps(_clean_actions(x.get("actions"), known_urls, {r["doc"] for r in refs.values() if r.get("doc")})), status, now, now))
    # open items the new list no longer carries are superseded (hidden), never deleted
    for r in con.execute("SELECT id FROM todo WHERE status='open'").fetchall():
        if r["id"] not in keep:
            con.execute("UPDATE todo SET status='superseded', updated_at=? WHERE id=?", (now, r["id"]))
    con.commit()
    return len(items)


def _run_model(prompt_text, cwd, timeout=420, purpose=None):
    """Kept for the modules that import it (loops, briefgen, initiatives, meeting prep). Goes through llm.run, which logs
    purpose, model, tokens and cost, and runs with no tools."""
    from . import llm
    return llm.run(prompt_text, cwd, timeout=timeout, purpose=purpose)


def generate(con, log=print):
    text, refs = context(con)
    run = db.start_run(con, "assist:todo", PROMPT_VERSION, None, {"chars": len(text), "refs": len(refs)})
    con.commit()   # never hold a write transaction while the model runs (minutes): it would lock the database
    try:
        out = _run_model(INSTRUCTIONS + "\n\n# CONTEXT\n" + text, db.ASSIST, purpose="todo")
        items = _parse(out)
    except Exception as e:
        db.finish_run(con, run, output_json={"error": str(e)[-400:]})
        con.commit()
        raise
    known = set(re.findall(r"https://[^\s<>\)\]\"']+", text)) | {r["url"] for r in refs.values() if str(r.get("url", "")).startswith("https://")}
    n = store(con, items, refs, run, known_urls=known)
    db.finish_run(con, run, output_json={"items": n})
    con.commit()
    log(f"actions: {n} items")
    return n


def job_status(con):
    """Status of the latest generation, read from the runs table so it survives server reloads."""
    r = con.execute("SELECT id, started_at, finished_at, output_json FROM runs WHERE agent='assist:todo' ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    out = json.loads(r["output_json"] or "{}")
    stale = (datetime.now(timezone.utc) - datetime.strptime(r["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() > 900
    running = not r["finished_at"] and not stale
    ok = None if running else (False if out.get("error") or not r["finished_at"] else True)
    return {"running": running, "ok": ok, "started": r["started_at"], "finished": r["finished_at"],
            "error": out.get("error") or (None if r["finished_at"] or running else "the run stopped without finishing"), "count": out.get("items")}


def start(cwd=None):
    """Run `assist.cli todo` as its own process (detached), so a server reload cannot kill it."""
    con = db.connect()
    try:
        j = job_status(con)
    finally:
        con.close()
    if j and j["running"]:
        return False
    py = os.path.expanduser("~/.assist/venv/bin/python")
    subprocess.Popen([py, "-m", "assist.cli", "todo"], cwd=str(db.ASSIST), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    return True


def _settle(con, now):
    """Open actions whose open items have all been closed since (Sam replied, it was found done, he closed or dropped it
    on Open items) are superseded at once rather than at the next re-prioritise. An item closed because a newer message
    in its thread became the one to answer does not count: the conversation is still waiting on Sam."""
    for r in con.execute("SELECT id, sources_json FROM todo WHERE status IN ('open','snoozed')").fetchall():
        sources = json.loads(r["sources_json"] or "[]")
        t = _targets(sources)
        ids = loops_for(con, sources if t is None else t)
        if not ids:
            continue
        q = ",".join("?" * len(ids))
        live = con.execute(f"SELECT COUNT(*) FROM loops WHERE id IN ({q}) AND (status IN ('open','snoozed') OR closed_by='auto:thread')",
                           list(ids)).fetchone()[0]
        if not live:
            con.execute("UPDATE todo SET status='superseded', updated_at=? WHERE id=?", (now, r["id"]))


def listing(con):
    now = db.now()
    con.execute("UPDATE todo SET status='open' WHERE status='snoozed' AND snooze_until <= ?", (now,))
    try:
        _settle(con, now)
    except Exception:   # the register is optional here: never let it break the list
        pass
    con.commit()
    rows = con.execute("SELECT * FROM todo WHERE status IN ('open','snoozed') OR (status IN ('done','dismissed') AND updated_at >= ?) ORDER BY "
                       "CASE status WHEN 'open' THEN 0 WHEN 'snoozed' THEN 1 ELSE 2 END, "
                       "CASE priority WHEN 'now' THEN 0 WHEN 'today' THEN 1 ELSE 2 END, rank",
                       ((datetime.now(timezone.utc) - timedelta(hours=18)).strftime("%Y-%m-%dT%H:%M:%SZ"),)).fetchall()
    last = con.execute("SELECT MAX(finished_at) FROM runs WHERE agent='assist:todo' AND output_json NOT LIKE '%error%'").fetchone()[0]
    return {"items": [{**{k: r[k] for k in r.keys() if k not in ("sources_json", "actions_json")},
                       "sources": json.loads(r["sources_json"] or "[]"), "actions": json.loads(r["actions_json"] or "[]")} for r in rows],
            "generated_at": last, "job": job_status(con)}


CHASE_WAIT_DAYS = 5


def _targets(sources):
    """The sources an action finishes. Actions written since todo-2026-10-11 say so ("closes"); for older ones, None."""
    if any("closes" in s for s in sources):
        return [s for s in sources if s.get("closes")]
    return None


def set_status(con, tid, status, snooze_until=None):
    """Done here is done everywhere: the open items the action finishes ("closes") close with it (what Sam owes: replies,
    promises, decisions), and the waits he chased rest for a few days. Items it only cites as background stay open.
    Reopening the action reopens what it closed. Dismissing touches nothing."""
    if status not in ("open", "done", "dismissed", "snoozed"):
        raise ValueError("bad status")
    row = con.execute("SELECT title, category, sources_json, status FROM todo WHERE id=?", (tid,)).fetchone()
    con.execute("UPDATE todo SET status=?, snooze_until=?, updated_at=?, touched_at=? WHERE id=?",
                (status, snooze_until if status == "snoozed" else None, db.now(), db.now(), tid))
    if row and (status == "done" or (status == "open" and row["status"] == "done")):
        _carry_to_loops(con, tid, row, status)
    con.commit()


def _carry_to_loops(con, tid, row, status):
    from . import loops
    ref = {"label": f"Action: {_clip(row['title'], 80)}", "url": f"#/actions?open={tid}"}
    sources = json.loads(row["sources_json"] or "[]")
    t = _targets(sources)
    ids = loops_for(con, sources if t is None else t)
    if not ids:
        return
    q = ",".join("?" * len(ids))
    if status == "open":   # reopened: undo what this action closed
        for l in con.execute(f"SELECT id FROM loops WHERE id IN ({q}) AND closed_by='sam' AND close_ref LIKE ?", [*ids, f"%#/actions?open={tid}%"]).fetchall():
            loops.set_status(con, l["id"], "open")
        return
    if row["category"] == "prep" and t is None:   # an older prep action: preparing a meeting is not delivering what it is about
        return
    until = (datetime.now(timezone.utc) + timedelta(days=CHASE_WAIT_DAYS)).strftime("%Y-%m-%dT08:00:00Z")
    for l in con.execute(f"SELECT id, kind, title FROM loops WHERE id IN ({q}) AND status IN ('open','snoozed')", list(ids)).fetchall():
        if t is None and not (   # an older action did not say what it finishes: only the obvious, never background
                (l["kind"] == "reply" and row["category"] in ("reply", "decide")) or loops.similar(l["title"], row["title"])):
            continue
        if l["kind"] in ("reply", "promise", "decision"):
            loops._close(con, l["id"], "done", "sam", f"Done in Actions: {_clip(row['title'], 160)}", ref)
        elif row["category"] == "chase":   # they still owe it; give them a few days before it comes back
            con.execute("UPDATE loops SET status='snoozed', snooze_until=?, suggestion=NULL, suggestion_note=?, updated_at=? WHERE id=?",
                        (until, f"Chased from Actions on {db.now()[:10]}.", db.now(), l["id"]))
    loops.flag(con)
