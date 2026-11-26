"""The demo copy: a second, separate SleePO on this Mac for trying first-run setup as a new user (Sam, 16 Nov 2026: "give
me a way to demo and test this workflow without deleting all my data and settings").

It is a fresh install beside the real one, sharing only the code and the built pages:
  data folder   ~/Library/Application Support/Assist Demo/home   (from templates/data, as scripts/install.sh makes it)
  database      ~/Library/Application Support/Assist Demo/assist.db (jobs, photos and caches sit next to it)
  Keychain      account "sleepo-demo" (a Granola key typed into the demo is kept apart from the real one)
  server        http://localhost:8766, restarted by assist/reload.demo.trigger, never by the real one's
  schedule      off: nothing runs by itself (scheduler.start returns at once when ASSIST_DEMO=1)

It still runs on this Mac as this user: an import the demo user starts reads the same Mail.app, Calendar.app and Granola a
new colleague's would read on their own Mac. Reset deletes the demo folder and its Keychain items, nothing else; the real
install's data folder, database, settings and Keychain items are never opened for writing.

  assist.cli demo [start|stop|reset|status] [--open]
"""
import json
import os
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from . import db

ROOT = Path.home() / "Library" / "Application Support" / "Assist Demo"
HOME = ROOT / "home"
DB = ROOT / "assist.db"
PORT = 8766
ACCOUNT = "sleepo-demo"
TRIGGER = "reload.demo.trigger"
PIDFILE = ROOT / "server.pid"
LOG = ROOT / "server.log"
URL = f"http://localhost:{PORT}/"
KEYCHAIN_SERVICES = ("granola-api", "granola-mcp", "assist-graph")
PY = os.path.expanduser("~/.assist/venv/bin/python")


def env():
    """The demo server's environment: every path and name that would otherwise be the real install's."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("ASSIST_")}
    e.update({"ASSIST_HOME": str(HOME), "ASSIST_DB": str(DB), "ASSIST_KEYCHAIN_ACCOUNT": ACCOUNT, "ASSIST_PORT": str(PORT),
              "ASSIST_DEMO": "1", "ASSIST_RELOAD_TRIGGER": TRIGGER,
              "PYTHONPATH": os.pathsep.join(x for x in (str(db.APP), os.environ.get("PYTHONPATH", "")) if x)})
    if os.environ.get("ASSIST_WEB_DIST"):
        e["ASSIST_WEB_DIST"] = os.environ["ASSIST_WEB_DIST"]
    return e


def _safe(p):
    """Only the demo folder may be deleted: refuse anything else, whatever a caller passes."""
    p = Path(p).resolve()
    return p == ROOT.resolve() and p.name == "Assist Demo" and p.parent.name == "Application Support"


def running():
    try:
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=2).read()) is not None
    except Exception:
        return False


def status():
    made = DB.exists()
    return {"running": running(), "url": URL, "folder": str(ROOT), "created": made,
            "created_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(DB.stat().st_mtime)) if made else None}


def create():
    """The demo's data folder and database, as a new install has them (existing files are kept)."""
    for d in ("inbox/queue", "drafts", "briefs", "org", ".claude"):
        (HOME / d).mkdir(parents=True, exist_ok=True)
    tpl = db.APP / "templates" / "data"
    for src in tpl.rglob("*"):
        dst = HOME / src.relative_to(tpl)
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        elif not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    skills = HOME / ".claude" / "skills"
    if not skills.exists() and (db.APP / ".claude" / "skills").exists():
        shutil.copytree(db.APP / ".claude" / "skills", skills)
    # the database, made by the demo's own environment so nothing reads the real install's paths
    subprocess.run([PY, "-m", "assist.cli", "migrate"], env=env(), cwd=str(HOME), check=True, capture_output=True, timeout=120)


def start(open_browser=False, wait=20):
    if not running():
        create()
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "ab") as out:
            p = subprocess.Popen([PY, "-m", "assist.cli", "serve", str(PORT)], env=env(), cwd=str(HOME), stdout=out, stderr=out,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        PIDFILE.write_text(str(p.pid))
        for _ in range(wait * 4):
            if running():
                break
            time.sleep(0.25)
    if open_browser:
        subprocess.run(["open", URL + "#/welcome"], check=False)
    return status()


def stop():
    """Stop the demo server (its reloader and worker are one process group). Only the pid the demo started is signalled."""
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        pid = None
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        for _ in range(40):
            if not running():
                break
            time.sleep(0.25)
    PIDFILE.unlink(missing_ok=True)
    return status()


def reset(start_after=True, open_browser=False):
    """Back to a brand-new install: stop, delete the demo folder and the demo's Keychain items, start again."""
    stop()
    if ROOT.exists():
        if not _safe(ROOT):
            raise RuntimeError(f"refusing to delete {ROOT}")
        shutil.rmtree(ROOT)
    for service in KEYCHAIN_SERVICES:
        subprocess.run(["security", "delete-generic-password", "-s", service, "-a", ACCOUNT], capture_output=True)
    return start(open_browser) if start_after else status()


def spawn(action):
    """Run `assist.cli demo <action>` detached, so a server can start, stop or reset the demo (even the demo itself) and answer."""
    subprocess.Popen([PY, "-m", "assist.cli", "demo", action, "--later"], cwd=str(db.APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True, env={k: v for k, v in os.environ.items() if not k.startswith("ASSIST_")})


def main(argv):
    action = argv[0] if argv else "status"
    if action in ("stop", "reset") and "--later" in argv:   # spawned by a server: let it answer before this stops it
        time.sleep(1)
    fn = {"start": lambda: start("--open" in argv), "stop": stop, "reset": lambda: reset(True, "--open" in argv), "status": status}.get(action)
    if not fn:
        print("usage: assist.cli demo [start|stop|reset|status] [--open]")
        return 2
    s = fn()
    print(f"demo: {'running at ' + s['url'] if s['running'] else 'stopped'} · folder {s['folder']}{'' if s['created'] else ' (not created)'}")
    return 0
