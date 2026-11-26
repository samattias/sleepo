"""The Slack pull, on its own run beside the Teams one (Sam, 17 Nov 2026: "make the Teams and Slack synchronization much
faster"; Teams: assist/teams_capture.py).

Slack is small (direct messages, group DMs and the followed channels), so its run still writes the messages itself, but it
now runs from the pulls' scratch folder, not the project: the project's CLAUDE.md, loaded from the working folder, is long
and was re-read on every turn. The window comes from the database here (it no longer runs the CLI to find it), the run
writes one JSON file in the scratch folder with its own tool (read-only Slack tools, writes only there), and this module
checks it, files it in inbox/queue and ingests it. Nothing is sent.
"""
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db

SCRATCH = Path("/tmp/assist-pull")
MODEL = "sonnet"          # settings llm_model_pull-slack overrides it
OVERLAP_MIN = 30
FIRST_DAYS = 3
TOOLS = ["slack_search_public_and_private", "slack_search_public", "slack_read_thread", "slack_read_channel",
         "slack_read_user_profile", "slack_search_channels", "slack_search_users"]


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def model(con):
    r = con.execute("SELECT value FROM settings WHERE key='llm_model_pull-slack'").fetchone()
    return (r[0] if r and r[0] else MODEL)


def window(con, span=None, now=None):
    """(from, to): since the last complete Slack pull less OVERLAP_MIN (3 days with none), or a backfill span of dates."""
    now = now or datetime.now(timezone.utc)
    if span:
        return f"{span[0]}T00:00:00Z", f"{span[1]}T00:00:00Z"
    last = con.execute("SELECT MAX(finished_at) FROM pulls WHERE source_id='slack' AND complete=1").fetchone()[0]
    start = (datetime.fromisoformat(last.replace("Z", "+00:00")) - timedelta(minutes=OVERLAP_MIN)) if last else now - timedelta(days=FIRST_DAYS)
    return _iso(start), None


def prompt(win, scope, path):
    since, until = win
    span = f"from {since} to {until}" if until else f"since {since}"
    return (
        "SLACK pull, read only, with the mcp__claude_ai_Slack__ tools. Do not send anything, run commands, or read anything else.\n"
        f"1. Read every message {span} (UTC) in {scope}, replies in threads too, each search or read paginated to the end. Direct "
        "messages and group DMs are read by searching them (there is no tool to list them one by one): a search paginated to the end "
        "counts as reading them to the end. Other Slack channels are background: do not read them, and they never make the pull "
        "incomplete.\n"
        f"2. Write ONE file, {path}, with the Write tool: JSON {{\"pulls\": [{{\"source_id\": \"slack\", \"window_from\": \"{since}\", "
        "\"available\": <messages found>, \"pulled\": <messages written>, \"noise\": <bots and notifications>, \"complete\": <true when "
        "every search and read in step 1 was paginated to the end; false only when one failed or stopped early>, \"note\": \"what was "
        "read, in a line\"}], "
        "\"chat_messages\": [...], \"gaps\": [<anything not read, in words>]}. Each message: {\"source_id\": \"slack\", \"external_id\": "
        "\"<channel id>:<message ts>\", \"conversation_id\": \"<channel id>\", \"conversation_name\": \"DM <their full name>\" or "
        "\"Group DM <their names>\" or \"#<channel name>\", \"conversation_kind\": \"dm\" or \"group\" or \"channel\", \"ts\": "
        "\"YYYY-MM-DDTHH:MM:SSZ\", \"author\": \"<full name>\", \"body_text\": \"<the message, verbatim; links as [title](url)>\", "
        "\"thread_parent\": <the parent's ts or null>, \"web_link\": \"<permalink>\", \"noise\": <true for bots and notifications>}. "
        "Never a summary. With nothing new, still write the file, with its pulls row and an empty chat_messages.\n"
        "Then answer with one line: messages written, and what could not be read.")


def run(claude, model_name, scope, span=None, env=None, log=print, on_result=None):
    """One Slack pull. Returns (ok, note). on_result(ev) gets the run's final stream-json event."""
    from . import connections
    con = db.connect()
    try:
        win = window(con, span)
    finally:
        con.close()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="slack-", dir=SCRATCH))
    path = folder / "bundle.json"
    t0 = time.time()
    try:
        cmd = [claude, "-p", prompt(win, scope, path), "--model", model_name, "--permission-mode", "default",
               "--setting-sources", "user,project", "--output-format", "stream-json", "--verbose",
               "--allowedTools", *[f"mcp__claude_ai_Slack__{t}" for t in TOOLS], "Write(//tmp/assist-pull/**)",
               "Write(//private/tmp/assist-pull/**)", "Edit(//tmp/assist-pull/**)", "Edit(//private/tmp/assist-pull/**)",
               "--disallowedTools", "Bash", "NotebookEdit", "Task", "Agent", "mcp__claude_ai_Microsoft_365"]
        p = subprocess.run(cmd, cwd=str(folder), env=env or os.environ, capture_output=True, text=True, timeout=1200)
        answer = ""
        for line in (p.stdout or "").splitlines():
            connections.seen_init(line, "slack-pull")
            if '"type":"result"' in line.replace(" ", ""):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                answer = str(ev.get("result") or "")[:300]
                if on_result:
                    on_result(ev)
        try:
            b = json.loads(path.read_text())
        except (OSError, ValueError):
            log(f"Slack: no readable bundle came back ({answer or p.returncode})")
            return False, f"Slack not pulled: {answer or 'no bundle written'}"[:300]
        msgs = [m for m in b.get("chat_messages") or [] if isinstance(m, dict) and m.get("external_id") and m.get("ts")]
        pulls = [x for x in b.get("pulls") or [] if isinstance(x, dict)] or [{"source_id": "slack", "window_from": win[0], "complete": False}]
        for x in pulls:
            x["source_id"] = "slack"
            x.setdefault("window_from", win[0])
            x["window_to"] = win[1] or _iso(datetime.now(timezone.utc))
            x["note"] = f"{x.get('note') or ''} ({round(time.time() - t0)} s)".strip()
        out = {"agent": "assist:slack-pull", "prompt_version": "slack-pull-2026-11-17", "pulls": pulls,
               "chat_messages": [dict(m, source_id="slack") for m in msgs], "gaps": [g for g in b.get("gaps") or [] if isinstance(g, str)]}
        dest = db.ASSIST / "inbox" / "queue" / f"pull-slack-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        ing = subprocess.run([os.path.expanduser("~/.assist/venv/bin/python"), "-m", "assist.cli", "ingest", str(dest)], cwd=str(db.ASSIST),
                             env=env or os.environ, capture_output=True, text=True, timeout=600)
        complete = all(bool(x.get("complete")) for x in pulls)
        log(f"Slack: {len(msgs)} messages{'' if complete else ', NOT complete'} ({round(time.time() - t0)} s)")
        return complete and ing.returncode == 0, pulls[0].get("note") or ""
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
