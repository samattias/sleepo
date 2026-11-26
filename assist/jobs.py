"""Shared plumbing for background work (22 Oct 2026, from the codebase review): one place for the locks that keep two
runs of the same thing apart, and (as the other modules move onto it) for detached CLI runs and job files.

exclusive(name): an advisory lock on a file under jobs/locks/, held for the duration of a `with` block by whichever
process takes it first; a second taker gets False at once instead of waiting. The lock is the process's open file, so it
is released when the process ends, crashes or is killed: no stale lock files, no pid reuse, and CLI runs, refresh steps
and the server all see the same lock.
"""
import fcntl
import os
import re
import subprocess
from contextlib import contextmanager

from . import db

LOCK_DIR = db.db_path().parent / "jobs" / "locks"
PY = os.path.expanduser("~/.assist/venv/bin/python")


@contextmanager
def exclusive(name):
    """`with exclusive("prep-AAMk…") as got:` got is True when this process holds the lock, False when another does."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCK_DIR / (re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:120] + ".lock")
    f = open(path, "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        f.close()


def held(name):
    """True when another process holds `name` right now (a quick probe; takes and drops the lock if free)."""
    with exclusive(name) as got:
        return not got


def spawn_cli(*args, cwd=None):
    """Start `python -m assist.cli <args>` detached from the caller (survives a server restart). Returns the Popen."""
    return subprocess.Popen([PY, "-m", "assist.cli", *map(str, args)], cwd=str(cwd or db.ASSIST), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)


# ------------------------------------------------------------------------------------------------ job files
def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


class JobStore:
    """Background jobs of one kind as JSON files under jobs/<kind>/ (outside OneDrive, private to this Mac), so a server
    reload loses nothing. One file per job ({jid}.json: the state the app polls), an optional {jid}.prompt the run reads and
    deletes, written atomically with mode 600. Files go after `keep` seconds (keep_for(name) can keep some longer). A job
    still marked running is reported as stopped when its process is gone (its pid is recorded at start), or, for older
    jobs without a pid, after `stale_after` seconds."""

    def __init__(self, kind, stale_after, stale_msg, keep=86400, keep_for=None, dir_of=None):
        # dir_of: read the folder from the owning module's JOB_DIR each time (tests point it at a temporary folder)
        self._dir = db.db_path().parent / "jobs" / kind
        self.dir_of = dir_of
        self.stale_after, self.stale_msg, self.keep, self.keep_for = stale_after, stale_msg, keep, keep_for

    @property
    def dir(self):
        return self.dir_of() if self.dir_of else self._dir

    def path(self, jid):
        if not re.fullmatch(r"[0-9a-f]{12}", jid or ""):
            raise ValueError("bad job id")
        return self.dir / f"{jid}.json"

    def prompt_path(self, jid):
        return self.dir / f"{jid}.prompt"

    def write_file(self, path, data):
        import json
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def write(self, jid, data):
        self.write_file(self.path(jid), data)

    def prune(self):
        import time
        if not self.dir.exists():
            return
        for f in self.dir.iterdir():
            try:
                age = time.time() - f.stat().st_mtime
                if age > (self.keep_for(f.name) if self.keep_for else self.keep):
                    f.unlink(missing_ok=True)
            except FileNotFoundError:   # a job finishing right now removed its .prompt or renamed its .tmp after the listing
                pass

    def get(self, jid):
        """The job's state, or None when unknown or gone. Also clears old job files."""
        import json
        import time
        try:
            p = self.path(jid)
        except ValueError:
            return None
        self.prune()
        if not p.exists():
            return None
        j = json.loads(p.read_text())
        if j.get("running"):
            dead = (not _alive(j["pid"])) if j.get("pid") else time.time() - j.get("started_ts", time.time()) > self.stale_after
            if dead:
                j.update(running=False, ok=False, error=j.get("error") or self.stale_msg)
        return j

    def start(self, state, cli, prompt=None, cwd=None):
        """New job: write its state (running, started_ts) and prompt file, then run `assist.cli <cli…> <jid>` detached and
        record its pid. Returns the job id."""
        import time
        import uuid
        jid = uuid.uuid4().hex[:12]
        state = {"running": True, "ok": None, "error": "", **state, "started_ts": time.time()}
        self.write(jid, state)
        if prompt is not None:
            pf = self.prompt_path(jid)
            pf.write_text(prompt)
            os.chmod(pf, 0o600)
        p = spawn_cli(*cli, jid, cwd=cwd)
        cur = self.get(jid) or state
        if cur.get("running"):   # the run may already have finished and written its result
            self.write(jid, {**cur, "pid": p.pid})
        return jid
