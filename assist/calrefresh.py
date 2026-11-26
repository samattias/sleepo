"""Meetings › Refresh as a background job (Sam, 23 Oct 2026). It used to be one 20-second request, which a server reload
(any save under assist/) cut off, and the page then said "Failed to fetch". It now runs as its own process
(`assist.cli calendar-refresh`, one at a time), with its state in a file outside OneDrive, and the page follows it.

The steps are unchanged: Calendar.app's store (assist/applecal.py), then Granola's new notes unless the full refresh is
pulling them right now (granola_update.py, collect_granola --prune, sync-granola), then the recordings re-matched
(reconcile_calendar.py) and the calendar reloaded (calendar-import). A Granola failure is reported, not fatal. Calendar.app
exit 2 (no Full Disk Access) and 3 (not synced lately) end the run with the message the page shows, as the 503s did.
"""
import json
import subprocess
import time

from . import db, jobs, web

ASSIST = db.ASSIST
ROOT = ASSIST.parent
PY = jobs.PY
STATE = db.db_path().parent / "jobs" / "calendar_refresh.json"
NO_ACCESS = ("SleePO cannot read Calendar.app (no Full Disk Access for the server's Python). The full refresh still pulls the "
             "calendar through Outlook.")


def _lines(p):
    return [x for x in ((p.stdout or "") + (p.stderr or "")).splitlines() if x.strip()]


def run(dry=False, granola=True):
    """The refresh itself. Returns {ok, secs, log, granola, error, code}; code is the HTTP status the page used to get."""
    t0 = time.time()
    p = subprocess.run([PY, "-m", "assist.cli", "calendar-local"] + (["--dry-run"] if dry else []), cwd=str(ASSIST),
                       capture_output=True, text=True, timeout=300)
    lines = _lines(p)
    out = {"ok": False, "secs": None, "log": lines[-60:], "granola": None, "error": None, "code": 200}
    if p.returncode == 2:
        return out | {"error": NO_ACCESS, "code": 503}
    if p.returncode == 3:
        return out | {"error": (lines[-1] if lines else "Calendar.app has not synced recently").lstrip("! "), "code": 503}
    if p.returncode != 0:
        return out | {"error": f"Calendar import failed: {(lines[-1:] or ['no output'])[0][:200]}", "code": 500}
    g_note = None
    if not dry:
        if not granola:
            g_note = "skipped: a refresh is pulling Granola now"
        else:
            g = subprocess.run(["/usr/bin/python3", web.granola_script()], cwd=str(web.granola_dir()), capture_output=True, text=True, timeout=300)
            if g.returncode == 0:
                subprocess.run(["/usr/bin/python3", str(db.APP / "scripts" / "collect_granola.py"), "--prune"], cwd=str(ASSIST), capture_output=True, text=True, timeout=120)
                subprocess.run([PY, "-m", "assist.cli", "sync-granola"], cwd=str(ASSIST), capture_output=True, text=True, timeout=300)
                g_note = "ok"
            else:
                g_note = "failed: " + ((_lines(g)[-1:] or ["no output"])[0][:160])
            lines.append("granola: " + g_note)
        subprocess.run(["/usr/bin/python3", str(db.APP / "scripts" / "reconcile_calendar.py")], cwd=str(ASSIST), capture_output=True, text=True, timeout=120)
        subprocess.run([PY, "-m", "assist.cli", "calendar-import"], cwd=str(ASSIST), capture_output=True, text=True, timeout=300)
    return out | {"ok": True, "secs": round(time.time() - t0, 1), "log": lines[-60:], "granola": g_note}


def state():
    """{running, started, finished, ok, secs, log, granola, error, code} of the last or current run."""
    try:
        d = json.loads(STATE.read_text())
    except Exception:
        d = {"running": False}
    if d.get("running") and not jobs.held("calendar-refresh"):
        if d.get("pid") and jobs._alive(d["pid"]):
            return d   # just started, not holding the lock yet
        d.update(running=False, ok=False, error=d.get("error") or "The refresh stopped before it finished. Try again.")
    return d


def write(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    tmp.replace(STATE)


def start(granola=True):
    """Start a run unless one is going; returns the state either way."""
    d = state()
    if d.get("running"):
        return d
    write({"running": True, "started": db.now(), "pid": None})
    pid = jobs.spawn_cli("calendar-refresh", *([] if granola else ["--no-granola"])).pid
    write({"running": True, "started": db.now(), "pid": pid})
    return state()


def main(granola=True):
    """Body of `assist.cli calendar-refresh`."""
    with jobs.exclusive("calendar-refresh") as got:
        if not got:
            print("calendar-refresh: another run is going")
            return
        started = (state().get("started") or db.now())
        try:
            r = run(granola=granola)
        except Exception as e:
            r = {"ok": False, "error": str(e)[-200:], "code": 500}
        write({"running": False, "started": started, "finished": db.now(), **r})
