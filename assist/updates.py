"""Versions and updates (Sam, 26 Nov 2026: "how do I do the versioning? Is there a way they can check for updates and have it
pull from GitHub?"; then "build this and also add a manual check for update button under the person's icon").

A release is a git tag on the public repository, named by date (v2026.11.26; a second one that day v2026.11.26.1), with a
GitHub Release whose notes are the changelog entries since the previous one (scripts/export_code.py --release / --publish).
The code folder's VERSION file says which release it is; without one it is a development copy, never updated from here.

- check(): once a day (and when the user asks, the account menu's Check for updates) one anonymous request to GitHub's
  releases API for the code's own repository (its git remote). Nothing about the user is sent; the answer is kept in
  jobs/updates.json, never in the database (a write there reloads every tab). Settings `update_check` = off stops the daily
  check; the button still works.
- update(): only on the user's click (`assist.cli update`, started detached by the app): stops when the code folder has
  edits of its own, was downloaded without git, or a refresh is running; backs up the database; fetches the tags and switches
  the code to the release's tag; reinstalls the Python packages when requirements.txt changed; brings the database up to date
  with the new code; refreshes the user's copies of the templates and skills they never edited (and lists the ones they did);
  then restarts the server. Data is never touched: it lives in the data folder and Application Support, outside the code.
Never automatic: SleePO reads mail and files, so new code arrives only when the user says so.
"""
import json
import re
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

from . import db

STATE = db.db_path().parent / "jobs" / "updates.json"   # the last check and the last update (tests point it elsewhere)
LOCK = "sleepo-update"
EVERY = 86400   # the automatic check: once a day
API = "https://api.github.com/repos/{repo}/releases/latest"
AGENT = "SleePO-update-check"   # a generic client name: no user, address or machine in the request
KEEP_BACKUPS = 3
RX = re.compile(r"^v?(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.(\d+))?$")
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
TEMPLATES = (("templates/data/", ""), (".claude/skills/", ".claude/skills/"))   # code path -> place in the data folder
MCP_RELAY = ("scripts/sleepo_mcp.py", Path.home() / ".assist" / "sleepo_mcp.py")   # install.sh copies it there once
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false", "SSH_ASKPASS": "/usr/bin/false"}


class Stop(Exception):
    """Why an update cannot go ahead, in words for the user."""


# ---------------------------------------------------------------- versions
def parse(v):
    """'2026.11.26' or 'v2026.11.26.1' -> (2026, 11, 26, 1); anything else -> None."""
    m = RX.match((v or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def newer(a, b):
    """True when version a is a later release than b (b None: any release is later than a development copy)."""
    pa, pb = parse(a), parse(b)
    return bool(pa) and (pb is None or pa > pb)


def version_for(day=None, taken=()):
    """Today's release name: 2026.11.26, or 2026.11.26.1, .2 … when that day already has one."""
    d = day or date.today()
    base = f"{d.year}.{d.month:02d}.{d.day:02d}"
    have = {t.lstrip("v") for t in taken}
    if base not in have:
        return base
    n = 1
    while f"{base}.{n}" in have:
        n += 1
    return f"{base}.{n}"


def current(app=None):
    """This code's release (the VERSION file the export writes), or None for a development copy."""
    f = Path(app or db.APP) / "VERSION"
    try:
        v = f.read_text().strip()
    except OSError:
        return None
    return v if parse(v) else None


def _day(v):
    p = parse(v)
    return date(p[0], p[1], p[2]) if p else None


def notes_since(changelog, since=None):
    """The changelog's entries ("## 25 Nov 2026" sections) dated after release `since` (all of them when None), as markdown."""
    parts = re.split(r"(?m)^## ", changelog or "")
    after = _day(since) if since else None
    keep = []
    for part in parts[1:]:
        head = part.split("\n", 1)[0].strip()
        m = re.match(r"(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})", head)
        if not m or m.group(2).lower() not in MONTHS:
            continue
        d = date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        if after is None or d > after:
            keep.append("## " + part.rstrip() + "\n")
    return "\n".join(keep).strip()


# ---------------------------------------------------------------- git
def _git(app, *args, check=True, binary=False, timeout=120):
    import os
    p = subprocess.run(["git", "-C", str(app), *args], capture_output=True, timeout=timeout, env={**os.environ, **GIT_ENV})
    if check and p.returncode:
        err = (p.stderr.decode(errors="ignore").strip().splitlines() or ["git failed"])[-1]
        raise Stop(f"git {args[0]}: {err[:300]}")
    return p.stdout if binary else p.stdout.decode(errors="ignore").strip()


def repo(app=None):
    """'owner/name' of the code's GitHub repository (its git remote), or None."""
    try:
        url = _git(app or db.APP, "config", "--get", "remote.origin.url", check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def blocked(app=None):
    """Why this copy cannot update itself, or "" when it can."""
    app = Path(app or db.APP)
    if not current(app):
        return "This is a development copy, so it isn't updated from GitHub."
    if not (app / ".git").exists():
        return ("This copy was downloaded without git, so it can't update itself. Download it again with git "
                "(the README's Quick start says how); your data stays where it is.")
    if not repo(app):
        return "This copy's code doesn't come from GitHub, so it can't update from there."
    edits = [ln for ln in _git(app, "status", "--porcelain", "--untracked-files=no", check=False).splitlines() if ln.strip()]
    if edits:
        return (f"The code folder has {len(edits)} changed file{'s' if len(edits) != 1 else ''} of its own. "
                "Undo or keep them elsewhere first, so an update doesn't overwrite them.")
    return ""


# ---------------------------------------------------------------- the check
def _state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save(**parts):
    st = _state()
    st.update(parts)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False))
    tmp.replace(STATE)
    return st


def fetch_latest(name, timeout=10):
    """GitHub's latest release of `name` ('owner/repo'): {version, tag, notes, url, published}, or None when none is published."""
    req = urllib.request.Request(API.format(repo=name), headers={"User-Agent": AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    tag = d.get("tag_name") or ""
    return {"version": tag.lstrip("v"), "tag": tag, "notes": (d.get("body") or "")[:20000], "url": d.get("html_url") or "",
            "published": d.get("published_at") or ""}


def check(force=False, app=None, fetch=None):
    """Ask GitHub for the latest release, at most once a day unless forced. Returns what is known (see status)."""
    st = _state()
    last = st.get("checked_ts") or 0
    if not force and time.time() - last < EVERY:
        return st
    name = repo(app)
    if not name:   # a development copy (where releases are made) has nothing to ask; any other copy says why it can't
        err = "" if not current(app) else "This copy's code doesn't come from GitHub."
        return _save(checked=db.now(), checked_ts=time.time(), latest=None, error=err)
    try:
        latest = (fetch or fetch_latest)(name)
    except Exception as e:   # offline, GitHub down, rate limit: say so, keep what was known
        return _save(checked=db.now(), checked_ts=time.time(), error=f"Couldn't reach GitHub ({type(e).__name__}).")
    return _save(checked=db.now(), checked_ts=time.time(), latest=latest, error="")


_BG = threading.Lock()


def check_soon(con=None):
    """From a page load: start the daily check in the background when it is due and switched on. Writes only the job file."""
    if con is not None and (db.get_setting(con, "update_check") or "").lower() == "off":
        return
    if time.time() - (_state().get("checked_ts") or 0) < EVERY or not _BG.acquire(blocking=False):
        return

    def run():
        try:
            check()
        finally:
            _BG.release()
    threading.Thread(target=run, daemon=True).start()


def running():
    from . import jobs
    return jobs.held(LOCK)


def status(con=None, app=None):
    """What the account menu and the Account page show: this version, the latest release, whether to update, and how the
    last update went. Reads only."""
    st = _state()
    mine, latest = current(app), st.get("latest")
    up = dict(st.get("update") or {})
    busy = running()
    starting = time.time() - (up.get("started_ts") or 0) < 30   # just started: its process may not hold the lock yet
    if up.get("running") and not busy and not starting:   # the update's process is gone without finishing (Mac restarted, killed)
        up.update(running=False, ok=False, error=up.get("error") or "The update stopped before it finished.")
    return {"version": mine, "dev": mine is None, "repo": repo(app), "latest": latest,
            "available": bool(latest and newer(latest.get("version"), mine) and mine),
            "checked": st.get("checked"), "error": st.get("error") or "",
            "auto": not (con is not None and (db.get_setting(con, "update_check") or "").lower() == "off"),
            "blocked": blocked(app), "running": busy or bool(up.get("running")), "update": up}


# ---------------------------------------------------------------- the update
def _refresh_running():
    """True while the server runs a refresh (the same probe `assist.cli restart` uses)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{db.PORT}/status", timeout=3) as r:
            return bool(json.loads(r.read()).get("running"))
    except Exception:
        return False


def _backup(label):
    """A copy of the database before the update, in Application Support/Assist/backups (the newest few are kept)."""
    src = db.db_path()
    if not src.exists():
        return None
    folder = src.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"assist-before-{label}-{datetime.now():%Y%m%d-%H%M%S}.db"
    a, b = sqlite3.connect(str(src)), sqlite3.connect(str(dst))
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()
    for old in sorted(folder.glob("assist-before-*.db"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return str(dst)


def _pip(app):
    from . import jobs
    p = subprocess.run([jobs.PY, "-m", "pip", "install", "-q", "-r", str(Path(app) / "requirements.txt")], capture_output=True,
                       text=True, timeout=1800)
    if p.returncode:
        raise Stop("Installing the Python packages failed: " + ((p.stderr or "").strip().splitlines() or ["pip failed"])[-1][:300])


def _migrate(app):
    """Bring the database up to date with the new code (a fresh process, so it runs the new migrations)."""
    from . import jobs
    p = subprocess.run([jobs.PY, "-m", "assist.cli", "migrate"], capture_output=True, text=True, timeout=600, cwd=str(app))   # from the code folder: its code, whatever the path says
    if p.returncode:
        raise Stop("Updating the database failed: " + ((p.stderr or "").strip().splitlines() or ["migrate failed"])[-1][:300])


def _restart():
    from . import jobs
    jobs.spawn_cli("restart", cwd=db.APP)   # the new code's restart: waits for a running refresh or Ask SleePO answer, then restarts


def refresh_templates(app, data, old, new):
    """The user's copies of the templates and skills (install.sh copied them into the data folder once): a copy still the
    same as the old release's is replaced by the new one; one the user changed is kept and listed; a new file is added;
    one the user deleted stays deleted. Returns {updated, added, kept}."""
    app, data = Path(app), Path(data)
    out = {"updated": [], "added": [], "kept": []}
    if data.resolve() == app.resolve():   # code and data together (the original install): nothing was copied
        return out
    files = [ln for ln in _git(app, "ls-tree", "-r", "--name-only", new, "--", *(p for p, _ in TEMPLATES), MCP_RELAY[0]).splitlines() if ln]
    for path in files:
        if path == MCP_RELAY[0]:
            target, shown = MCP_RELAY[1], "~/.assist/sleepo_mcp.py"
        else:
            src, dst = next((s, d) for s, d in TEMPLATES if path.startswith(s))
            rel = dst + path[len(src):]
            target, shown = data / rel, rel
        new_b = _git(app, "show", f"{new}:{path}", binary=True)
        had = bool(old) and subprocess.run(["git", "-C", str(app), "cat-file", "-e", f"{old}:{path}"], capture_output=True).returncode == 0
        old_b = _git(app, "show", f"{old}:{path}", binary=True) if had else b""
        if had and new_b == old_b:
            continue
        if not target.exists():
            if not had:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(new_b)
                out["added"].append(shown)
            continue
        cur = target.read_bytes()
        if cur == new_b:
            continue
        if had and cur == old_b:
            target.write_bytes(new_b)
            out["updated"].append(shown)
        else:
            out["kept"].append(shown)
    return out


def start(tag=None):
    """Update now (the app's button): run `assist.cli update` detached, so a server restart does not stop it."""
    from . import jobs
    if running():
        return {"started": False}
    why = blocked()
    if why:
        return {"started": False, "reason": why}
    _save(update={"running": True, "phase": "Starting", "started": db.now(), "started_ts": time.time(), "from": current()})
    jobs.spawn_cli("update", *(["--to", tag] if tag else []), cwd=db.APP)   # from the code folder, like the restart after it
    return {"started": True}


def update(tag=None, log=print, app=None, data=None, restart=True):
    """Body of `assist.cli update`: switch the code to release `tag` (default: the latest one found). True when done."""
    from . import jobs
    app, data = Path(app or db.APP), Path(data or db.ASSIST)
    with jobs.exclusive(LOCK) as got:
        if not got:
            log("update: another update is running")
            return False
        mine = current(app)
        st = {"running": True, "phase": "Starting", "started": db.now(), "from": mine, "ok": None, "error": ""}

        def phase(p):
            st["phase"] = p
            _save(update=dict(st))
            log(p)

        old = None
        switched = False
        try:
            why = blocked(app)
            if why:
                raise Stop(why)
            if _refresh_running():
                raise Stop("A refresh is running. Update when it ends.")
            phase("Downloading the release")
            _git(app, "fetch", "--tags", "--force", "--quiet", "origin", timeout=600)
            tags = [t for t in _git(app, "tag", "--list", "v*").splitlines() if parse(t)]
            if not tag:
                latest = (_state().get("latest") or {}).get("tag")
                tag = latest if latest in tags else max(tags, key=parse, default=None)
            if not tag or tag not in tags:
                raise Stop(f"Release {tag or ''} isn't on GitHub.".replace("  ", " "))
            target = tag.lstrip("v")
            st["to"] = target
            if not newer(target, mine):
                raise Stop(f"This is already {mine}, the same as or newer than {target}.")
            old = _git(app, "rev-parse", "HEAD")
            new = _git(app, "rev-parse", f"{tag}^{{commit}}")
            phase("Backing up your database")
            st["backup"] = _backup(mine)
            phase(f"Installing {target}")
            _git(app, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", tag)
            switched = True
            if _git(app, "diff", "--name-only", old, new, "--", "requirements.txt"):
                phase("Installing Python packages")
                _pip(app)
            phase("Updating the database")
            _migrate(app)
            st["templates"] = refresh_templates(app, data, old, new)
            st.update(ok=True, version=target)
        except Stop as e:
            st.update(ok=False, error=str(e))
        except Exception as e:   # an unexpected failure: say what it was, never leave half an update
            st.update(ok=False, error=f"{type(e).__name__}: {e}"[:400])
        if not st["ok"] and switched and old:
            try:
                _git(app, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", old)
                st["error"] += " The code was put back as it was."
            except Stop as e:
                st["error"] += f" Putting the code back failed too ({e}); run `git checkout {old[:12]}` in {app}."
        st.update(running=False, finished=db.now(), phase="Restarting" if st["ok"] and restart else ("Done" if st["ok"] else "Stopped"))
        _save(update=dict(st))
        log(f"update: {'now ' + st.get('version', '') if st['ok'] else st['error']}")
        if st["ok"] and restart:
            _restart()
        return bool(st["ok"])


def describe(st):
    """One line for the terminal."""
    v = st["version"] or "development copy"
    if st.get("available"):
        return f"SleePO {v}; {st['latest']['version']} is available ({st['latest'].get('url')})"
    if st.get("latest"):
        return f"SleePO {v}; latest release {st['latest']['version']}" + ("" if st["dev"] else " (up to date)")
    return f"SleePO {v}; " + (st.get("error") or "no release published yet")
