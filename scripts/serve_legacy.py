#!/usr/bin/env python3
"""Local server for Assist.html with a Refresh button that actually refreshes.

  python3 scripts/serve.py            # http://localhost:8765
  python3 scripts/serve.py 8080       # another port

Routes
  GET  /                      Assist.html (always the current file on disk)
  GET  /Granola Export/...    transcripts and raw notes (the page links to them)
  GET  /status                JSON: {running, mode, started, finished, ok, log}
  POST /refresh?mode=sync     pull Granola, digest, rebuild the page           (~10–60 s)
  POST /refresh?mode=full     sync, then run Claude headless for /brief        (~5–10 min)

The server only runs scripts that live in this folder. It binds to localhost only.
"""
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ASSIST = Path(os.environ.get("ASSIST_DIR") or Path(__file__).resolve().parent.parent)
ROOT = ASSIST.parent  # serve Assist/ and Granola Export/ side by side
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
LOCK = threading.Lock()
STATE = {"running": False, "mode": None, "started": None, "finished": None, "ok": None, "log": ""}

FULL_PROMPT = (
    "Run the /brief skill for today. Pull the calendar for today and the next two working days, and mail, Teams and Slack "
    "since the last live pull, paginating to the end of each window. Write briefs/<today>.md, save the metadata snapshot in "
    "inbox/live/, merge the calendar pull into inbox/calendar/events.json (same schema, replace by id) and run python3 scripts/reconcile_calendar.py, update inbox/coverage.json counts and TASKS.md, then run python3 scripts/build_ui.py. Do not send anything."
)
ALLOWED = [
    "Bash(python3 scripts/*)", "Bash(python3 scripts/collect_granola.py*)", "Bash(python3 scripts/build_ui.py)", "Bash(python3 scripts/reconcile_calendar.py)",
    "Read", "Write", "Edit", "Glob", "Grep", "ToolSearch", "Skill",
    "mcp__claude_ai_Microsoft_365__outlook_calendar_search", "mcp__claude_ai_Microsoft_365__outlook_email_search",
    "mcp__claude_ai_Microsoft_365__chat_message_search", "mcp__claude_ai_Microsoft_365__read_resource",
    "mcp__claude_ai_Microsoft_365__get_me", "mcp__plugin_productivity_slack__slack_search_public_and_private",
    "mcp__plugin_productivity_slack__slack_read_thread", "mcp__plugin_productivity_slack__slack_read_channel",
]


def log(line):
    STATE["log"] += line.rstrip("\n") + "\n"
    STATE["log"] = STATE["log"][-20000:]


def run(cmd, cwd, env=None):
    log(f"$ {' '.join(shlex.quote(c) for c in cmd)}")
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    for line in p.stdout:
        log(line)
    p.wait()
    log(f"(exit {p.returncode})")
    return p.returncode == 0


def refresh(mode):
    env = dict(os.environ)
    try:
        key = subprocess.run(["security", "find-generic-password", "-s", "granola-api", "-a", "sam", "-w"],
                             capture_output=True, text=True).stdout.strip()
        if key:
            env["GRANOLA_API_KEY"] = key
    except Exception:
        pass
    ok = True
    ok &= run(["/usr/bin/python3", "granola_update.py"], ROOT / "Granola Export", env)
    ok &= run(["/usr/bin/python3", "scripts/collect_granola.py", "--prune"], ASSIST, env)
    if mode == "full":
        claude = os.path.expanduser("~/.local/bin/claude")
        if not os.path.exists(claude):
            claude = "claude"
        cmd = [claude, "-p", FULL_PROMPT, "--permission-mode", "acceptEdits", "--output-format", "text", "--allowedTools"] + ALLOWED
        ok &= run(cmd, ASSIST, env)
    ok &= run(["/usr/bin/python3", "scripts/build_ui.py"], ASSIST, env)
    return ok


def worker(mode):
    STATE.update({"running": True, "mode": mode, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "finished": None, "ok": None, "log": ""})
    try:
        STATE["ok"] = refresh(mode)
    except Exception as e:  # pragma: no cover
        log(f"error: {e}")
        STATE["ok"] = False
    STATE["running"] = False
    STATE["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):  # quiet
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html", "/Assist.html"):
            body = (ASSIST / "Assist.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/status":
            return self.send_json(STATE)
        if path.startswith("/Granola%20Export/") or path.startswith("/Granola Export/") or path.startswith("/Assist/"):
            return super().do_GET()
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/refresh":
            return self.send_json({"error": "not found"}, 404)
        mode = urllib.parse.parse_qs(u.query).get("mode", ["sync"])[0]
        if mode not in ("sync", "full"):
            return self.send_json({"error": "mode must be sync or full"}, 400)
        with LOCK:
            if STATE["running"]:
                return self.send_json({"started": False, "reason": "already running"}, 409)
            threading.Thread(target=worker, args=(mode,), daemon=True).start()
        self.send_json({"started": True, "mode": mode})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Assist at http://localhost:{PORT}  (serving {ROOT})")
    srv.serve_forever()
