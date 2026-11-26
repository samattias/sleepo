"""Automatic runs: the full refresh every working morning, without anyone pressing Refresh.

A background thread in the app server checks once a minute. On the configured days, once the local time passes the
configured time and today's morning run has not happened, it starts the full refresh. If the Mac was asleep at that time,
the run happens when it wakes, up to the catch-up cut-off, so a late wake does not trigger a surprise afternoon run.

Settings (table `settings`, editable; defaults in brackets):
  schedule_morning      "06:45"   local time (Europe/London)
  schedule_days         "mon,tue,wed,thu,fri"
  schedule_catchup_until "14:00"  no automatic morning run after this time
  schedule_enabled      "1"       "0" turns automatic runs off
  schedule_last_morning           date of the last automatic morning run (written here)
"""
import threading
import time
from datetime import datetime, timedelta
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from . import profile

try:
    from zoneinfo import ZoneInfo
    LONDON = profile.zone()
except Exception:  # pragma: no cover
    LONDON = None

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULTS = {"schedule_morning": "06:45", "schedule_days": "mon,tue,wed,thu,fri", "schedule_catchup_until": "14:00", "schedule_enabled": "1",
            # quick sync (Granola, Apple Mail inbox and sent, local files, documents; no Claude) through the working day, so new meeting notes appear
            "schedule_sync_every": "30", "schedule_sync_from": "08:00", "schedule_sync_until": "19:00", "schedule_sync_enabled": "1"}
_STARTED = False
_LOCK = threading.Lock()


def _get(con, key):
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r and r["value"] is not None else DEFAULTS.get(key)


def config(con):
    return {k: _get(con, k) for k in list(DEFAULTS) + ["schedule_last_morning", "schedule_last_sync"]}


def sync_due(con, now=None):
    """A quick sync is due: working day, inside the day window, and the last one (scheduled or not) is older than the interval."""
    c = config(con)
    if c["schedule_sync_enabled"] != "1" or not LONDON:
        return False
    now = now or datetime.now(LONDON)
    days = [d.strip()[:3] for d in (c["schedule_days"] or "").split(",") if d.strip()]
    if DAYS[now.weekday()] not in days or not (c["schedule_sync_from"] <= now.strftime("%H:%M") < c["schedule_sync_until"]):
        return False
    try:
        last = datetime.fromisoformat(c.get("schedule_last_sync") or "2000-01-01T00:00:00+00:00")
    except ValueError:
        last = datetime(2000, 1, 1, tzinfo=LONDON)
    return (now - last).total_seconds() >= int(c["schedule_sync_every"] or 30) * 60


def next_run(con, now=None):
    """When the next automatic morning run is due (local time), for display."""
    c = config(con)
    if c["schedule_enabled"] != "1":
        return None
    now = now or datetime.now(LONDON)
    days = [d.strip()[:3] for d in (c["schedule_days"] or "").split(",") if d.strip()]
    hh, mm = (int(x) for x in c["schedule_morning"].split(":"))
    for i in range(0, 8):
        d = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=i)
        if DAYS[d.weekday()] in days and d > now:
            return d.isoformat(timespec="minutes")
    return None


def due(con, now=None):
    c = config(con)
    if c["schedule_enabled"] != "1" or not LONDON:
        return False
    now = now or datetime.now(LONDON)
    days = [d.strip()[:3] for d in (c["schedule_days"] or "").split(",") if d.strip()]
    if DAYS[now.weekday()] not in days:
        return False
    hm = now.strftime("%H:%M")
    if not (c["schedule_morning"] <= hm < c["schedule_catchup_until"]) or c.get("schedule_last_morning") == now.date().isoformat():
        return False
    return not _full_refresh_today(now)


def _full_refresh_today(now):
    """A full refresh already finished today (e.g. started by hand) counts as the morning run."""
    import json
    from . import db
    try:
        h = json.loads((db.db_path().parent / "refresh_history.json").read_text())
    except (OSError, ValueError):
        return False
    return any((r.get("finished") or "").startswith(now.date().isoformat()) and r.get("ok") for r in h.get("full", []))


def start(connect, run_full, is_running, log=print, run_sync=None):
    """Start the checker once per process. connect() -> sqlite connection; run_full() starts the refresh; is_running() -> bool."""
    global _STARTED
    from . import db
    if db.DEMO:   # the demo copy (assist/demo.py) runs nothing by itself: imports happen when its user starts them
        return
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True

    def loop():
        time.sleep(20)   # let the server finish starting
        while True:
            try:
                con = connect()
                try:
                    if due(con) and not is_running():
                        today = datetime.now(LONDON).date().isoformat()
                        # claim the day first (atomically), so a reload or a second process never starts a second run
                        cur = con.execute("INSERT INTO settings (key, value) VALUES ('schedule_last_morning', ?) ON CONFLICT(key) DO UPDATE "
                                          "SET value=excluded.value WHERE settings.value IS NOT excluded.value", (today,))
                        claimed = cur.rowcount == 1
                        con.commit()
                        if claimed:
                            log(f"scheduler: starting the morning full refresh ({today})")
                            run_full()
                    elif run_sync and sync_due(con) and not is_running():
                        stamp = datetime.now(LONDON).isoformat(timespec="seconds")
                        prev = config(con).get("schedule_last_sync")
                        # claim the slot atomically (a reload or second process must not double-run)
                        cur = con.execute("INSERT INTO settings (key, value) VALUES ('schedule_last_sync', ?) ON CONFLICT(key) DO UPDATE "
                                          "SET value=excluded.value WHERE settings.value IS ?", (stamp, prev))
                        con.commit()
                        if cur.rowcount == 1:
                            log(f"scheduler: quick sync ({stamp})")
                            run_sync()
                finally:
                    con.close()
            except Exception as e:  # never let the checker die
                log(f"scheduler: {e}")
            time.sleep(60)
    threading.Thread(target=loop, name="assist-scheduler", daemon=True).start()
