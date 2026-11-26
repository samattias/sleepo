"""FastAPI app: serves the page from the database and runs refreshes. Route groups (mail, chat, meetings, messages,
people, knowledge, ui) live in assist/routes/ and share assist/web.py; this file keeps the app, its middleware, the
refresh and the routes not yet moved.

  assist serve            → http://localhost:8765
Routes
  GET  /                         the React app (assist-web/dist)
  PATCH /api/commitments/{id}    {"status": "open|done|dropped"}
  GET  /api/search?q=            full-text search over items and documents
  GET  /api/items?source=&q=&limit=
  GET  /status · POST /refresh?mode=sync|full   (same contract as the old serve.py)
  GET  /Granola Export/...       transcripts
"""
import json
import os
import re
import shlex
import subprocess
import threading
import urllib.parse
from typing import Optional
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
import asyncio
from pydantic import BaseModel

from . import connections, db, llm
from . import org
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from .retention import RETENTION_DAYS
from . import web
from .web import WEB_DIST, _nocache, _versions, con, snapshot   # shared with the route groups in assist/routes/

ASSIST, ROOT = web.ASSIST, web.ROOT
app = FastAPI(title="Assist", docs_url="/api/reference", redoc_url=None)

# Requests that change something or launch an app must come from the app itself. A web page in the browser can POST to
# this localhost server without a CORS preflight, so check Origin (or Referer) on every non-GET request.
TRUSTED_ORIGINS = {f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in sorted({8765, db.PORT, 5173})}   # this server's own port too (the demo copy)


TRUSTED_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


@app.middleware("http")
async def same_origin_only(request, call_next):
    # DNS rebinding: a web page can point its own hostname at 127.0.0.1 and then read this server as "same origin".
    # Only answer requests addressed to this machine by name or loopback address.
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    if host not in TRUSTED_HOSTS:
        return JSONResponse({"detail": "unknown host"}, status_code=421)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if not origin and request.headers.get("referer"):
            u = urllib.parse.urlsplit(request.headers["referer"])
            origin = f"{u.scheme}://{u.netloc}"
        if origin and origin not in TRUSTED_ORIGINS:   # no Origin at all = curl / the CLI on this Mac
            return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
    return await call_next(request)
LOCK = threading.Lock()
STATE = {"running": False, "mode": None, "started": None, "finished": None, "ok": None, "log": ""}
PY = web.PY
SCRIPTS = "scripts" if db.APP == db.ASSIST else str(db.APP / "scripts")   # helper scripts, from the data folder Claude runs in
_PULL_RULES = ("Do NOT use background agents or subagents. Do NOT write the brief, commitments, decisions, actions or meeting briefs: "
               "the server builds those from the database afterwards. Do not send anything. You may write files only under inbox/ "
               "(scratch files in /tmp/assist-pull/) and run only the assist CLI and the scripts the skills name; do not write or run "
               "scripts of your own. ")
_CALENDAR_MERGE = ("write the pull to inbox/calendar/pull-<today>.json as {\"window\": {afterDateTime, beforeDateTime, totalResultCount, "
                   "events_fetched}, \"events\": [...]} (the events.json event schema) and merge it with "
                   f"~/.assist/venv/bin/python -m assist.cli calendar-merge <that file>, then run python3 {SCRIPTS}/reconcile_calendar.py")
# Parts of the pull prompts that come from settings are placeholders, filled by render_pull() when a pull starts
# (16 Nov 2026: the followed Slack channels were written into the prompt and ignored settings followed_channels).
SLACK_SCOPE = "@@SLACK_SCOPE@@"


def render_pull(prompt):
    """A pull prompt with its placeholders filled from settings. Reads only."""
    from . import chatsync
    try:
        c = db.connect()
        try:
            chans = chatsync.followed_channels(c)
        finally:
            c.close()
    except Exception:
        chans = list(chatsync.FOLLOWED_CHANNELS)
    scope = ("DMs, group DMs and " + ", ".join(chans)) if chans else "DMs and group DMs"
    return prompt.replace(SLACK_SCOPE, scope)


_RM = org.section("roadmap", {})
_ROADMAP_STEP = (   # the org pack's roadmap workbook; none, no step
    f" 3) Check the product roadmap workbook (sharepoint_search for '{_RM['file'].rsplit('.', 1)[0]}' by {_RM['owner']}, the copy in "
    f"{_RM.get('owner_pronoun') or 'their'} Documents root): if its lastModifiedDateTime is newer than the 'modified' "
    "value in `~/.assist/venv/bin/python -m assist.cli roadmap-status`, read it with read_resource and write ONLY the "
    f"{_RM.get('sheet') or 'Initiatives'} sheet rows "
    "(header from 'ID', no Formulas) exactly as returned, tab-separated, to inbox/roadmap/initiatives.tsv, then run "
    "~/.assist/venv/bin/python -m assist.cli roadmap-import --modified <lastModifiedDateTime>.") if _RM.get("file") else ""
# The pulls run as separate, parallel Claude runs (each on the pull model); each ingests only its own bundles.
PULL_PROMPTS = {
    "mail": ("Morning refresh, MAIL pull. " + _PULL_RULES +
             "1) Run the /mail-full skill so new Inbox and Sent mail is stored in full. 2) Run the /docs-read skill (reads up to 15 recent "
             "SharePoint/OneDrive files in full through read_resource, then stores them)." + _ROADMAP_STEP),
    "chat": ("Morning refresh, CALENDAR, TEAMS AND SLACK pull. " + _PULL_RULES +
             "Run ONLY the '1. Gather' steps of the /brief skill for these sources: pull the calendar from YESTERDAY to 14 days ahead "
             "(older events are already stored): " + _CALENDAR_MERGE + "; pull Teams and Slack since the last pull recorded "
             "in the database (~/.assist/venv/bin/python -m assist.cli stats), paginating to the end of each window; save the metadata snapshot "
             "to inbox/live/<today>.md. For Slack use the mcp__claude_ai_Slack__ tools. Slack is complete when " + SLACK_SCOPE + " "
             "are paginated to the end; other Slack channels are background only and never make the pull incomplete. Teams is complete when "
             "chat_message_search is paginated to the end since the last pull (no nextOffset); listing chats or channels is not needed and "
             "never makes the pull incomplete. Store EVERY message that search returns, Teams channel posts and Slack Bridge relays "
             "included (they are background, kept out of the brief by the app; never skip them: from 30 Oct to 17 Nov 2026 the pull "
             "skipped them and channel conversations went missing); only the attachments step below skips Slack Bridge. Write ONE ingest bundle inbox/queue/pull-chat-<today-HHMM>.json "
             "following assist/ingest.py with pulls, items (calendar events and the shared-folder files below), chat_messages (EVERY Teams and "
             "Slack message you read, its text verbatim, noise set for bots and notifications; never a summary or gist, and no Teams or Slack "
             "items: ingest drops them), source_health and gaps. Teams ATTACHMENTS, a required step (chat_message_search returns none, so "
             f"files shared with {USER.first} are missed without it): (a) run chat_message_search with query '*' (never a KQL exclusion such as NOT "
             "\"[slack]\": it drops real messages) and hasAttachment true over the same window, paginated to the end; skip results from Slack "
             "Bridge. (b) Read each remaining message with read_resource (its uri) and give its chat_messages record attachments: "
             "[{name, content_type, size, url}] from the message's attachments (url = contentUrl; leave out messageReference quotes and "
             "cards); store the message itself in full as usual. Do not read the files: a separate step does (assist/chat_files.py). Say in "
             "the Teams pull note how many messages with attachments were read. For every "
             "SharePoint/OneDrive FOLDER link shared in those Teams or Slack messages (links containing ':f:'), list its current files with "
             "sharepoint_search (folderName = the folder's title) and add each file to the same bundle as an item (source_id 'sharepoint', kind 'doc', "
             "external_id = the file id, subject = file name, url = webUrl with spaces encoded plus '?web=1', thread = the folder path, from_name = "
             "who shared it; skip files in 'old' or archive subfolders). Then run ~/.assist/venv/bin/python -m assist.cli ingest <that bundle's path> "
             "(only your own bundle)."),
    "salesforce": ("Morning refresh, SALESFORCE pull. " + _PULL_RULES +
                   "Run the /salesforce skill to refresh open pipeline and closed deals (company and deal data only)."),
}
PULL_PHASE = {"mail": "Mail (Claude)", "salesforce": "Salesforce", "chat": "Calendar, Teams, Slack", "kb": "Emery Yates"}
PULL_MODEL = "sonnet"   # mechanical fetching: a lighter, faster model than the analysis steps
# Calendar.app delivered the calendar (assist/applecal.py): the chat pull leaves it out
PULL_PROMPTS["chat-nocal"] = PULL_PROMPTS["chat"].replace("CALENDAR, TEAMS AND SLACK pull", "TEAMS AND SLACK pull").replace(
    "pull the calendar from YESTERDAY to 14 days ahead (older events are already stored): " + _CALENDAR_MERGE + "; ",
    "the calendar already came from Calendar.app on this Mac, so do NOT pull it; ").replace("items (calendar events and the shared-folder files below)", "items (only the shared-folder and attached files below)")
assert PULL_PROMPTS["chat-nocal"].count("calendar") == 1
PULL_PROMPTS["docs"] = PULL_PROMPTS["mail"].replace("MAIL pull", "DOCUMENTS pull").replace(
    "1) Run the /mail-full skill so new Inbox and Sent mail is stored in full. 2)", "Mail is already stored (Apple Mail). 1)").replace(" 3) Check", " 2) Check")
assert PULL_PROMPTS["docs"] != PULL_PROMPTS["mail"]
# Jira issues mentioned in mail, chat and meetings (assist/refs.py): title, type and status, read-only. SUP is the customer
# support desk: its summaries can name customers, so only type and status are fetched for it.
_JIRA = org.section("jira", {})
_DESK = sorted(_JIRA.get("support_desk") or [])
if _JIRA.get("site"):   # the org pack's Jira site and support desk; no Jira, no step
    PULL_PROMPTS["docs"] += (" Finally, JIRA ISSUES: run ~/.assist/venv/bin/python -m assist.cli tickets-todo. If it lists keys, read them with "
                             f"searchJiraIssuesUsingJql (cloudId {_JIRA['site']}, jql 'key in (...)' in batches of 90, fields summary, status, issuetype, updated"
                             + (f"; for {', '.join(d + '-' for d in _DESK)} keys request only status, issuetype, updated) " if _DESK else ") ")
                             + "and write inbox/jira/issues.json as {\"issues\": [{\"key\", \"summary\"" + (f" (null for {', '.join(_DESK)})" if _DESK else "") + ", "
                             "\"status\", \"status_category\", \"type\", \"updated\"}]}, then run ~/.assist/venv/bin/python -m assist.cli tickets-import. Never write to Jira.")
FULL_PROMPT = PULL_PROMPTS["mail"]   # kept for callers that still import it


def salesforce_pulled(since):
    """Did a complete Salesforce pull land since this time (the open pipeline, the bundle the /salesforce skill ingests)?"""
    c = con()
    try:
        return bool(c.execute("SELECT 1 FROM pulls WHERE source_id='salesforce' AND complete=1 AND started_at >= ?", (since,)).fetchone())
    finally:
        c.close()


def salesforce_due(days=None):
    """Salesforce changes slowly: pull it at most once every N days (settings salesforce_every_days, default 7)."""
    c = con()
    try:
        r = c.execute("SELECT value FROM settings WHERE key='salesforce_every_days'").fetchone()
        n = float(days if days is not None else (r["value"] if r else 7))
        last = c.execute("SELECT MAX(finished_at) FROM pulls WHERE source_id='salesforce' AND complete=1").fetchone()[0]
    finally:
        c.close()
    if not last:
        return True
    try:
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 86400
    except ValueError:
        return True
    return age >= n


# Runs that pull from connectors read other people's mail and chat while holding tools, so what they may do is an allow
# list: write only under inbox/ and their scratch folder, run only the assist CLI and the two named scripts. They run in
# the default permission mode, where anything not allowed is refused (acceptEdits would accept any edit in this folder).
# No wildcard sits in front of fixed text in a Bash rule: "*" also matches spaces, so "rm -f *x" would allow
# "rm -f <anything> x" and "python3 scripts/*" allowed "python3 scripts/../inbox/x.py" (tested 13 Oct 2026).
# The deny rules stay as a second line for the files that steer the assistant (rules, memory, skills, code, git).
# .claude/settings.local.json is left out: it collects "always allow" clicks from interactive sessions (it allows
# "pnpm build *", which runs any package.json a pull could write under inbox/). The project settings stay: they carry the skills.
PULL_MODE = "default"
PULL_SETTINGS = ["--setting-sources", "user,project"]
PROTECTED = ["Edit(CLAUDE.md)", "Edit(DESIGN.md)", "Edit(memory/**)", "Edit(.claude/**)", "Edit(assist/**)", "Edit(scripts/**)",
             "Edit(evals/**)", "Edit(briefs/**)", "Edit(drafts/**)", "Edit(tests/**)", "Edit(.git/**)"]
ALLOWED = [f"Bash(python3 {SCRIPTS}/collect_granola.py)", f"Bash(python3 {SCRIPTS}/collect_granola.py --prune)", f"Bash(python3 {SCRIPTS}/reconcile_calendar.py)",
           "Bash(~/.assist/venv/bin/python -m assist.cli *)", "Bash(python3 -m assist.cli *)", "Read", "Glob", "Grep",
           "Edit(inbox/**)", "Edit(//tmp/assist-pull/**)", "Edit(//private/tmp/assist-pull/**)",
           "ToolSearch", "Skill", "mcp__claude_ai_Microsoft_365__outlook_calendar_search", "mcp__claude_ai_Microsoft_365__outlook_email_search",
           "mcp__claude_ai_Microsoft_365__chat_message_search", "mcp__claude_ai_Microsoft_365__read_resource", "mcp__claude_ai_Microsoft_365__sharepoint_search", "mcp__claude_ai_Microsoft_365__get_me",
           "mcp__plugin_productivity_slack__slack_search_public_and_private", "mcp__plugin_productivity_slack__slack_read_thread",
           "mcp__claude_ai_Slack__slack_search_public_and_private", "mcp__claude_ai_Slack__slack_search_public", "mcp__claude_ai_Slack__slack_read_thread",
           "mcp__claude_ai_Slack__slack_read_channel", "mcp__claude_ai_Slack__slack_read_user_profile", "mcp__claude_ai_Slack__slack_search_channels",
           "mcp__claude_ai_Slack__slack_search_users",
           "Bash(python3 -m json.tool *)",
           *[f"mcp__claude_ai_{org.section('crm', {}).get('connector')}__{t}" for t in org.section("crm", {}).get("connector_tools") or []],   # the org pack's CRM connector
           # raw exports in inbox/ are removed by name; the connector's tool-results copies are deleted by purge_tool_copies()
           "Bash(rm -rf inbox/salesforce-raw)", "Bash(rm -rf inbox/docs-raw)"]


def log(line):
    STATE["log"] = (STATE["log"] + line.rstrip("\n") + "\n")[-20000:]


# ---- refresh progress: named phases, each timed; past runs give the estimate for the next one
PHASES = {"sync": ["Calendar", "Granola meetings", "Local files", "Mail sync", "Documents", "Open items"],
          "full": ["Calendar", "Granola meetings", "Local files", "Mail sync", "Mail (Claude)", "Salesforce", "Emery Yates",
                   "Calendar, Teams, Slack", "Linking", "Documents", "Open items", "Initiatives", "Top of mind", "Tasks", "Meeting prep", "Meeting follow-ups"]}
DEFAULT_SECS = {"Calendar": 5, "Granola meetings": 40, "Local files": 20, "Mail sync": 30, "Mail (Claude)": 180, "Salesforce": 90, "Emery Yates": 300,
                "Calendar, Teams, Slack": 150, "Linking": 10, "Documents": 60, "Open items": 150, "Initiatives": 90, "Top of mind": 120, "Tasks": 100,
                "Meeting prep": 180, "Meeting follow-ups": 150, "sync:Open items": 2}   # mode:phase overrides a phase that differs by mode
HISTORY = db.db_path().parent / "refresh_history.json"


def _history():
    try:
        return json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        return {}


def _typical(mode, name):
    runs = [r["phases"][name] for r in [x for x in _history().get(mode, []) if x.get("ok")][-7:] if name in r.get("phases", {})]
    return sorted(runs)[len(runs) // 2] if runs else DEFAULT_SECS.get(f"{mode}:{name}", DEFAULT_SECS.get(name, 60))


def phase(name, status="running"):
    """Move the refresh to a named phase (forward only); earlier phases still marked running become done."""
    now = time.time()
    names = [x["name"] for x in STATE["phases"]]
    if name not in names:
        return
    i = names.index(name)
    if status == "running" and i < STATE["phase_index"]:
        return
    for j, x in enumerate(STATE["phases"]):
        if j < i and x["status"] in ("pending", "running"):
            if x["status"] == "running":
                x["secs"] = round(now - x["started"])
            x["status"] = "done" if x["status"] == "running" else "skipped"
    x = STATE["phases"][i]
    if status == "running" and x["status"] != "running":
        x.update(status="running", started=now)
        STATE["phase_index"] = i
    elif status in ("done", "failed", "skipped"):
        if x["status"] == "running":
            x["secs"] = round(now - x["started"])
        x["status"] = status


def record_mail_pull(since, ok):
    """The mail skill stores messages but writes no pulls row; record one per folder from what this run actually stored,
    so the freshness check sees the mail pull."""
    c = con()
    try:
        for folder, sid in (("inbox", "outlook.inbox"), ("sentitems", "outlook.sent")):
            n = c.execute("SELECT COUNT(*) FROM mail_messages WHERE folder=? AND synced_at >= ?", (folder, since)).fetchone()[0]
            pid = db.start_pull(c, sid, "claude-code:mail-full (parallel pull)", since, db.now(), f"{n} messages stored in this run")
            db.finish_pull(c, pid, n, n, 0, 1 if ok else 0)
            c.execute("UPDATE sources SET last_pull_at=? WHERE id=?", (db.now(), sid))
        c.commit()
    finally:
        c.close()


def phase_set(name, status):
    """Set one phase's status without moving the others (the parallel pulls run side by side)."""
    now = time.time()
    for x in STATE.get("phases") or []:
        if x["name"] == name:
            if status == "running":
                x.update(status="running", started=now)
            else:
                if x["status"] == "running" and x.get("started"):
                    x["secs"] = round(now - x["started"])
                x["status"] = status


def tagged_line(tag, line):
    """One stream-json event from a parallel pull, as a log line prefixed with its pull."""
    connections.seen_init(line, f"pull-{tag}")   # which connectors are signed in (assist/connections.py)
    try:
        ev = json.loads(line)
    except ValueError:
        return log(f"[{tag}] {line.rstrip()}")
    llm.record_stream_result(ev, f"pull-{tag}", PULL_MODEL)   # cost and tokens into llm_calls
    if ev.get("type") == "assistant":
        for c in ev.get("message", {}).get("content", []):
            if c.get("type") == "text" and c.get("text", "").strip():
                log(f"[{tag}]   " + c["text"].strip().replace("\n", " ")[:300])
            elif c.get("type") == "tool_use":
                STATE["tools"] = STATE.get("tools", 0) + 1
                inp = c.get("input") or {}
                name = c.get("name", "").replace("mcp__claude_ai_", "")
                what = (f"Skill:{inp.get('skill')}" if name == "Skill" else inp.get("command", "")[:160] if name == "Bash"
                        else f"{name} {inp.get('file_path', '')}" if name in ("Read", "Write", "Edit") else name)
                log(f"[{tag}]   → {what}")
    elif ev.get("type") == "result":
        log(f"[{tag}]   Claude finished: {ev.get('subtype')} in {round((ev.get('duration_ms') or 0) / 1000)}s, {ev.get('num_turns')} turns")


def _progress():
    """Fraction done and seconds left, from the typical length of each phase in past runs."""
    if not STATE.get("phases"):
        return None, None
    now, mode = time.time(), STATE["mode"]
    done = sum(_typical(mode, x["name"]) for x in STATE["phases"] if x["status"] in ("done", "skipped", "failed"))
    left = sum(_typical(mode, x["name"]) for x in STATE["phases"] if x["status"] == "pending")
    cur = next((x for x in STATE["phases"] if x["status"] == "running"), None)
    if cur:
        typ, spent = _typical(mode, cur["name"]), now - cur["started"]
        done += min(spent, typ * 0.95)
        left += max(typ - spent, typ * 0.05)
    total = done + left
    return (round(done / total, 3) if total else 0), round(left)


def _record_history():
    phases = {x["name"]: x["secs"] for x in STATE["phases"] if x["status"] == "done" and x.get("secs") is not None}
    h = _history()
    h.setdefault(STATE["mode"], []).append({"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "ok": STATE["ok"], "phases": phases,
                                            "total": round(time.time() - STATE["started_ts"])})
    h[STATE["mode"]] = h[STATE["mode"]][-20:]
    try:
        HISTORY.write_text(json.dumps(h, indent=1))
    except OSError:
        pass


CLAUDE_STEPS = [(re.compile(r"^Skill:prep\b|skills/prep/"), "Meeting prep"),
                (re.compile(r"^Skill:brief\b|skills/brief/|calendar_search|chat_message_search|slack_"), "Calendar, Teams, Slack"),
                (re.compile(r"^Skill:salesforce\b|skills/salesforce/|sf_get_|sf-bundle"), "Salesforce"),
                (re.compile(r"^Skill:mail-full\b|skills/mail-full/|outlook_email_search|mail-window"), "Mail (Claude)")]


def claude_line(line):
    """One stream-json event from the headless Claude run -> a readable log line and a phase move."""
    connections.seen_init(line, "pull-retry")
    try:
        ev = json.loads(line)
    except ValueError:
        return log(line)
    llm.record_stream_result(ev, "pull-retry", PULL_MODEL)   # cost and tokens into llm_calls
    if ev.get("type") == "assistant":
        for c in ev.get("message", {}).get("content", []):
            if c.get("type") == "text" and c.get("text", "").strip():
                log("  " + c["text"].strip().replace("\n", " ")[:300])
            elif c.get("type") == "tool_use":
                STATE["tools"] = STATE.get("tools", 0) + 1
                inp = c.get("input") or {}
                name = c.get("name", "").replace("mcp__claude_ai_", "")
                what = (f"Skill:{inp.get('skill')}" if name == "Skill" else inp.get("command", "")[:160] if name == "Bash"
                        else f"{name} {inp.get('file_path', '')}" if name in ("Read", "Write", "Edit") else name)
                log(f"  → {what}")
                for rx, ph in CLAUDE_STEPS:
                    if rx.search(what):
                        phase(ph)
                        break
    elif ev.get("type") == "result":
        log(f"  Claude finished: {ev.get('subtype')} in {round((ev.get('duration_ms') or 0) / 1000)}s, {ev.get('num_turns')} turns")


def run(cmd, cwd, env=None, on_line=None):
    log("$ " + " ".join(shlex.quote(c) for c in cmd)[:400])
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    for line in p.stdout:
        (on_line or log)(line)
    p.wait()
    log(f"(exit {p.returncode})")
    return p.returncode == 0


def run_rc(cmd, cwd, env=None):
    """run(), returning the exit code (callers that need to tell failures apart)."""
    log("$ " + " ".join(shlex.quote(c) for c in cmd)[:400])
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    for line in p.stdout:
        log(line)
    p.wait()
    log(f"(exit {p.returncode})")
    return p.returncode


def refresh(mode):
    env = dict(os.environ)
    try:
        key = subprocess.run(["security", "find-generic-password", "-s", "granola-api", "-a", db.keychain_account(), "-w"], capture_output=True, text=True).stdout.strip()
        if key:
            env["GRANOLA_API_KEY"] = key
    except Exception:
        pass
    # which connectors are signed in (assist/connections.py): Claude's start-up report, about 5 s, beside the steps below.
    # A connector that needs a new sign-in shows in the header with a way to sign in, not only in this log.
    connections.check_in_background("refresh", ASSIST)
    phase("Calendar")
    # Calendar.app's local store (assist/applecal.py): moved meetings, removed or declined ones and Sam's replies, in seconds.
    # First, so the recordings below are matched against today's calendar. Exit 2 = no Full Disk Access, 3 = not synced lately.
    cal_started = db.now()
    from . import jobs as _jobs
    for _ in range(90):   # Meetings › Refresh may be reading Calendar.app right now (assist/calrefresh.py): let it finish
        if not _jobs.held("calendar-refresh"):
            break
        time.sleep(1)
    with CAL_LOCK:
        cal_rc = run_rc([PY, "-m", "assist.cli", "calendar-local"], ASSIST, env)
    local_cal = cal_rc == 0
    connections.note_local("calendar-app", {0: "ok", 2: "no-access", 3: "not-synced"}.get(cal_rc, "ok"))
    if cal_rc == 2:
        log("!! Calendar.app: the server's Python cannot read Calendar.app's store (no Full Disk Access); the calendar comes from the connector pull")
    elif cal_rc not in (0, 3):
        log(f"!! Calendar.app import failed (exit {cal_rc}); the calendar comes from the connector pull")
    phase("Granola meetings")
    ok = run(["/usr/bin/python3", web.granola_script()], web.granola_dir(), env)
    ok &= run(["/usr/bin/python3", f"{SCRIPTS}/collect_granola.py", "--prune"], ASSIST, env)
    run(["/usr/bin/python3", f"{SCRIPTS}/reconcile_calendar.py"], ASSIST, env)   # match new recordings to the calendar now, not only in the full pull
    ok &= run([PY, "-m", "assist.cli", "sync-granola"], ASSIST, env)
    # screenshots of the shared screen through Granola's MCP (assist/granola_shots.py); after the notes, so they link.
    # Not part of ok: a missing sign-in (exit 2) leaves the rest of the refresh alone.
    shots_rc = run_rc([PY, "-m", "assist.cli", "granola-shots", "--days", "3" if mode == "sync" else "7"], ASSIST, env)
    connections.note_local("granola-mcp", "signed-out" if shots_rc == 2 else "ok")
    if shots_rc == 2:
        log("!! Granola screenshots: not signed in to Granola's MCP; run  ~/.assist/venv/bin/python -m assist.cli granola-login")
    elif shots_rc:
        log(f"!! Granola screenshots failed (exit {shots_rc})")
    phase("Local files")
    ok &= run([PY, "-m", "assist.cli", "scan-local"], ASSIST, env)
    from . import mailsync
    phase("Mail sync")
    # Apple Mail's local store (assist/applemail.py): Inbox and Sent in seconds, read only. Exit 2 = no Full Disk Access.
    local_started = db.now()
    with MAIL_LOCK:   # not alongside a mail refresh started from the Replies page
        local_rc = run_rc([PY, "-m", "assist.cli", "mail-local"], ASSIST, env)
    if local_rc == 2:
        # macOS attaches the permission to the real Python.app behind the venv symlink
        import sys
        app = os.path.join(sys.base_prefix, "Resources", "Python.app")
        log("!! Apple Mail: the server's Python cannot read ~/Library/Mail (no Full Disk Access). In System Settings > Privacy & Security > "
            "Full Disk Access, press +, then Cmd-Shift-G and paste " + app + " ; then restart the server. Until then mail comes from the connector pull.")
    elif local_rc != 0:
        log(f"!! Apple Mail import failed (exit {local_rc}); mail comes from the connector pull")
    rep = pull_report(local_started)
    local_mail = local_rc == 0 and all(rep[s]["ok"] for s in ("outlook.inbox", "outlook.sent"))
    if local_rc == 0 and not local_mail:
        log("Apple Mail: import ran but the pull is not complete (is Mail.app running?); the connector pull stays the fallback")
    connections.note_local("apple-mail", "no-access" if local_rc == 2 else "ok" if local_mail
                           else "not-running" if local_rc == 0 and not _mail_running() else "ok")
    if mailsync.signed_in():
        ok &= run([PY, "-m", "assist.cli", "mail-sync"], ASSIST, env)
    if mode == "full":
        claude = os.path.expanduser("~/.local/bin/claude")
        claude = claude if os.path.exists(claude) else "claude"
        started = time.time()
        env = dict(env, CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="1800000")   # if it does start background work, give it 30 min
        # 1. pulls: the only steps with connector tools. Mail, calendar/Teams/Slack and (weekly) Salesforce run side by side.
        pull_started = db.now()
        jobs = ["mail", "chat"] + (["salesforce"] if salesforce_due() else [])
        if _chat_state().get("running"):   # the Messages page is pulling Teams and Slack right now: not twice at once
            jobs.remove("chat")
            log("Teams, Slack: the Messages page's pull is running; this refresh leaves them to it")
        if local_mail:
            log("Mail: Inbox and Sent came from Apple Mail; the Claude mail pull only reads documents and the roadmap")
        if local_cal:
            log("Calendar: came from Calendar.app; the Claude chat pull reads only Teams and Slack")
        if "salesforce" not in jobs:
            phase_set("Salesforce", "skipped")
            log("Salesforce: pulled within the last week, skipped (settings salesforce_every_days)")
        from . import kb_sync   # the emery yates and product docs, weekly (assist/kb_sync.py)
        c = con()
        try:
            kb_due = kb_sync.due(c)
        finally:
            c.close()
        if kb_due:
            jobs.append("kb")
        else:
            phase_set("Emery Yates", "skipped")
            log("Emery Yates: read within the last week, skipped")
        results = {}

        def pull(key):
            t0 = time.time()
            phase_set(PULL_PHASE[key], "running")
            if key == "kb":   # every note read through the connector, built in code (assist/kb_sync.py)
                results[key] = run([PY, "-m", "assist.cli", "kb-sync"], ASSIST, env, on_line=lambda line: tagged_line("kb", line))
            elif key == "chat" and local_cal:   # Teams (built in code) and Slack side by side (Sam, 17 Nov 2026: faster)
                r = teams_slack_pull(env=env, verbose=True)
                log(f"[teams] {r.get('teams_note', '')}")
                log(f"[slack] {r.get('slack_note', '')}")
                results[key] = bool(r.get("teams")) and bool(r.get("slack"))
            else:
                if key == "mail":   # new and changed SharePoint/OneDrive files first, so /docs-read below can read them (assist/sp_index.py)
                    if not run([PY, "-m", "assist.cli", "sp-index"], ASSIST, env, on_line=lambda line: tagged_line("sharepoint", line)):
                        log("!! SharePoint & OneDrive index not complete (see Sources); documents already indexed are still read")
                prompt = render_pull(PULL_PROMPTS["docs" if key == "mail" and local_mail else key])
                cmd = [claude, "-p", prompt, "--model", PULL_MODEL, "--permission-mode", PULL_MODE, *PULL_SETTINGS, "--output-format", "stream-json",
                       "--verbose", "--allowedTools"] + ALLOWED + ["--disallowedTools"] + PROTECTED
                results[key] = run(cmd, ASSIST, env, on_line=lambda line, k=key: tagged_line(k, line))
            phase_set(PULL_PHASE[key], "done" if results[key] else "failed")
            for x in STATE.get("phases") or []:   # the pull's own wall time (parallel phases overlap)
                if x["name"] == PULL_PHASE[key]:
                    x["secs"] = round(time.time() - t0)
            if key == "mail" and not local_mail:   # Apple Mail records its own pulls
                record_mail_pull(pull_started, results[key])
        threads = [threading.Thread(target=pull, args=(k,), daemon=True) for k in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        ok &= all(results.values())
        ok &= run([PY, "-m", "assist.cli", "ingest"], ASSIST, env)            # anything a pull left in the queue
        # A Salesforce run that ends normally is not a pull (6 to 17 Nov 2026: every morning's run stopped within seconds,
        # stored nothing and the phase said done; Sources showed it 32 days old). Without a complete pull, retry it once
        # now, minutes later, and mark the phase failed if there is still none.
        if "salesforce" in jobs and not salesforce_pulled(pull_started):
            log("!! Salesforce: the run stored no complete pull; retrying it once")
            pull("salesforce")
            if not salesforce_pulled(pull_started):
                phase_set(PULL_PHASE["salesforce"], "failed")
                ok = False
                log("!! Salesforce not pulled: the pipeline keeps its last complete pull (see Sources)")
        if "chat" in jobs:   # the files shared in Teams chats (assist/chat_files.py; its own short run, not fatal)
            run([PY, "-m", "assist.cli", "chat-files"], ASSIST, env)
        from . import codebase   # the code base's clones, weekly, in the background: a fetch can take minutes (assist/codebase.py)
        if codebase.config().get("hosts") and codebase.due() and not codebase.running():
            codebase.start()
            log("Code base: updating the GitLab clones in the background (Knowledge › Product › Code base)")
        ok &= run([PY, "-m", "assist.cli", "sync-granola"], ASSIST, env)      # the calendar file the pull just wrote
        # everything below is built from the database, so the sources must be fresh first: check each one, retry the gaps once
        report = pull_report(pull_started, calendar_since=cal_started if local_cal else None)
        missing = [s for s, r in report.items() if not r["ok"]]
        waiting = _needs_signin(missing)   # a retry cannot sign in: it would fail the same way
        if waiting:
            log("!! not retried, the connector needs a new sign-in (shown in the header): " + ", ".join(waiting))
            missing = [s for s in missing if s not in waiting]
        if "teams" in missing and local_cal:   # Teams is retried the way it is pulled (assist/teams_capture.py), not by the model
            from . import teams_capture
            log("!! Teams not pulled to the end: retrying it once")
            c = con()
            try:
                tm = teams_capture.model(c)
            finally:
                c.close()
            teams_capture.run(claude, tm, env=env, log=log, on_result=lambda ev: llm.record_stream_result(ev, "pull-retry-teams", tm))
            report = pull_report(pull_started, calendar_since=cal_started if local_cal else None)
            missing = [s for s in missing if s != "teams" or not report[s]["ok"]]
            if "teams" in missing:
                log("!! Teams still not pulled: " + str(report["teams"]["note"]))
                missing.remove("teams")
        if missing:
            log("!! not pulled in this run: " + ", ".join(f"{s} ({report[s]['note']})" for s in missing) + " - retrying those once")
            retry = [claude, "-p", retry_prompt(missing, report), "--model", PULL_MODEL, "--permission-mode", PULL_MODE, *PULL_SETTINGS, "--output-format", "stream-json", "--verbose",
                     "--allowedTools"] + ALLOWED + ["--disallowedTools"] + PROTECTED
            run(retry, ASSIST, env, on_line=claude_line)
            run([PY, "-m", "assist.cli", "ingest"], ASSIST, env)
            run([PY, "-m", "assist.cli", "sync-granola"], ASSIST, env)
            report = pull_report(pull_started, calendar_since=cal_started if local_cal else None)
        STATE["pulls"] = report
        still = [s for s, r in report.items() if not r["ok"]]
        if still:
            log("!! STALE: the brief, actions and meeting briefs below are built without fresh data from: " + ", ".join(still))
        purge_tool_copies(started)
        # 2. everything below reads the database; model steps run without tools
        phase("Linking")
        # a full re-link every morning: new names, aliases and attendees reach older items too (incremental linking
        # only looks at new items); Sam's verdicts are kept
        ok &= run([PY, "-m", "assist.cli", "link", "--full"], ASSIST, env)
        run([PY, "-m", "assist.cli", "eval-links"], ASSIST, env)   # link quality trend (no model)
        run([PY, "-m", "assist.cli", "company-logos"], ASSIST, env)   # logos of companies new since the last run (assist/logos.py; network, no model)
        phase("Documents")   # document cards for new or changed text (assist/doccards.py), then a folder for every new document
        ok &= run([PY, "-m", "assist.cli", "doc-cards"], ASSIST, env)
        ok &= run([PY, "-m", "assist.cli", "doc-file"], ASSIST, env)
        phase("Open items")
        ok &= run([PY, "-m", "assist.cli", "loops", "all"], ASSIST, env)
        phase("Who said what")   # each speaker's main points and where open items were said (assist/speakers.py)
        ok &= run([PY, "-m", "assist.cli", "speakers"], ASSIST, env)
        phase("Initiatives")
        ok &= run([PY, "-m", "assist.cli", "ini-tag", "--days", "7"], ASSIST, env)
        phase("Top of mind")   # the topics of the last days, filed under the initiatives (assist/topics.py); tool-free, after who said what
        run([PY, "-m", "assist.cli", "topics"], ASSIST, env)   # a failed run keeps the last set and does not fail the refresh
        phase("Tasks")   # 22 Oct 2026: Tasks replaced Actions. Steps closed by evidence, new register items and the assistant's
        # proposals become suggestions Sam accepts or dismisses (assist/tasks.py); nothing is added to his list without him
        # the past tasks rebuilt from what Sam did (assist/task_history.py): only the last complete week, when it is not built
        # yet (Mondays); the suggestions just after read it. A failed week is retried next time and does not fail the refresh.
        run([PY, "-m", "assist.cli", "task-history"], ASSIST, env)
        ok &= run([PY, "-m", "assist.cli", "tasks", "all"], ASSIST, env)
        # new emails Sam should send (Inbox › Drafts, assist/new_mail.py; 26 Oct 2026): an email-focused pass stored as task
        # suggestions like the ones above. One tool-free run; a failure does not fail the refresh.
        run([PY, "-m", "assist.cli", "drafts-suggest"], ASSIST, env)
        # No daily brief here (12 Oct 2026): the app had no place for it, and Tasks plus meeting briefs carry the day.
        # /brief still writes one on demand (assist/briefgen.py).
        # No weekly strategy memo (Sam, 29 Oct 2026: "we don't need it"; its page is gone). assist.cli strategy still writes one.
        phase("Meeting prep")   # tool-free: the pack is built from the database, the model only writes (assist/prepgen.py)
        ok &= run([PY, "-m", "assist.cli", "prep-write", "--upcoming", "--days", "1"], ASSIST, env)
        phase("Meeting follow-ups")   # actions from what was said in the recorded meetings of the last 3 days (assist/followup.py), tool-free
        ok &= run([PY, "-m", "assist.cli", "followup-write", "--recent"], ASSIST, env)
    if mode != "full":   # the full refresh runs these after linking
        if STATE.get("documents", True):   # the onboarding agent's import leaves the cards to the next sync (a new install's
            phase("Documents")             # hundreds of files took 25 minutes of card runs, 16 Nov 2026); shown as skipped
            ok &= run([PY, "-m", "assist.cli", "doc-cards"], ASSIST, env)
        # new mail from Apple Mail is tied to its people, companies, bets and tasks now, not at the next bundle ingest
        # (17 Nov 2026: mail sat unlinked from 09:48 to 12:39); incremental, and the end of linking walks the graph (graph memory)
        run([PY, "-m", "assist.cli", "link"], ASSIST, env)
        # deterministic, well under a second: replies Sam sent since the last run close their open items, so the
        # register, Today and the Actions list stay current through the day (extraction and review stay in the full run)
        phase("Open items")
        ok &= run([PY, "-m", "assist.cli", "loops", "sync"], ASSIST, env)
        ok &= run([PY, "-m", "assist.cli", "tasks", "sync"], ASSIST, env)   # steps the register or Sam's mail closed (no model)
    # mail, chat and meeting notes linked to Sam's tasks (assist/task_links.py): same thread as a task's sources at once,
    # the model's match of new items in the background
    run([PY, "-m", "assist.cli", "task-links"], ASSIST, env)
    try:
        from . import task_links
        if task_links.spawn_match(ASSIST):
            log("Task links: matching new mail, chat and meeting notes to your tasks, in the background")
    except Exception as e:
        log(f"!! task links could not start: {e}")
    # recommended replies for mail waiting on Sam (assist/replies.py predraft): in the background, so the refresh ends now
    try:
        from . import replies
        if replies.spawn_predraft(ASSIST):
            log("Pre-drafts: writing recommended replies for new mail waiting on you, in the background")
    except Exception as e:
        log(f"!! pre-drafts could not start: {e}")
    try:   # and a task proposed for each, shown in the Inbox's Create task tab (assist/tasks.py preplan)
        from . import tasks as _tasks
        if _tasks.spawn_preplan(ASSIST):
            log("Task proposals: proposing a task for new mail waiting on you, in the background")
    except Exception as e:
        log(f"!! task proposals could not start: {e}")
    try:   # search by meaning: vectors for what is new in the search index (assist/embed.py; only once fastembed is installed)
        from . import embed
        if embed.available():
            run([PY, "-m", "assist.cli", "embed-sync"], ASSIST, env)
    except Exception as e:
        log(f"!! search by meaning not updated: {e}")
    try:   # what Sam told SleePO since the last run, kept as memories (assist/remember.py), in the background
        from . import remember
        if remember.spawn_learn(ASSIST):
            log("Memory: learning from what you told SleePO, in the background")
    except Exception as e:
        log(f"!! memory learning could not start: {e}")
    try:   # graph memory, phase 2: bets, topics and the next briefs that new material touched, brought up to date (assist/graph_refresh.py)
        from . import graph_refresh
        if graph_refresh.spawn(ASSIST):
            log("Graph memory: reading what new material changed in your bets, topics and next briefs, in the background")
    except Exception as e:
        log(f"!! graph memory refresh could not start: {e}")
    return ok   # the last phase is closed as done or failed by the caller


def _needs_signin(source_ids):
    c = con()
    try:
        return connections.needs_signin(c, source_ids)
    except Exception:
        return []
    finally:
        c.close()


def _mail_running():
    """Is Mail.app running? (an Apple Mail import that read nothing complete, with Mail closed, is the user's to fix)"""
    try:
        return subprocess.run(["pgrep", "-xq", "Mail"], check=False).returncode == 0
    except OSError:
        return True


PULL_SOURCES = {"outlook.inbox": "Mail (inbox)", "outlook.sent": "Mail (sent)", "teams": "Teams", "slack": "Slack", "calendar": "Calendar"}


def pull_report(since, calendar_since=None):
    """Per source: did this run record a complete pull, and what is the newest item now? (pulls rows the ingest wrote).
    calendar_since: the calendar came from Calendar.app at the start of the run, before the pulls."""
    c = con()
    try:
        out = {}
        for sid, name in PULL_SOURCES.items():
            # the calendar file is re-imported by every sync (agent 'claude-code (prototype)'); only a real pull counts.
            # A complete pull anywhere in the run wins: a later, partial retry must not hide it (16 Oct 2026)
            r = c.execute("SELECT complete, note, pulled, finished_at FROM pulls WHERE source_id=? AND started_at >= ? "
                          "AND agent NOT IN ('claude-code (prototype)', 'importer') ORDER BY complete DESC, id DESC LIMIT 1",
                          (sid, calendar_since if sid == "calendar" and calendar_since else since)).fetchone()
            newest = c.execute("SELECT MAX(ts) FROM items WHERE source_id=?", (sid,)).fetchone()[0]
            ok = bool(r) and bool(r["complete"])
            out[sid] = {"name": name, "ok": ok, "pulled": r["pulled"] if r else None, "newest": newest,
                        "note": (r["note"] or "")[:160] if r else "no pull recorded in this run"}
        return out
    finally:
        c.close()


def retry_prompt(missing, report=None):
    """A focused second pass for the sources the main pull did not deliver. The retry run cannot query the database,
    so it is given the newest stored item per source, and told to leave the sources that were delivered alone."""
    steps = []
    if any(s.startswith("outlook.") for s in missing):
        steps.append("Run the /mail-full skill so new Inbox and Sent mail since the last stored message is stored in full.")
    rest = [PULL_SOURCES[s] for s in missing if not s.startswith("outlook.")]
    if rest:
        how = []   # instructions only for the sources being retried: calendar steps in a Slack retry made it pull the calendar too
        if "calendar" in missing:
            how.append("calendar: past 7 to next 14 days; " + _CALENDAR_MERGE)
        if "teams" in missing or "slack" in missing:
            how.append("Teams and Slack: since the newest stored message, paginated to the end")
        if "slack" in missing:
            how.append("Slack is complete when " + SLACK_SCOPE + " are; other channels are not required")
        steps.append("Run ONLY the '1. Gather' steps of the /brief skill for: " + ", ".join(rest) + " (" + "; ".join(how) + "). Write ONE ingest bundle "
                     "inbox/queue/pull-retry-<now>.json with pulls (complete:true only if paginated to the end), items, chat_messages and source_health, "
                     "then run ~/.assist/venv/bin/python -m assist.cli ingest. If a connector is not available, record a pull with complete:false and "
                     "a note saying why.")
        newest = [f"{PULL_SOURCES[s]} {report[s]['newest']}" for s in missing if report and report.get(s, {}).get("newest")]
        if newest:
            steps.append("Newest stored item (UTC), so pull from there and do not query the database: " + "; ".join(newest) + ".")
        steps.append("Pull and record ONLY these sources; the others were delivered by the main pull, so record nothing for them.")
    return render_pull("Pull retry: the main pull did not deliver some sources. Do ONLY these steps, in this session, no background agents. "
            + " ".join(f"{i + 1}) {x}" for i, x in enumerate(steps)) + " Do not write the brief or anything else. " + _PULL_RULES)


def purge_tool_copies(since):
    """The headless run's connector saves oversized results under ~/.claude/projects/<this folder>/…/tool-results.
    Full mail must live only in the database, so delete the copies that run left behind."""
    proj = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ASSIST))
    n = 0
    for f in proj.glob("**/tool-results/*"):
        try:
            if not f.is_file() or f.stat().st_mtime < since - 5:
                continue
            # mail bodies, and document text read for /docs-read (Microsoft 365 read_resource or Salesforce exports by file name)
            if re.search(r"Microsoft_365-read_resource" + ("|" + re.escape(org.section("crm", {}).get("connector")) if org.section("crm", {}).get("connector") else ""), f.name) or \
               re.search(r'"bodyPreview"|"toRecipients"|mail:///messages/', f.read_text(errors="ignore")):
                f.unlink(); n += 1
        except OSError:
            pass
    log(f"removed {n} connector copies of mail and documents from tool-results")


def worker(mode, documents=True):
    STATE.update({"running": True, "mode": mode, "documents": documents, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "started_ts": time.time(), "finished": None,
                  "ok": None, "log": "", "tools": 0, "phase_index": 0,
                  "phases": [{"name": n, "status": "pending", "started": None, "secs": None} for n in PHASES[mode]]})
    try:
        STATE["ok"] = refresh(mode)
    except Exception as e:  # pragma: no cover
        log(f"error: {e}")
        STATE["ok"] = False
    for x in STATE["phases"]:
        if x["status"] == "running":
            phase(x["name"], "done" if STATE["ok"] else "failed")
    _record_history()   # failed runs too, so a bad morning is visible; estimates use successful runs only (_typical)
    STATE["running"] = False
    STATE["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")


@app.get("/api/meta")
def api_meta():
    d = snapshot()
    return _nocache({"built": d["built"], "built_iso": d["built_iso"], "initiatives": d["initiatives"], "logos": d["logos"], "db": d["db"], "retention_days": RETENTION_DAYS,
                     "counts": {"commitments_open": sum(1 for t in d["tasks"] if t["group"] in ("active", "waiting")),
                                "calendar": len(d["calendar"]["events"]), "meetings": len(d["meetings"]), "people": len(d["people"]),
                                "initiatives": len(d["projects"]), "library": len(d["docs"]), **_store_counts()}, **_last_refresh(),
                     "profile": _meta_profile(), "org": _meta_org(), "app_name": "SleePO", "demo": db.DEMO, "setup": _meta_setup()})


def _meta_setup():
    """Whether first-run setup (/welcome) should open by itself: no profile yet and setup never finished or skipped."""
    from . import profile
    p = profile.get()
    c = profile.read_only(db.db_path())
    try:
        done = bool(c and db.get_setting(c, "onboarding_done"))
    finally:
        if c is not None:
            c.close()
    # the onboarding agent keeps Calendar.app's address before it reads (assist/onboard_agent.py): a run not yet confirmed
    # still needs setup, so a window closed half-way opens the Welcome page again
    from . import onboard_agent
    run = onboard_agent.status()
    started = bool(run.get("stage")) and not run.get("applied")
    return {"needed": not (p["full_name"] and p["emails"]) or (started and not done), "done": done}


def _meta_profile():
    """The user's profile for the app (assist/profile.py): who "me" is, names, time zone, locale, sign-off (16 Nov 2026)."""
    from . import profile
    p = profile.get()
    keep = ("full_name", "first_name", "emails", "aliases", "speaker_label", "role", "role_short", "pronouns", "timezone", "locale",
            "signoff", "spelling", "second_timezone", "second_timezone_label", "manager", "manager_pronouns", "meeting_days", "meeting_hours", "plan_file", "plan_title")
    out = {k: p[k] for k in keep}
    out["names"] = profile.names()
    out["role_soul_file"] = __import__("assist.soul", fromlist=["files"]).files()["cpo"]
    return out


def _meta_org():
    """The organisation for the app (assist/org.py): its name, CRM regions and the roadmap owner."""
    from . import org
    o = org.get()
    return {"name": o.get("name") or "", "domains": o.get("domains") or [], "crm_regions": (o.get("crm") or {}).get("regions") or [],
            "roadmap_owner": (o.get("roadmap") or {}).get("owner") or ""}


def _last_refresh():
    """For the sidebar footer: when data last landed (any pull) and when the Claude agents last ran. ISO UTC."""
    c = con()
    try:
        data = c.execute("SELECT MAX(finished_at) FROM pulls").fetchone()[0]
        agents = c.execute("SELECT MAX(COALESCE(finished_at, started_at)) FROM runs WHERE agent LIKE 'claude-code%'").fetchone()[0]
        return {"last_data": data, "last_agents": agents}
    finally:
        c.close()


def _store_counts():
    """Totals for the sidebar: everything stored for Documents, Emails and Messages (the same rows those pages list)."""
    c = con()
    try:
        one = lambda sql: c.execute(sql).fetchone()[0]
        docs = one("SELECT COUNT(*) FROM items WHERE source_id='local' OR (kind='doc' AND source_id IN ('sharepoint', 'acme-kb'))") \
            + one("SELECT COUNT(*) FROM mail_attachments a JOIN mail_messages m ON m.item_id=a.item_id WHERE a.is_inline=0")
        try:
            docs += one("SELECT COUNT(*) FROM chat_attachments a JOIN chat_messages m ON m.item_id=a.item_id JOIN items i ON i.id=a.item_id")
        except Exception:  # chat tables not there yet
            pass
        return {"documents": docs, "mail": one("SELECT COUNT(*) FROM items WHERE source_id IN ('outlook.inbox', 'outlook.sent')"),
                "messages": one("SELECT COUNT(*) FROM items WHERE source_id IN ('teams', 'slack')"),
                # same rows as the Pipeline page: open, non-test Salesforce opportunities
                "pipeline": one("SELECT COUNT(*) FROM items WHERE source_id='salesforce' AND kind='opportunity' AND noise=0 "
                                "AND COALESCE(json_extract(payload, '$.is_open'), 1) <> 0")}
    finally:
        c.close()


@app.get("/api/today")
def api_today():
    d = snapshot()
    return _nocache({"brief": d["brief"], "calendar_today": [e for e in d["calendar"]["events"] if e["date"] == d["built_iso"] and not e["cancelled"]],
                     "built_iso": d["built_iso"], "sources": d["sources"], "coverage": d["coverage"],
                     "meetings_status": {k: sum(1 for m in d["meetings"] if m["status"] == k) for k in ("analysed", "digested", "pending", "personal")}})


@app.get("/api/commitments")
def api_commitments():
    return _nocache(snapshot()["tasks"])


# ---- mail only: the Replies page's refresh button
MAIL_LOCK = threading.Lock()   # this and the refresh's own Mail sync never run at once


@app.get("/api/refresh-mail")
def api_refresh_mail_status():
    c = con()
    try:
        last = c.execute("SELECT MAX(finished_at) FROM pulls WHERE agent='assist mail-local'").fetchone()[0]
    finally:
        c.close()
    from . import applemail   # a quiet check that found nothing records its time outside the database
    return _nocache({"running": MAIL_LOCK.locked(), "last": max(filter(None, [last, applemail.checked()]), default=None)})


@app.post("/api/refresh-mail")
def api_refresh_mail():
    """Inbox and Sent from Apple Mail on this Mac (the import every refresh runs; seconds, no Claude), then the open-items
    sync so replies Sam has sent close their items. Waits for both and says what came in, and how many emails changed
    between read and unread (read in Mail, or no longer in its Inbox: applemail.left_inbox)."""
    from . import applemail
    if not MAIL_LOCK.acquire(timeout=60):
        raise HTTPException(409, "Mail is already being refreshed")
    unread = "SELECT m.item_id FROM mail_messages m JOIN items i ON i.id=m.item_id WHERE i.source_id='outlook.inbox' AND m.is_read=0"
    try:
        c = con()
        try:
            before = {r[0] for r in c.execute(unread)}
        finally:
            c.close()
        started, t0 = db.now(), time.time()
        # --quiet: when nothing changed, nothing is written (any write reloads every open tab; the Inbox checks every 2 minutes)
        p = subprocess.run([PY, "-m", "assist.cli", "mail-local", "--quiet"], cwd=str(ASSIST), capture_output=True, text=True, timeout=300)
        if p.returncode == 2:
            raise HTTPException(503, "SleePO cannot read Apple Mail (no Full Disk Access for the server's Python). The full refresh still pulls mail through Outlook.")
        if p.returncode != 0:
            tail = [x for x in (p.stdout + p.stderr).splitlines() if x.strip()][-1:] or ["no output"]
            raise HTTPException(500, f"Apple Mail import failed: {tail[0][:200]}")
        loops = subprocess.run([PY, "-m", "assist.cli", "loops", "sync"], cwd=str(ASSIST), capture_output=True, text=True, timeout=180)
        subprocess.run([PY, "-m", "assist.cli", "tasks", "sync"], cwd=str(ASSIST), capture_output=True, text=True, timeout=180)
    finally:
        MAIL_LOCK.release()
    c = con()
    try:
        new = {"inbox": 0, "sent": 0, **{("sent" if r["source_id"] == "outlook.sent" else "inbox"): r["pulled"] or 0 for r in c.execute(
            "SELECT source_id, pulled FROM pulls WHERE agent='assist mail-local' AND started_at >= ? ORDER BY id", (started,))}}
        last = max(filter(None, [c.execute("SELECT MAX(finished_at) FROM pulls WHERE agent='assist mail-local'").fetchone()[0], applemail.checked()]), default=None)
        after = {r[0] for r in c.execute(unread)}
    finally:
        c.close()
    if loops.returncode == 0:   # new mail waiting on Sam gets its recommended reply, and a proposed task, in the background
        from . import replies, tasks as _tasks
        replies.spawn_predraft(ASSIST)
        try:
            _tasks.spawn_preplan(ASSIST)
        except Exception:
            pass
    return _nocache({"ok": True, "secs": round(time.time() - t0, 1), "new": new, "last": last, "mail_running": applemail.mail_running(),
                     "loops_ok": loops.returncode == 0, "read": len(before - after), "unread": len(after)})


# ---- Teams and Slack only: the Messages page's Refresh (Sam, 22 Oct 2026). The same pull the full refresh runs for them
# (a Claude run through the Microsoft 365 and Slack connectors, read only; calendar left out: Calendar.app has it), then
# the ingest. It runs as its own process (assist.cli chat-pull) with its state in a file outside OneDrive, so a server
# restart (any save under assist/) neither stops it nor loses it. One at a time, and not while a full refresh pulls.
CHAT_JOB = db.db_path().parent / "jobs" / "chat_pull.json"


def _chat_state():
    try:
        d = json.loads(CHAT_JOB.read_text())
    except (OSError, ValueError):
        d = {}
    if d.get("running") and d.get("pid"):
        try:
            os.kill(int(d["pid"]), 0)
        except (OSError, ValueError):
            d.update(running=False, ok=False, note=d.get("note") or "The pull stopped without a result. Try again.")
    return d


def _chat_write(d):
    CHAT_JOB.parent.mkdir(parents=True, exist_ok=True)
    CHAT_JOB.write_text(json.dumps(d))


def chat_pull_prompt(window=None):
    """The Teams and Slack pull in one run (the fallback when the calendar has to come from the connector too: the morning
    refresh without Calendar.app). window = (from, to) as YYYY-MM-DD re-reads that span instead of since the last pull (a
    backfill; messages already stored are matched by id, not added twice)."""
    p = render_pull(PULL_PROMPTS["chat-nocal"])
    if not window:
        return p
    span = f"from {window[0]}T00:00:00Z to {window[1]}T00:00:00Z"
    q = p.replace("since the last pull recorded in the database (~/.assist/venv/bin/python -m assist.cli stats)",
                  f"{span} (a backfill: read every message in that window, including ones already stored)").replace(
                  "paginated to the end since the last pull", f"paginated to the end {span}")
    assert q.count(span) == 2, "chat pull prompt changed: update chat_pull_prompt"
    return q


def chat_files_cmd(prompt):
    """The Claude command for the shared-files step (assist/chat_files.py) and Roadmap › Refresh (assist/roadmap.py): the pull's
    model, settings and read-only tools."""
    claude = os.path.expanduser("~/.local/bin/claude")
    claude = claude if os.path.exists(claude) else "claude"
    return [claude, "-p", prompt, "--model", PULL_MODEL, "--permission-mode", PULL_MODE, *PULL_SETTINGS,
            "--allowedTools"] + ALLOWED + ["--disallowedTools"] + PROTECTED


def teams_slack_pull(env=None, window=None, verbose=False, tag="pull"):
    """Teams and Slack side by side (Sam, 17 Nov 2026: "make the Teams and Slack synchronization much faster"): Teams built in
    code from the connector's results (assist/teams_capture.py, Haiku) and Slack's own run (assist/slack_pull.py, Sonnet),
    both from the scratch folder, at the same time. verbose: one line each in the refresh log. window = (from, to) dates for
    a backfill. Returns {"teams": ok, "teams_note": str, "slack": ok, "slack_note": str}."""
    from . import slack_pull, teams_capture
    claude = os.path.expanduser("~/.local/bin/claude")
    claude = claude if os.path.exists(claude) else "claude"
    c = con()
    try:
        tm, sm = teams_capture.model(c), slack_pull.model(c)
    finally:
        c.close()
    say = log if verbose else (lambda x: None)
    out = {}

    def teams():
        try:
            out["teams"], out["teams_note"] = teams_capture.run(claude, tm, window=window, env=env, log=say,
                                                                on_result=lambda ev: llm.record_stream_result(ev, f"{tag}-teams", tm))
        except Exception as e:   # a failed Teams pull leaves Slack's alone and shows in the pull report
            out["teams"], out["teams_note"] = False, f"Teams pull failed: {e}"[:300]

    def slack():
        try:
            out["slack"], out["slack_note"] = slack_pull.run(claude, sm, render_pull(SLACK_SCOPE), span=window, env=env, log=say,
                                                             on_result=lambda ev: llm.record_stream_result(ev, f"{tag}-slack", sm))
        except Exception as e:
            out["slack"], out["slack_note"] = False, f"Slack pull failed: {e}"[:300]

    threads = [threading.Thread(target=f, daemon=True) for f in (teams, slack)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


CHAT_FILES_LOCK = CHAT_JOB.parent / "locks" / "chat-files.lock"


def _chat_files_once():
    """The shared-files step (assist/chat_files.py), one at a time: it now runs after the Refresh has finished, so a second
    Refresh can start while it reads. Returns (files to read, files stored), or None when another one is reading."""
    from . import chat_files
    try:
        os.kill(int(CHAT_FILES_LOCK.read_text().strip()), 0)
        return None
    except (OSError, ValueError):
        pass
    CHAT_FILES_LOCK.parent.mkdir(parents=True, exist_ok=True)
    CHAT_FILES_LOCK.write_text(str(os.getpid()))
    try:
        return chat_files.run(log=lambda x: None, claude_cmd=chat_files_cmd)
    finally:
        try:
            CHAT_FILES_LOCK.unlink()
        except OSError:
            pass


def chat_pull_run(window=None):
    """Body of `assist.cli chat-pull`: Teams and Slack side by side, the ingest, and what came in. The Refresh ends as soon as
    the messages are stored (Sam, 17 Nov 2026: faster); the files shared in those chats are read afterwards, in the same
    process, and their count is added to the note when they are done."""
    d = _chat_state()
    started = d.get("started") or db.now()
    res = {}
    try:
        res = teams_slack_pull(window=window, tag="pull-chat-only")
        subprocess.run([PY, "-m", "assist.cli", "ingest"], cwd=str(ASSIST), capture_output=True, text=True, timeout=600)   # anything left in the queue
        rep = pull_report(started)
        got = [f"{rep[s]['name']}: {rep[s]['pulled'] or 0} new" + ("" if rep[s]["ok"] else ", not read to the end")
               for s in ("teams", "slack") if rep[s]["ok"] or rep[s]["pulled"] is not None]
        missing = [rep[s]["name"] for s in ("teams", "slack") if not rep[s]["ok"] and rep[s]["pulled"] is None]
        d.update(ok=res.get("teams", False) and res.get("slack", False) and not missing and all(rep[s]["ok"] for s in ("teams", "slack")),
                 note=(" · ".join(got) + (f" · not pulled: {', '.join(missing)}" if missing else "")) if (got or missing) else "nothing came back")
    except Exception as e:
        d.update(ok=False, note=str(e)[:200])
    d.update(running=False, finished=db.now())
    _chat_write(d)
    try:   # then the files shared in those chats (29 Oct 2026), after the page has its messages
        files = _chat_files_once()
    except Exception:
        files = None
    if files and files[0]:
        now = _chat_state()
        if now.get("started") == d.get("started") and not now.get("running"):
            now["note"] = (now.get("note") or "") + f" · files read: {files[1]} of {files[0]}"
            _chat_write(now)


@app.get("/api/refresh-messages")
def api_refresh_messages_status():
    c = con()
    try:
        last = {r[0]: r[1] for r in c.execute("SELECT id, last_pull_at FROM sources WHERE id IN ('teams','slack')")}
    finally:
        c.close()
    d = _chat_state()
    return _nocache({"running": bool(d.get("running")), "started": d.get("started"), "finished": d.get("finished"), "ok": d.get("ok"),
                     "note": d.get("note") or "", "last": max([v for v in last.values() if v] or [None]), "teams": last.get("teams"), "slack": last.get("slack")})


@app.post("/api/refresh-messages")
def api_refresh_messages():
    if STATE.get("running") and STATE.get("mode") == "full":
        raise HTTPException(409, "The full refresh is pulling Teams and Slack right now.")
    if _chat_state().get("running"):
        return api_refresh_messages_status()   # already running: report it
    _chat_write({"running": True, "started": db.now(), "pid": None})
    p = subprocess.Popen([PY, "-m", "assist.cli", "chat-pull"], cwd=str(ASSIST), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    _chat_write({"running": True, "started": db.now(), "pid": p.pid})
    return api_refresh_messages_status()


# ---- calendar only: the Calendar page's refresh button
CAL_LOCK = threading.Lock()   # the refresh's calendar step, one at a time (Meetings › Refresh: assist/calrefresh.py)


@app.get("/api/refresh-calendar")
def api_refresh_calendar_status():
    """The last or current Meetings › Refresh (assist/calrefresh.py)."""
    from . import calrefresh
    return _nocache(calrefresh.state())


@app.post("/api/refresh-calendar")
def api_refresh_calendar(dry: int = 0):
    """Meetings › Refresh: Calendar.app on this Mac, then Granola's new notes, then recordings re-matched and the database
    reloaded. Since 23 Oct 2026 it runs as its own process (assist/calrefresh.py) so a server restart cannot cut it off:
    this starts it (or reports the run already going) and the page follows GET /api/refresh-calendar. dry=1 runs the
    calendar part here and writes nothing."""
    from . import calrefresh
    if dry:
        r = calrefresh.run(dry=True)
        if r["error"]:
            raise HTTPException(r["code"], r["error"])
        return _nocache(r)
    return _nocache(calrefresh.start(granola=not STATE.get("running")))   # the full refresh pulls Granola itself


def _ext(name):
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", name or "")
    return m.group(1).lower() if m else ""


# ---------------------------------------------------------------- who was in each meeting (assist/meeting_people.py)


@app.get("/api/meetings/{mid}/shots")
def api_meeting_shots(mid: str):
    """Screenshots of the shared screen in a recorded meeting (assist/granola_shots.py), placed in the transcript."""
    from . import transcripts
    c = con()
    try:
        t = transcripts.load(c, mid)
    finally:
        c.close()
    if not t:
        raise HTTPException(404)
    return _nocache({"shots": t.get("shots", [])})


@app.get("/api/shots/{shot_id}/image")
def api_shot_image(shot_id: str, thumb: int = 0):
    from . import granola_shots
    c = con()
    try:
        f, mime = granola_shots.file_for(c, shot_id, thumb=bool(thumb))
    finally:
        c.close()
    if not f:
        raise HTTPException(404, f"image not kept (deleted after {RETENTION_DAYS} days, or not fetched yet)")
    return FileResponse(str(f), media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/meetings/{mid}/transcript")
def api_transcript(mid: str):
    from . import transcripts
    c = con()
    try:
        t = transcripts.load(c, mid)
        if t and mid.removeprefix("m-").isdigit():   # who said what: each speaker's main points (assist/speakers.py)
            from . import speakers
            t["by_speaker"] = speakers.for_meeting(c, int(mid.removeprefix("m-")))
    finally:
        c.close()
    if not t:
        raise HTTPException(404)
    return _nocache(t)


@app.get("/api/calendar")
def api_calendar():
    return _nocache(snapshot()["calendar"])


@app.get("/api/meetings")
def api_meetings():
    return _nocache(snapshot()["meetings"])


@app.get("/api/sources")
def api_sources():
    d = snapshot()
    counts = {k: sum(len(t["rows"]) for t in v) for k, v in d["streams"].items()}
    c = con()
    try:   # stored items are the real count (e.g. every mail envelope since 1 Jul), not the rows of the last pull summaries
        for r in c.execute("SELECT source_id, COUNT(*) AS n FROM items GROUP BY source_id"):
            counts[r["source_id"]] = max(counts.get(r["source_id"], 0), r["n"])
        from . import gaps, source_status   # live freshness, the same definition as /api/sources/status and the Today widget
        status = source_status.systems(c)
        gap_list = gaps.listing(c)
        pulls = _source_pulls(c)
    finally:
        c.close()
    systems = [{**x, "status": status.get(x["id"])} for x in d["sources"]]
    return _nocache({"systems": systems, "coverage": d["coverage"], "sync": d["sync"], "stream_counts": counts,
                     "gaps": gap_list, "pulls": pulls})


def _source_pulls(c, keep=12):
    """Per system: how many pulls there were, the latest ones that brought something in, and how many quiet checks (nothing
    new) ran in the last 7 days. The Sources page showed every pull window (3,107 for Outlook, mostly identical quiet checks)."""
    week = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {}
    for r in c.execute("SELECT s.system, COUNT(*) n, SUM(CASE WHEN COALESCE(p.pulled, 0)=0 AND p.finished_at >= ? THEN 1 ELSE 0 END) quiet, "
                       "MAX(p.finished_at) last FROM pulls p JOIN sources s ON s.id=p.source_id GROUP BY s.system", (week,)):
        out[r["system"]] = {"total": r["n"], "quiet_week": r["quiet"] or 0, "last": r["last"], "recent": []}
    for r in c.execute("SELECT * FROM (SELECT s.system, s.name, p.finished_at, p.available, p.pulled, p.complete, p.agent, p.note, "
                       "ROW_NUMBER() OVER (PARTITION BY s.system ORDER BY p.finished_at DESC, p.id DESC) rn "
                       "FROM pulls p JOIN sources s ON s.id=p.source_id WHERE COALESCE(p.pulled, 0) > 0) WHERE rn <= ?", (keep,)):
        out[r["system"]]["recent"].append({"stream": r["name"], "at": r["finished_at"], "available": r["available"], "pulled": r["pulled"],
                                           "complete": bool(r["complete"]), "agent": r["agent"], "note": r["note"] or ""})
    return out


@app.get("/api/streams/{sid}")
def api_stream(sid: str):
    return _nocache(snapshot()["streams"].get(sid, []))


class Status(BaseModel):
    status: str


@app.patch("/api/commitments/{cid}")
def api_commitment(cid: int, body: Status):
    if body.status not in ("open", "done", "dropped"):
        raise HTTPException(400, "status must be open, done or dropped")
    c = con()
    try:
        c.execute("UPDATE commitments SET status=?, closed_at=CASE WHEN ?='open' THEN NULL ELSE COALESCE(closed_at, ?) END WHERE id=?",
                  (body.status, body.status, db.now(), cid))
        from . import loops   # keep the open-items register in step (same item, same status)
        lp = c.execute("SELECT id FROM loops WHERE fact_type='commitment' AND fact_id=?", (cid,)).fetchone()
        if lp:
            loops.set_status(c, lp["id"], body.status)
        c.commit()
        return {"id": cid, "status": body.status}
    finally:
        c.close()


def fts_query(q):
    """Turn free text into a safe FTS5 query: every word quoted, last word prefix-matched, all words required."""
    words = re.findall(r"\w+", q or "", flags=re.UNICODE)
    if not words:
        return None
    return " ".join('"%s"' % w for w in words[:-1]) + (" " if len(words) > 1 else "") + '"%s"*' % words[-1]


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), limit: int = 60):
    """Unified, ranked search over everything (assist/search.py)."""
    from . import search
    c = con()
    try:
        search.ensure_fresh(c)
        return _nocache(search.search(c, q, min(max(limit, 1), 300)))
    finally:
        c.close()


@app.get("/api/search/suggest")
def api_search_suggest(q: str = Query(..., min_length=1)):
    from . import search
    c = con()
    try:
        search.ensure_fresh(c)
        return _nocache(search.suggest(c, q))
    finally:
        c.close()


@app.post("/api/mcp")
async def api_mcp(request: Request):
    """SleePO's MCP tools (assist/mcp_server.py) for the Claude desktop app, through the relay ~/.assist/sleepo_mcp.py: macOS
    does not let processes the desktop app starts read the OneDrive folder (14 Oct 2026: "Operation not permitted"), so the
    relay runs outside it and asks this server. One JSON-RPC message or batch in, its response out; every tool reads only."""
    from . import mcp_server
    try:
        msg = await request.json()
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    if isinstance(msg, list):
        out = [r for r in await asyncio.gather(*(asyncio.to_thread(mcp_server.handle, m) for m in msg)) if r]
    else:
        out = await asyncio.to_thread(mcp_server.handle, msg)
    return JSONResponse(out) if out else JSONResponse(None, status_code=202)   # 202: a notification, nothing to answer


@app.get("/api/items")
def api_items(source: str = None, q: str = None, limit: int = 200, offset: int = 0):
    c = con()
    try:
        where, args = [], []
        if source:
            where.append("source_id=?"); args.append(source)
        if q:
            where.append("(subject LIKE ? OR text LIKE ? OR from_name LIKE ?)"); args += [f"%{q}%"] * 3
        # conv_kind: the chat's own type from the pull (dm | group | channel | meeting), when stored; the Messages page sections by it.
        # conv_id and conv_title: a group or meeting chat's id and one title for it (chatsync.chat_titles; Sam, 17 Nov 2026), so
        # the page shows one row per chat however the pulls named its messages
        sql = ("SELECT id, source_id, kind, ts, from_name, subject, text, thread, url, noise, "
               "(SELECT conversation_kind FROM chat_messages c WHERE c.item_id=items.id) AS conv_kind, "
               "(SELECT conversation_id FROM chat_messages c WHERE c.item_id=items.id) AS conv_id FROM items"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ? OFFSET ?")
        rows = [dict(r) for r in c.execute(sql, args + [limit, offset])]
        groups = [r["conv_id"] for r in rows if r["conv_id"] and r["conv_kind"] in ("group", "meeting")]
        from . import chatsync
        titles = chatsync.chat_titles(c, groups) if groups else {}
        for r in rows:
            r["conv_title"] = titles.get(r["conv_id"]) if r["conv_kind"] in ("group", "meeting") else None
        return rows
    finally:
        c.close()


@app.get("/api/todo")
def api_todo():
    from . import todo
    c = con()
    try:
        return _nocache(todo.listing(c))
    finally:
        c.close()


@app.post("/api/todo/generate")
def api_todo_generate():
    from . import todo
    return {"started": todo.start()}


class TodoPatch(BaseModel):
    status: str
    snooze_until: Optional[str] = None


@app.patch("/api/todo/{tid}")
def api_todo_patch(tid: str, body: TodoPatch):
    from . import todo
    c = con()
    try:
        todo.set_status(c, tid, body.status, body.snooze_until)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/todo/{tid}/sources")
def api_todo_sources(tid: str):
    """What an action is about, resolved for the page: the email it answers, the message, the open item, the meeting."""
    from . import action_context
    c = con()
    try:
        row = c.execute("SELECT * FROM todo WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(404)
        return _nocache(action_context.sources(c, row))
    finally:
        c.close()


class TodoAct(BaseModel):
    step: int
    prompt: Optional[str] = None


@app.post("/api/todo/{tid}/act")
def api_todo_act(tid: str, body: TodoAct, request: Request):
    """Open a create / draft step in Claude with its context pack (assist/action_context.py). JSON only (forces a CORS
    preflight from other origins); nothing runs in Claude until Sam presses send there."""
    if not (request.headers.get("content-type") or "").startswith("application/json"):
        raise HTTPException(415, "JSON body required")
    from . import action_context
    c = con()
    try:
        return action_context.act(c, tid, body.step, body.prompt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@app.get("/api/items/{item_id}/links")
def api_item_links(item_id: int):
    """Everyone and everything one item is linked to, with role, evidence and Sam's verdicts."""
    from . import entities
    c = con()
    try:
        return _nocache(entities.entities_of(c, item_id))
    finally:
        c.close()


LIVE_EVERY = 10   # seconds between 'data' events while the database keeps changing


@app.get("/api/events")
async def events():
    """Server-sent events: 'data' when the database changes, 'code' when the page template changes. While a job keeps
    writing, 'data' goes at most every LIVE_EVERY seconds (6 Nov 2026: each one makes every open tab refetch everything;
    every 1.5 s, two tabs sent 1,200 requests in 40 s and pages waited 17 to 48 s). A change after a quiet spell goes at once."""
    async def stream():
        data, code = _versions()
        sent = 0.0
        yield f"event: hello\ndata: {code}\n\n"
        while True:
            await asyncio.sleep(1.5)
            d, c = _versions()
            if c is not None and c != code:
                code = c
                yield f"event: code\ndata: {c}\n\n"
            elif d != data and time.monotonic() - sent >= LIVE_EVERY:
                data, sent = d, time.monotonic()
                yield f"event: data\ndata: {d}\n\n"
            else:
                yield ": keepalive\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/sources/status")
def api_sources_status():
    """Every source stream with its last successful pull and its state (assist/source_status.py, shared with /api/sources)."""
    from . import source_status
    c = con()
    try:
        return _nocache(source_status.streams(c))
    finally:
        c.close()


@app.get("/api/action-profile")
def api_action_profile(days: int = 30, fresh: int = 0):
    """Every kind of action Sam takes and how he takes it (frequency, timing, people, channels), from his own data."""
    from . import action_profile
    c = con()
    try:
        return _nocache(action_profile.profile(c, days=max(7, min(days, 90)), fresh=bool(fresh)))
    finally:
        c.close()


@app.post("/api/agents/{key}/run")
def api_agent_run(key: str):
    """Run one agent now. The full refresh goes through the normal refresh; every other agent runs as its own process."""
    from . import agent_runner
    if key == "refresh":
        return post_refresh("full")
    if STATE.get("running"):
        raise HTTPException(409, "The full refresh is running; it includes this agent.")
    try:
        return agent_runner.start(key, ASSIST)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/agents/{key}/log")
def api_agent_log(key: str, lines: int = 600):
    """The raw log: the full refresh's live log, or the latest manual run of this agent."""
    from . import agent_runner
    lines = max(50, min(lines, 3000))
    if key == "refresh":
        return _nocache({"running": bool(STATE.get("running")), "started": STATE.get("started"), "finished": STATE.get("finished"),
                         "ok": STATE.get("ok"), "lines": (STATE.get("log") or "").splitlines()[-lines:], "source": "refresh"})
    t = agent_runner.tail(key, lines) if key in agent_runner.STEPS else None
    if not t:
        return _nocache({"running": False, "lines": [], "source": None})
    s = t["status"]
    return _nocache({"running": s.get("running"), "started": s.get("started"), "finished": s.get("finished"), "ok": s.get("ok"),
                     "lines": t["lines"], "source": "manual"})


@app.get("/api/agents")
def api_agents():
    """Every agent: running now (refresh phases, meeting briefs, replies, initiative jobs, detached runs, live Claude processes),
    the registry with last run and outcome, and the recent run log."""
    from . import agents
    c = con()
    try:
        prog = _progress() if STATE.get("running") else (None, None)
        return _nocache(agents.snapshot(c, state=STATE, prep_jobs=PREP_JOBS, progress=prog))
    finally:
        c.close()


@app.get("/status")
def status():
    progress, left = _progress() if STATE["running"] else (None, None)
    elapsed = round(time.time() - STATE["started_ts"]) if STATE.get("started_ts") and STATE["running"] else None
    return JSONResponse({**STATE, "progress": progress, "eta_secs": left, "elapsed_secs": elapsed}, headers={"Cache-Control": "no-store"})


@app.on_event("startup")
def _start_scheduler():
    """Automatic runs (assist/scheduler.py): the morning full refresh, and a quick sync every 30 minutes through the working day.
    Both go through post_refresh, so they never overlap a running refresh."""
    from . import scheduler
    if not db.DEMO:   # sign-ins, for the header (the demo copy runs nothing by itself)
        connections.check_in_background("startup", ASSIST, older_than=connections.REWRITE_AFTER)
    scheduler.start(con, lambda: post_refresh("full"), lambda: bool(STATE.get("running")), log=lambda m: STATE.__setitem__("sched_log", m),
                    run_sync=lambda: post_refresh("sync"))


class Feedback(BaseModel):
    target_type: str
    target_id: str
    rating: Optional[int] = None
    copied: Optional[bool] = None
    edit_ratio: Optional[float] = None
    note: Optional[str] = None


@app.post("/api/feedback")
def api_feedback(body: Feedback):
    """Sam's feedback on something an agent produced (thumbs, copied, how much he edited). Feeds evaluation and tuning."""
    if body.target_type not in ("action", "brief", "prep", "reply", "loop", "initiative"):
        raise HTTPException(400, "unknown target_type")
    c = con()
    try:
        c.execute("INSERT INTO feedback (target_type, target_id, rating, copied, edit_ratio, note, created_at) VALUES (?,?,?,?,?,?,?)",
                  (body.target_type, body.target_id[:200], body.rating if body.rating in (-1, 1) else None,
                   1 if body.copied else None if body.copied is None else 0, body.edit_ratio, (body.note or "")[:1000] or None, db.now()))
        c.commit()
        return {"ok": True}
    finally:
        c.close()


@app.get("/api/llm/costs")
def api_llm_costs(days: int = 7):
    from . import llm
    c = con()
    try:
        return _nocache({"days": days, "by_purpose": llm.costs(c, days)})
    finally:
        c.close()


@app.get("/api/schedule")
def api_schedule():
    from . import scheduler
    c = con()
    try:
        return _nocache({**scheduler.config(c), "next": scheduler.next_run(c)})
    finally:
        c.close()


@app.post("/refresh")
def post_refresh(mode: str = "sync", documents: int = 1):
    if mode not in ("sync", "full"):
        raise HTTPException(400, "mode must be sync or full")
    with LOCK:
        if STATE["running"]:
            return JSONResponse({"started": False, "reason": "already running"}, status_code=409)
        threading.Thread(target=worker, args=(mode, bool(documents)), daemon=True).start()
    return {"started": True, "mode": mode}


REBUILDING = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Assist</title><style>body{font:14px system-ui;background:#fafafa;color:#0a0a0a;display:grid;place-items:center;height:100vh;margin:0}
@media (prefers-color-scheme:dark){body{background:#0a0a0a;color:#f5f5f5}}</style>
<p>Updating the app… this page reloads by itself.</p><script>setTimeout(()=>location.reload(),1500)</script>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    """The React app. While a build is rewriting dist/, wait for it."""
    for _ in range(20):
        try:
            return HTMLResponse((WEB_DIST / "index.html").read_text(), headers={"Cache-Control": "no-store"})
        except FileNotFoundError:
            await asyncio.sleep(0.25)
    return HTMLResponse(REBUILDING, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- route groups (assist/routes/), included before the catch-all file routes below
from .routes import chat as _chat, companies as _companies, connections as _connections, drafts as _drafts, initiative_work as _ini_work, knowledge as _knowledge, mail as _mail, meetings as _meetings, memory as _memory, profile as _profile_routes, messages as _messages, onboarding as _onboarding, people as _people, tasks as _task_routes, ui as _ui  # noqa: E402

for _group in (_chat, _companies, _connections, _drafts, _ini_work, _knowledge, _mail, _meetings, _memory, _profile_routes, _messages, _onboarding, _people, _task_routes, _ui):
    app.include_router(_group.router)
from .routes import actions as _actions_routes  # noqa: E402  (the Actions page, assist/actions_view.py)
app.include_router(_actions_routes.router)
from .routes import graph_memory as _graph_memory  # noqa: E402  (DESIGN-GRAPH-MEMORY.md)
app.include_router(_graph_memory.router)
from .routes import codebase as _codebase_routes  # noqa: E402  (Knowledge › Product › Code base, assist/codebase.py)
app.include_router(_codebase_routes.router)
PREP_JOBS = _meetings.PREP_JOBS   # the Agents page's view of running meeting briefs


@app.get("/{name}.{ext}", include_in_schema=False)
def web_root_icon(name: str, ext: str):
    """App icons that sit at the root of the build (favicon.svg, apple-touch-icon.png)."""
    if ext not in ("svg", "png", "ico") or not re.fullmatch(r"[\w-]+", name):
        raise HTTPException(404)
    f = WEB_DIST / f"{name}.{ext}"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(str(f), headers={"Cache-Control": "public, max-age=86400"})


@app.get("/assets/{path:path}")
async def web_assets(path: str):
    f = (WEB_DIST / "assets" / path).resolve()
    if not f.is_relative_to((WEB_DIST / "assets").resolve()):   # a path check, not a string prefix ("assets-old" is not inside)
        raise HTTPException(404)
    for _ in range(20):  # a build may be rewriting dist/ right now
        if f.exists():
            break
        await asyncio.sleep(0.25)
    else:
        raise HTTPException(404)
    return FileResponse(str(f), headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/Granola Export/{path:path}")
def granola_file(path: str):
    f = (ROOT / "Granola Export" / path).resolve()
    if not f.is_relative_to((ROOT / "Granola Export").resolve()) or not f.exists():
        raise HTTPException(404)
    return FileResponse(str(f))
