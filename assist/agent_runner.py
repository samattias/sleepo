"""Run one agent by hand, as its own process, with a readable log.

`assist.cli agent-run <key>` runs the steps below and writes every line to a log file; a status file says whether it is
running, when it started and finished, and whether it worked. Both live outside OneDrive (Application Support/Assist/
jobs/agents) and are kept for 7 days. Because the run is a separate process, a server reload cannot cut it off.
Claude steps stream their progress (what Claude says and each tool it uses, never the content it reads) into the log,
and copies the connector leaves behind are removed afterwards, exactly as in the full refresh.

The full refresh is not run from here: the Agents page starts it through the normal refresh endpoint, whose log it shows.
Reply drafting runs per email, from the Replies page.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import db

JOB_DIR = db.db_path().parent / "jobs" / "agents"
PY = os.path.expanduser("~/.assist/venv/bin/python")
NO_SEND = " Do not send anything."
STEPS = {
    "mail": [("claude", "Run the /mail-full skill so new Inbox and Sent mail is stored in full." + NO_SEND), ("cli", ["ingest"])],
    "chat": [("claude", "Pull Teams and Slack since the last pull recorded in the database (~/.assist/venv/bin/python -m assist.cli stats), "
                        "paginating to the end of each window, following the '1. Gather' steps of the /brief skill for Teams and Slack only. "
                        "Write ONE ingest bundle inbox/queue/pull-chat-<now>.json following assist/ingest.py (pulls, chat_messages: every "
                        "message verbatim, never a summary; source_health, gaps) and run ~/.assist/venv/bin/python -m assist.cli ingest. Do not write a brief." + NO_SEND), ("cli", ["link"])],
    "salesforce": [("claude", "Run the /salesforce skill to refresh open pipeline (company and deal data only)." + NO_SEND), ("cli", ["ingest"])],
    "docs": [("claude", "Run the /docs-read skill (reads up to 15 recent SharePoint/OneDrive files in full through read_resource, then stores them)." + NO_SEND),
             ("cli", ["doc-cards"])],
    "linking": [("cli", ["link"])],
    "loops": [("cli", ["loops", "all"])],
    "initiatives": [("cli", ["ini-tag", "--days", "7"])],
    "todo": [("cli", ["tasks", "suggest"])],   # key kept (agents.REGISTRY, soul.USES): Tasks replaced the Actions list on 22 Oct
    "brief": [("cli", ["brief"])],
    "prep": [("cli", ["prep-write", "--upcoming", "--days", "1"])],   # tool-free (assist/prepgen.py)
}
NOT_RUNNABLE = {"refresh": "Use Run full refresh", "replies": "Runs per email, from Replies", "deliverables": "Runs per email, from the Inbox",
                "briefings": "Runs per email, from the Inbox"}


def _status_path(key):
    if key not in STEPS:
        raise ValueError("unknown agent")
    return JOB_DIR / f"{key}.json"


def status(key):
    p = JOB_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text())
    except ValueError:
        return None
    if s.get("running"):   # the process died without writing its end
        try:
            os.kill(int(s.get("pid") or 0), 0)
        except (OSError, ValueError):
            s.update(running=False, ok=False, error="The run stopped without finishing.")
    return s


def _write_status(key, s):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JOB_DIR / f"{key}.tmp"
    tmp.write_text(json.dumps(s))
    os.chmod(tmp, 0o600)
    tmp.replace(JOB_DIR / f"{key}.json")


def start(key, cwd):
    """Start a manual run of one agent in its own process. Returns the status, or raises if it cannot start."""
    if key in NOT_RUNNABLE:
        raise ValueError(NOT_RUNNABLE[key])
    _status_path(key)
    cur = status(key)
    if cur and cur.get("running"):
        raise RuntimeError("already running")
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    for f in JOB_DIR.glob("*.log"):   # keep a week of logs
        if time.time() - f.stat().st_mtime > 7 * 86400:
            f.unlink(missing_ok=True)
    logf = JOB_DIR / f"{key}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    logf.touch(mode=0o600)
    from . import jobs
    p = jobs.spawn_cli("agent-run", key, logf, cwd=cwd)
    s = {"key": key, "running": True, "ok": None, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished": None, "pid": p.pid,
         "log": logf.name, "manual": True}
    _write_status(key, s)
    return s


def _fmt_stream(line, out):
    from . import connections
    connections.seen_init(line, "agent")   # which connectors are signed in (assist/connections.py)
    try:
        ev = json.loads(line)
    except ValueError:
        out(line.rstrip())
        return
    if ev.get("type") == "assistant":
        for c in ev.get("message", {}).get("content", []):
            if c.get("type") == "text" and c.get("text", "").strip():
                out("  " + c["text"].strip().replace("\n", " ")[:400])
            elif c.get("type") == "tool_use":
                inp = c.get("input") or {}
                name = c.get("name", "").replace("mcp__claude_ai_", "")
                what = (f"Skill:{inp.get('skill')}" if name == "Skill" else inp.get("command", "")[:200] if name == "Bash"
                        else f"{name} {inp.get('file_path', '')}" if name in ("Read", "Write", "Edit") else name)
                out(f"  → {what}")
    elif ev.get("type") == "result":
        from . import llm
        llm.record_stream_result(ev, "agent-run")   # cost and tokens into llm_calls
        out(f"  Claude finished: {ev.get('subtype')} in {round((ev.get('duration_ms') or 0) / 1000)}s, {ev.get('num_turns')} turns")


def run(key, logpath, cwd):
    """Body of `assist.cli agent-run <key> <log>`."""
    logf = Path(logpath)
    s = status(key) or {"key": key, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "log": logf.name, "manual": True}
    s.update(running=True, pid=os.getpid())
    _write_status(key, s)
    fh = logf.open("a", buffering=1)

    def out(t):
        fh.write(f"{time.strftime('%H:%M:%S')} {t}\n")

    ok, started = True, time.time()
    try:
        from .api import ALLOWED, PROTECTED, PULL_MODE, PULL_SETTINGS, purge_tool_copies
    except Exception:   # the API module is only needed for Claude steps; without its allow list a Claude step may do nothing
        ALLOWED, PROTECTED, PULL_MODE, PULL_SETTINGS, purge_tool_copies = [], [], "default", ["--setting-sources", "user,project"], None
    env = dict(os.environ, CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="1800000")
    for kind, arg in STEPS[key]:
        if kind == "cli":
            cmd = [PY, "-m", "assist.cli", *arg]
            out("$ assist.cli " + " ".join(arg))
            p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
            for line in p.stdout:
                out("  " + line.rstrip())
            p.wait()
        else:
            claude = os.path.expanduser("~/.local/bin/claude")
            cmd = [claude if os.path.exists(claude) else "claude", "-p", arg, "--permission-mode", PULL_MODE, *PULL_SETTINGS, "--output-format", "stream-json",
                   "--verbose", "--allowedTools", *ALLOWED, "--disallowedTools", *PROTECTED]
            out("$ claude -p (" + re.sub(r"\s+", " ", arg)[:90] + "…)")
            t0 = time.time()
            p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
            for line in p.stdout:
                _fmt_stream(line, out)
            p.wait()
            if purge_tool_copies:
                try:
                    purge_tool_copies(t0)
                except Exception:
                    pass
        out(f"(exit {p.returncode})")
        ok &= p.returncode == 0
    out(f"Finished {'OK' if ok else 'with errors'} in {round(time.time() - started)}s")
    fh.close()
    s.update(running=False, ok=ok, finished=time.strftime("%Y-%m-%dT%H:%M:%S"), secs=round(time.time() - started))
    _write_status(key, s)
    return ok


def tail(key, lines=600):
    """The latest manual run's log for one agent (last lines), with its status."""
    s = status(key)
    if not s or not s.get("log"):
        return None
    p = JOB_DIR / s["log"]
    text = p.read_text(errors="replace") if p.exists() else ""
    return {"status": s, "lines": text.splitlines()[-lines:]}


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if run(sys.argv[1], sys.argv[2], db.ASSIST) else 1)
