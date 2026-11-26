"""What every group of routes shares (22 Oct 2026, from the codebase review: api.py had grown to 3,000 lines and 150
routes). The app itself, its middleware and the refresh live in api.py; route groups live in assist/routes/<group>.py, each
an APIRouter that api.py includes."""
import os
import re
import threading
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from . import db, views

ASSIST = db.ASSIST
ROOT = ASSIST.parent
PY = os.path.expanduser("~/.assist/venv/bin/python")
_MIGRATED = set()
def _web_dist():
    """The built front end: env ASSIST_WEB_DIST, else web/dist in the code folder (an install), else the assist-web checkout."""
    for p in (os.environ.get("ASSIST_WEB_DIST"), str(db.APP / "web" / "dist")):
        if p and (Path(p).expanduser() / "index.html").exists():
            return Path(p).expanduser()
    return Path.home() / "Developer" / "assist-web" / "dist"


WEB_DIST = _web_dist()


def granola_dir():
    """Where meeting notes and transcripts are kept: "Granola Export" next to the data folder (created when missing)."""
    d = ROOT / "Granola Export"
    d.mkdir(parents=True, exist_ok=True)
    return d


def granola_script():
    """The Granola sync: the copy in the Granola Export folder when there is one (Sam's), else the app's own."""
    own = granola_dir() / "granola_update.py"
    return str(own if own.exists() else db.APP / "scripts" / "granola_update.py")
_CACHE = {"key": None, "data": None}
_BUILD = threading.Lock()


def con():
    """A connection to the database, migrated once per process (the server restarts when the code changes)."""
    c = db.connect()
    key = str(db.db_path())
    if key not in _MIGRATED:
        db.migrate(c)
        _MIGRATED.add(key)
    return c


def db_con():
    """Dependency: a connection for the request, closed after it."""
    c = con()
    try:
        yield c
    finally:
        c.close()


def json_only(request: Request):
    """Dependency for routes that read a JSON body themselves (await request.json()): anything else is refused, so a
    form post from another page cannot reach them."""
    if not (request.headers.get("content-type") or "").startswith("application/json"):
        raise HTTPException(415, "JSON body required")


def _nocache(obj):
    return JSONResponse(obj, headers={"Cache-Control": "no-store"})


def _mid(mid):
    """A meeting id from the path (m-12, 12) as an int; 404 otherwise."""
    m = re.match(r"^m?-?(\d+)$", str(mid))
    if not m:
        raise HTTPException(404)
    return int(m.group(1))


def snapshot():
    """The full view model, rebuilt only when the database changes. One rebuild at a time (23 Oct 2026): after a refresh
    writes, every page request used to rebuild it at once (4-11 s each, all fighting for the GIL), and even the cheapest
    requests waited 40 s; now one request rebuilds and the others wait for it. They wait only for the first build (6 Nov
    2026): while a job writes, the database changes faster than a rebuild, so every request queued behind one and the app
    froze; now they get the last view model, and the next change brings the new one."""
    key = _versions()[0]
    if _CACHE["key"] != key:
        if not _BUILD.acquire(blocking=_CACHE["data"] is None):
            return _CACHE["data"]
        try:
            key = _versions()[0]
            if _CACHE["key"] != key:   # another request may have built it while this one waited
                c = con()
                try:
                    _CACHE["data"] = views.bootstrap(c)
                    _CACHE["key"] = key
                finally:
                    c.close()
        finally:
            _BUILD.release()
    return _CACHE["data"]


def _versions():
    """Fingerprints the page watches: data (database + WAL mtimes) and code (the built app's index.html).
    While `pnpm build` has emptied dist/ the code version is None, so open tabs are not told to reload into the gap."""
    p = db.db_path()
    data = sum(f.stat().st_mtime_ns for f in [p, Path(str(p) + "-wal")] if f.exists())
    built = WEB_DIST / "index.html"
    try:
        code = built.stat().st_mtime_ns
    except FileNotFoundError:
        code = None
    return data, code
