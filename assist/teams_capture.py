"""The Teams pull, without the model retyping messages (Sam, 17 Nov 2026: "Is there a way to make the Teams and Slack
synchronization much faster? It just takes a long time").

The old pull had a Claude run read every message through the Microsoft 365 connector and then write each one out again,
verbatim, into the ingest bundle: its time followed its output (17 Nov 2026: 125 messages, 33,000 output tokens, 4 minutes),
and it kept the search's 250-character clips of long messages. Now the run only calls the tools (pages through
chat_message_search, reads each chat message with read_resource, lists the chats and channels to name them) and answers in
a line; a PostToolUse hook (assist/capture_hook.py) keeps every result as it comes back, and this module builds the
chat_messages records from those raw results in code and writes the bundle (pulls, chat_messages, gaps). The run is
read only and holds only those four tools, and it runs from the scratch folder (the project's long CLAUDE.md is not loaded).
Slack is pulled side by side by its own run (assist/slack_pull.py; both started by api.teams_slack_pull).

Names: a direct message is "1:1 chat <the other person>", a group chat "Group chat: <topic>" or "Group chat: <the others>",
a meeting chat "Meeting chat: <topic>", a channel "Teams channel: <its name>", from teams_list_chats and teams_list_channels;
without them, the name the conversation already has. Channel posts cannot be read one by one (Teams answers "not found" for
replies), so their text is the search's; they are Slack Bridge relays and notices, short. Bots and notifications are noise.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from . import db, profile

HOOK = Path(__file__).with_name("capture_hook.py")
TOOLS = ["chat_message_search", "read_resource", "teams_list_chats", "teams_list_channels"]
SCRATCH = Path("/tmp/assist-pull")   # the pulls' scratch folder, outside OneDrive; a capture is deleted once parsed
PROMPT_VERSION = "teams-capture-2026-11-17"
# The run only calls tools, so the light model does it (17 Nov 2026, the same day pulled both ways: Haiku 91 s and $0.09,
# Sonnet 72 to 121 s and $0.58 to $0.80; a quiet pull about 15 s on either, $0.01 against $0.19). Settings
# llm_model_pull-teams overrides it.
MODEL = "haiku"


def model(con):
    r = con.execute("SELECT value FROM settings WHERE key='llm_model_pull-teams'").fetchone()
    return (r[0] if r and r[0] else MODEL)
OVERLAP_MIN = 30      # the next pull starts this long before the last one ended (the search index lags a little)
FIRST_DAYS = 3        # with no pull on record
RELAY = re.compile(r"^\s*\[slack\]\s*<([^>]+)>", re.I)
BOT = re.compile(r"\b(?:jira|confluence|gitlab|github|bitbucket|sonar\w*|jenkins|acme development|bot|notifications?|alerts?|"
                 r"zapier|statuspage|workflows?|power automate|forms)\b", re.I)
SKIP_ATTACH = re.compile(r"^(?:messageReference|application/vnd\.microsoft\.card|application/vnd\.microsoft\.teams\.card)", re.I)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def windows(con, window=None, now=None):
    """The search windows: since the last complete Teams pull (less OVERLAP_MIN), or for a backfill (window = (from, to) as
    YYYY-MM-DD) one window per day, since one search pages at most 1,000 results."""
    now = now or datetime.now(timezone.utc)
    if window:
        a = datetime.fromisoformat(window[0]).replace(tzinfo=timezone.utc)
        b = min(datetime.fromisoformat(window[1]).replace(tzinfo=timezone.utc), now)
        out = []
        while a < b:
            nxt = min(a + timedelta(days=1), b)
            out.append((_iso(a), _iso(nxt)))
            a = nxt
        return out
    last = con.execute("SELECT MAX(finished_at) FROM pulls WHERE source_id='teams' AND complete=1").fetchone()[0]
    start = (datetime.fromisoformat(last.replace("Z", "+00:00")) - timedelta(minutes=OVERLAP_MIN)) if last else now - timedelta(days=FIRST_DAYS)
    return [(_iso(start), None)]


def prompt(wins):
    """What the run does: call the tools, nothing else."""
    backfill = not (len(wins) == 1 and not wins[0][1])
    if not backfill:
        search = f"chat_message_search with query '*', afterDateTime '{wins[0][0]}' and limit 25"
    else:
        search = ("chat_message_search with query '*' and limit 25, once for each of these windows: "
                  + "; ".join(f"afterDateTime '{a}' beforeDateTime '{b}'" for a, b in wins))
    return ("TEAMS pull, read only, through the Microsoft 365 connector. SleePO keeps every result these tools return and builds the "
            "messages from them itself: do NOT copy, list or summarise messages, write files, run commands or use any other tool.\n"
            f"1. {search}: offset 0, then each nextOffset until a page has none. Read every page of every window.\n"
            "2. read_resource on the uri of every result whose uri starts with teams:///chats/, except results from Slack Bridge. Make "
            "up to 20 of these calls at once in one turn. Results whose uri starts with teams:///teams/ (channel posts) need no read.\n"
            + ("3. teams_list_chats with limit 25, then its nextCursor pages until every chatId from step 1 has appeared (newest first; "
               "at most 5 pages). It can run alongside step 2.\n" if backfill else
               "3. teams_list_chats once with limit 25, in the same turn as the first search (the newest chats; it names them).\n")
            + "4. teams_list_channels once for each team id in the channel results (the id after teams:///teams/ in their uri).\n"
            "When done, answer with one line: windows, pages, results and chat messages read. If a tool fails (sign-in, permission), "
            "say which and stop.")


def hook_settings():
    """The --settings JSON that installs the capture hook for this run only."""
    import sys
    py = os.path.expanduser("~/.assist/venv/bin/python")
    py = py if os.path.exists(py) else sys.executable
    cmd = f"{shlex.quote(py)} {shlex.quote(str(HOOK))}"
    return json.dumps({"hooks": {"PostToolUse": [{"matcher": "mcp__claude_ai_Microsoft_365__.*",
                                                  "hooks": [{"type": "command", "command": cmd, "timeout": 30}]}]}})


# ---- reading the captured results

def _texts(x):
    """The text parts of a tool result, however the hook was handed it (a string, MCP content blocks, a wrapper)."""
    if x is None:
        return []
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        return [t for y in x for t in _texts(y)]
    if isinstance(x, dict):
        if isinstance(x.get("text"), str) and x.get("type", "text") == "text":
            return [x["text"]]
        for k in ("content", "result", "structuredContent"):
            if k in x:
                return _texts(x[k])
        return [json.dumps(x)]
    return []


def _objs(text):
    """Every JSON object in a result text: the connector returns objects one after another ("{…}{…}{…}"), or an array."""
    dec, i, out, text = json.JSONDecoder(), 0, [], text or ""
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text):
            break
        try:
            o, i = dec.raw_decode(text, i)
        except ValueError:
            break
        if isinstance(o, dict):
            out.append(o)
        elif isinstance(o, list):
            out += [y for y in o if isinstance(y, dict)]
    return out


def load(folder):
    """The captured calls, oldest first: [{tool, input, objs}]."""
    calls = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            c = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        calls.append({"tool": c.get("tool"), "input": c.get("input") or {}, "objs": [o for t in _texts(c.get("response")) for o in _objs(t)]})
    return calls


def _ts(s):
    return f"{s[:19]}Z" if s and len(s) >= 19 else None


def _chat_of_uri(uri):
    m = re.search(r"teams:///chats/([^/]+)/messages", uri or "")
    return unquote(m.group(1)) if m else None


def _me(name="", email=""):
    return profile.mentions_me(f"{name or ''} {email or ''}")


def build(calls, con):
    """Records for chatsync.store_record and what the pull saw: {records, available, complete, errors, searches, reads}.
    con is read only (the names conversations already have, and older message ids to keep)."""
    results, full, chats, channels, ends, errors = {}, {}, {}, {}, {}, []
    searches = reads = 0
    for c in calls:
        errs = [o for o in c["objs"] if o.get("code") and o.get("message") and not o.get("id")]
        if errs:
            errors.append(f"{c['tool']}: {errs[0]['code']}")
            continue
        if c["tool"] == "chat_message_search":
            searches += 1
            q = (c["input"].get("afterDateTime"), c["input"].get("beforeDateTime"), c["input"].get("query"), c["input"].get("hasAttachment"))
            more = any("nextOffset" in o for o in c["objs"])
            ends[q] = ends.get(q, False) or not more
            for o in c["objs"]:
                if o.get("uri") and o.get("id"):
                    results[(o.get("chatId"), str(o["id"]))] = o
        elif c["tool"] == "read_resource":
            for o in c["objs"]:
                if o.get("id") and "body" in o:
                    reads += 1
                    full[(o.get("chatId") or _chat_of_uri(c["input"].get("uri")), str(o["id"]))] = o
        elif c["tool"] == "teams_list_chats":
            for o in c["objs"]:
                if o.get("id") and o.get("chatType"):
                    chats[o["id"]] = o
        elif c["tool"] == "teams_list_channels":
            for o in c["objs"]:
                if o.get("id") and o.get("displayName"):
                    channels[o["id"]] = o["displayName"]

    by_conv = {}
    for (cid, _), s in results.items():
        by_conv.setdefault(cid, []).append(s)
    names = {}
    for cid, msgs in by_conv.items():
        names[cid] = _name(con, cid, msgs, chats.get(cid) or {}, channels)

    records = []
    for (cid, mid), s in results.items():
        f = full.get((cid, mid))
        if f and f.get("deletedDateTime"):
            continue
        sender = (f or {}).get("from") or s.get("from") or {}
        author = (sender.get("displayName") or (s.get("from") or {}).get("displayName") or "").strip()
        if not author or (f and f.get("messageType") not in (None, "message")):
            continue   # system events (member added, renamed)
        kind = _kind(cid, s, chats.get(cid))
        relay = RELAY.match(s.get("summary") or "")
        rec = {"source_id": "teams", "external_id": _external(con, cid, mid), "conversation_id": cid, "conversation_name": names[cid],
               "conversation_kind": kind, "ts": _ts((f or {}).get("createdDateTime") or s.get("createdDateTime")), "author": author,
               "noise": bool(BOT.search(author if not relay else relay.group(1))) or (author.lower() == "slack bridge" and not relay),
               "web_link": (f or {}).get("webUrl") or s.get("webUrl"), "thread_parent": (f or {}).get("replyToId")}
        body = (f or {}).get("body") or {}
        if body.get("content"):
            rec["body_html" if (body.get("contentType") or "html").lower() == "html" else "body_text"] = body["content"]
        else:
            rec["body_text"] = s.get("summary") or ""
        att = [{"name": a.get("name"), "content_type": a.get("contentType"), "size": None, "url": a.get("contentUrl")}
               for a in (f or {}).get("attachments") or [] if a.get("contentUrl") and not SKIP_ATTACH.match(a.get("contentType") or "")]
        if att:
            rec["attachments"] = att
        if not rec["ts"] or not (rec.get("body_text") or rec.get("body_html") or att):
            continue
        records.append(rec)
    records.sort(key=lambda r: r["ts"])
    # chat messages the run did not open: stored with the search's text, which clips long messages at about 250 characters
    unread = sum(1 for (cid, mid), s in results.items() if (cid, mid) not in full and not _kind(cid, s, chats.get(cid)) == "channel"
                 and ((s.get("from") or {}).get("displayName") or "").lower() != "slack bridge")
    return {"records": records, "available": len(results), "complete": bool(ends) and all(ends.values()) and not errors,
            "errors": errors, "searches": searches, "reads": reads, "unread": unread}


def _kind(cid, s, chat):
    if s.get("channelUri") or "/channels/" in (s.get("uri") or ""):
        return "channel"
    t = (chat or {}).get("chatType")
    if t:
        return {"oneOnOne": "dm", "group": "group", "meeting": "meeting"}.get(t, "group")
    return "dm" if (cid or "").endswith("@unq.gbl.spaces") else "meeting" if (cid or "").startswith("19:meeting_") else "group"


def _name(con, cid, msgs, chat, channels):
    kind = _kind(cid, msgs[0], chat)
    topic = (chat.get("topic") or "").strip()
    members = [m.get("displayName") for m in chat.get("members") or [] if m.get("displayName") and not _me(m.get("displayName"), m.get("email"))]
    authors = list(dict.fromkeys((m.get("from") or {}).get("displayName") for m in msgs
                                 if (m.get("from") or {}).get("displayName") and not _me((m.get("from") or {}).get("displayName"), (m.get("from") or {}).get("email"))))
    row = con.execute("SELECT conversation_name FROM chat_messages WHERE conversation_id=? AND COALESCE(conversation_name, '') != '' "
                      "ORDER BY sent_at DESC LIMIT 1", (cid,)).fetchone() if cid else None
    old = row[0] if row else None
    if kind == "dm":
        other = (members or authors or [None])[0]
        return f"1:1 chat {other}" if other else old or "1:1 chat"
    if kind == "meeting":
        return f"Meeting chat: {topic}" if topic else old or "Meeting chat"
    if kind == "channel":
        return f"Teams channel: {channels[cid]}" if cid in channels else old or "Teams channel"
    if topic:
        return f"Group chat: {topic}"
    people = members or authors
    return f"Group chat: {', '.join(people[:6])}" if people else old or "Group chat"


def _external(con, cid, mid):
    """teams:<conversation>:<message>, or the bare id an earlier pull stored the same message under (so it is not stored twice)."""
    if con.execute("SELECT 1 FROM chat_messages WHERE source_id='teams' AND external_id=? AND conversation_id=?", (mid, cid)).fetchone():
        return mid
    return f"teams:{cid}:{mid}"


def bundle(built, wins, finished, note):
    """The ingest bundle for one pull."""
    recs = built["records"]
    pull = {"source_id": "teams", "window_from": wins[0][0], "window_to": wins[-1][1] or finished, "available": built["available"],
            "pulled": len(recs), "noise": sum(1 for r in recs if r.get("noise")), "complete": built["complete"], "note": note}
    b = {"agent": "assist:teams-capture", "prompt_version": PROMPT_VERSION, "pulls": [pull], "chat_messages": recs}
    if not built["complete"]:
        b["gaps"] = [f"Teams pull of {finished[:16].replace('T', ' ')} UTC incomplete: {note}"]
    return b


def run(claude, model, window=None, env=None, log=print, on_result=None, cwd=None):
    """One Teams pull: the tools-only Claude run with the capture hook, the bundle built in code, its ingest. Returns
    (ok, note). on_result(ev) gets the run's final stream-json event (cost and time); every line goes to seen_line."""
    from . import connections
    con = db.connect()
    try:
        wins = windows(con, window)
    finally:
        con.close()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="teams-capture-", dir=SCRATCH))
    t0 = time.time()
    try:
        cmd = [claude, "-p", prompt(wins), "--model", model, "--permission-mode", "default", "--setting-sources", "user,project",
               "--settings", hook_settings(), "--output-format", "stream-json", "--verbose",
               "--allowedTools", *[f"mcp__claude_ai_Microsoft_365__{t}" for t in TOOLS],
               "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "Task", "Agent"]
        e = dict(env or os.environ, ASSIST_CAPTURE=str(folder))
        # run from the scratch folder: the run needs no project file, and the project's CLAUDE.md, loaded from the working
        # folder, is long and re-read on every turn (17 Nov 2026: it was most of the time and cost of a pull this small)
        p = subprocess.run(cmd, cwd=str(cwd or SCRATCH), env=e, capture_output=True, text=True, timeout=1800)
        answer = ""
        for line in (p.stdout or "").splitlines():
            connections.seen_init(line, "teams-pull")
            if '"type":"result"' in line.replace(" ", ""):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                answer = str(ev.get("result") or "")[:300]
                if on_result:
                    on_result(ev)
        con = db.connect()
        try:
            built = build(load(folder), con)
        finally:
            con.close()
        finished = _iso(datetime.now(timezone.utc))
        if not built["searches"]:
            note = "Teams not pulled: the connector returned nothing" + (f" ({answer})" if answer else "") + (f"; {', '.join(built['errors'])}" if built["errors"] else "")
        else:
            note = (f"chat_message_search {'paginated to the end' if built['complete'] else 'NOT read to the end'} ({built['searches']} pages, "
                    f"{built['available']} results); {built['reads']} chat messages read in full"
                    + (f", {built['unread']} not opened (search text)" if built.get("unread") else "")
                    + "; built in code from the connector's results "
                    f"({round(time.time() - t0)} s)" + (f"; errors: {', '.join(built['errors'])}" if built["errors"] else ""))
        b = bundle(built, wins, finished, note)
        path = db.ASSIST / "inbox" / "queue" / f"pull-teams-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(b, ensure_ascii=False, indent=1))
        ing = subprocess.run([os.path.expanduser("~/.assist/venv/bin/python"), "-m", "assist.cli", "ingest", str(path)], cwd=str(db.ASSIST),
                             env=env or os.environ, capture_output=True, text=True, timeout=600)
        log(f"Teams: {len(b['chat_messages'])} messages from {built['available']} results, {built['reads']} read in full"
            f"{'' if built['complete'] else ', NOT complete'} ({round(time.time() - t0)} s)")
        return bool(built["searches"]) and built["complete"] and ing.returncode == 0, note
    finally:
        shutil.rmtree(folder, ignore_errors=True)
