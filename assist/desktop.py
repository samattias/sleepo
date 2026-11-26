"""Doing things on the user's Mac from Ask SleePO, every step allowed first (Sam, 23 Nov 2026: "I want the assistant to be
able to do tasks like this on my desktop ... so it asked me for approval to take action, but I want to be able to do all
this stuff". The chat had gathered a data room's decks in its own folder, then asked him to drag them into Downloads himself
and to fetch three demo files from SharePoint by hand).

The chat (assist/chat.py) runs `assist.cli ask-do PLAN`. This module checks every step in code, files the plan as a request
under jobs/desktop/ and waits. The app shows the steps as a card in the answer (components/ChatDesktop.tsx). Nothing happens
until the user allows them (all, or the ones left ticked) or declines. Then this same process carries out exactly the steps
allowed, records each outcome on the request and prints them, so the chat knows what was done and carries on.

Steps (the card says each in plain words; paths are resolved and checked here, never taken on trust from the model):
- folder: make a folder (and its parents).
- copy: files or folders into a folder. A name already there gets " 2", " 3", as Finder does: nothing is overwritten.
- move: into a folder. Never out of OneDrive or a synced SharePoint library: that breaks the file's links for everyone it is
  shared with (copy instead).
- rename: in place; not in OneDrive, for the same reason.
- trash: into the Trash, where it can be taken back out; not in OneDrive, where deleting deletes it for everyone.
- download: a file from the company's SharePoint or OneDrive, by its link. SleePO holds no Microsoft token that can read files
  (the tenant wants admin approval for one: outlook-login, 22 Oct 2026), so the browser downloads it with the user's own
  sign-in: the link is turned into SharePoint's download address and opened. SleePO waits for the file in Downloads and moves
  it where the plan says. Only links on the company's own SharePoint hosts (the org pack's microsoft.hosts, else the hosts of
  the files SleePO's SharePoint index holds).
- open: a file or folder in its app, or an https link in the browser. Never an app, script, installer or shortcut file.
- show: a file or folder in Finder.

Where: only inside the home folder. Never in Library (except Library/CloudStorage, where OneDrive lives), never a hidden file
or folder (~/.ssh, ~/.assist …), never SleePO's own code or data, never the HR investigation folder (chat_tools.EXCLUDED).
A copy or move into OneDrive is allowed, with a warning on the card: it uploads to SharePoint.

The gate: the request file is written by the process that asks; the answer only by the server, when the user presses a
button in the app (POST /api/chat/desktop/<id>/decide), as a second file created once (O_EXCL), so the answer, the request
expiring (WAIT) and a stopped turn cannot overwrite each other. The chat cannot write either file: Write and Edit reach only
its workspace folder, and no step may write under Library. Reading a request (the card's GET) never writes.
Tests: tests/test_desktop.py.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import db

HOME = Path.home()
JOB_DIR = None             # tests point this at a temporary folder; the real one is next to the database (job_dir())
WAIT = 600                 # seconds a request waits for the user's answer
DL_START = 120             # seconds for a download to show up in Downloads
DL_MAX = 900               # seconds for it to finish
POLL = 0.5
BEAT = 5                   # the waiting process rewrites its request this often, so the app can tell it is still there
STALE = 45                 # a pending request not rewritten for this long has lost its process
STALE_RUNNING = 600        # a running one (a large copy writes nothing until it ends)
MAX_STEPS = 20
MAX_FILES = 50
OPS = ("folder", "copy", "move", "rename", "trash", "download", "open", "show")
ALIAS = {"mkdir": "folder", "make_folder": "folder", "reveal": "show", "delete": "trash", "cp": "copy", "mv": "move"}
PARTIAL = (".crdownload", ".download", ".part", ".partial", ".opdownload")   # Chrome/Edge, Safari, Firefox, Opera
NO_OPEN = {"app", "command", "sh", "zsh", "bash", "csh", "tool", "pkg", "mpkg", "dmg", "iso", "scpt", "scptd", "applescript",
           "workflow", "terminal", "py", "rb", "pl", "php", "js", "jar", "exe", "bat", "cmd", "msi", "action", "prefpane", "kext",
           "plugin", "webloc", "inetloc", "fileloc", "url", "shortcut", "osax", "service", "saver", "mobileconfig", "dylib", "so",
           "bin", "run", "appex", "xpc", "bundle", "framework", "qlgenerator", "mdimporter"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def job_dir():
    return Path(JOB_DIR) if JOB_DIR else db.db_path().parent / "jobs" / "desktop"


# ---------------------------------------------------------------- where a step may reach

def _home():
    return HOME.resolve()


def _rel(p):
    try:
        return Path(p).relative_to(_home())
    except ValueError:
        return None


def onedrive(p):
    """True for a path in OneDrive or a synced SharePoint library (~/Library/CloudStorage)."""
    r = _rel(p)
    return bool(r and r.parts[:2] == ("Library", "CloudStorage"))


def _protected():
    out = []
    for p in (db.APP, db.ASSIST, db.db_path().parent):
        try:
            out.append(Path(p).resolve())
        except OSError:
            pass
    return out


def check(path, must_exist=True):
    """The resolved path, or ValueError saying in plain words why SleePO will not touch it."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("a path is missing")
    raw = os.path.expanduser(path.strip())
    if not os.path.isabs(raw):
        raise ValueError(f"“{path}” is not a full path (start it with ~/ or /Users/…)")
    try:
        p = Path(raw).resolve()   # not strict: a folder an earlier step makes need not exist yet
    except (OSError, RuntimeError):
        raise ValueError(f"{path} cannot be read")
    r = _rel(p)
    if r is None:
        raise ValueError(f"{path} is outside your home folder")
    if not r.parts:
        raise ValueError("that is your home folder itself")
    if any(part.startswith(".") for part in r.parts):
        raise ValueError(f"{path} is a hidden file or folder")
    if r.parts[0] == "Library" and r.parts[1:2] != ("CloudStorage",):
        raise ValueError(f"{path} is in Library, which holds apps' and macOS's own files")
    for q in _protected():
        if p == q or q in p.parents:
            raise ValueError(f"{path} is SleePO's own code or data")
    from .chat_tools import EXCLUDED
    if EXCLUDED.search(str(p)):
        raise ValueError(f"{path} is in a folder SleePO never touches")
    if must_exist and not (p.exists() or p.is_symlink()):
        raise ValueError(f"{path} does not exist")
    return p


def where(p, ws=None):
    """A path in plain words: "Downloads › Data room", "OneDrive › Documents › Board", "this conversation's folder"."""
    p = Path(p)
    if ws:
        ws = Path(ws)
        if p == ws or ws in p.parents:
            return " › ".join(("this conversation's folder",) + p.relative_to(ws).parts)
    r = _rel(p)
    if r is None:
        return str(p)
    parts = list(r.parts)
    if parts[:2] == ["Library", "CloudStorage"] and len(parts) > 2:
        lib = parts[2]
        name = "SharePoint (synced)" if "SharedLibraries" in lib else "OneDrive" if lib.startswith("OneDrive") else lib.split("-")[0]
        parts = [name] + parts[3:]
    return " › ".join(parts) or "your home folder"


def _size(p, cap=20000):
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    total = 0
    for i, f in enumerate(p.rglob("*")):
        if i > cap:
            break
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _mb(n):
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


# ---------------------------------------------------------------- SharePoint and OneDrive links

def tenant_hosts():
    """The company's SharePoint hosts: the org pack's microsoft.hosts, else those of the files SleePO's SharePoint index holds."""
    from . import org
    try:
        hosts = {str(h).lower() for h in (org.section("microsoft", {}) or {}).get("hosts") or []}
    except Exception:
        hosts = set()
    if hosts:
        return hosts
    try:
        con = sqlite3.connect(f"file:{db.db_path()}?mode=ro", uri=True)
        try:
            for (u,) in con.execute("SELECT DISTINCT url FROM items WHERE source_id='sharepoint' AND url LIKE 'https://%sharepoint.com/%'"):
                h = urlparse(u).netloc.lower()
                if h.endswith(".sharepoint.com"):
                    hosts.add(h)
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return hosts


def link_name(url):
    """The file's name as the link shows it ("" for a sharing link, which hides it)."""
    p = urlparse(url)
    path = unquote(p.path)
    if re.match(r"^/:\w:/", path):
        return ""
    q = parse_qs(p.query)
    if path.lower().endswith(".aspx"):
        name = (q.get("file") or [""])[0] or (q.get("id") or [""])[0].rstrip("/").rsplit("/", 1)[-1]
    else:
        name = path.rstrip("/").rsplit("/", 1)[-1]
    return name if "." in name else ""


def download_url(url, hosts):
    """The address that makes SharePoint send the file itself, or ValueError. Sharing links (/:x:/…, /:v:/…) take download=1;
    a file's own address and a stream.aspx or onedrive.aspx link go through the site's _layouts/15/download.aspx (SourceUrl);
    an Office page (Doc.aspx?sourcedoc={guid}) through download.aspx?UniqueId."""
    p = urlparse((url or "").strip())
    if p.scheme != "https" or not p.netloc:
        raise ValueError("a download needs the file's https link")
    host = p.netloc.lower()
    if host not in hosts:
        raise ValueError(f"{host} is not the company's SharePoint or OneDrive (SleePO only downloads from {', '.join(sorted(hosts)) or 'there'})")
    path, q = unquote(p.path), parse_qs(p.query)
    m = re.match(r"^/:(\w):/", path)
    if m:
        if m.group(1).lower() == "f":
            raise ValueError("that link is to a folder, not a file: open it instead, or find the file's own link (ask-sharepoint)")
        keep = [kv for kv in p.query.split("&") if kv and not kv.lower().startswith(("download=", "web="))]
        return p._replace(query="&".join(keep + ["download=1"]), fragment="").geturl()
    site = re.match(r"^/(?:sites|teams|personal)/[^/]+", path)
    base = f"https://{host}{site.group(0) if site else ''}/_layouts/15/download.aspx"
    if path.lower().endswith(".aspx"):
        doc = (q.get("sourcedoc") or [""])[0].strip("{}")
        if re.fullmatch(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}", doc):
            return f"{base}?UniqueId={doc}"
        sid = (q.get("id") or [""])[0]
        if sid.startswith("/") and "." in sid.rstrip("/").rsplit("/", 1)[-1]:
            return f"{base}?SourceUrl={quote(sid, safe='/')}"
        raise ValueError("that link opens a SharePoint page, not a file")
    if "." not in path.rstrip("/").rsplit("/", 1)[-1]:
        raise ValueError("that link is to a folder, not a file")
    return f"{base}?SourceUrl={quote(path, safe='/')}"


# ---------------------------------------------------------------- checking a plan

def _list(v):
    if isinstance(v, str):
        return [v]
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _step(s, ws, made, hosts):
    if not isinstance(s, dict):
        raise ValueError("each step is an object like {\"do\": \"copy\", \"from\": [...], \"to\": \"...\"}")
    op = str(s.get("do") or s.get("op") or "").strip().lower()
    op = ALIAS.get(op, op)
    if op not in OPS:
        raise ValueError(f"“{op or '?'}” is not a step SleePO can do ({', '.join(OPS)})")

    def folder(path):   # where something goes: an existing folder, or one an earlier step makes
        p = check(path, must_exist=False)
        if p.exists() and not p.is_dir():
            raise ValueError(f"{path} is a file, not a folder")
        if not p.exists() and p not in made:
            raise ValueError(f"the folder {path} does not exist (put a folder step before this one)")
        return p

    def sources(v):
        lst = _list(v)
        if not lst:
            raise ValueError("say which files (\"from\": [paths])")
        if len(lst) > MAX_FILES:
            raise ValueError(f"at most {MAX_FILES} files in one step")
        return [check(x) for x in lst]

    st = {"do": op, "state": "waiting", "detail": [], "warn": ""}
    if op == "folder":
        p = check(s.get("path") or s.get("to"), must_exist=False)
        if p.exists() and not p.is_dir():
            raise ValueError(f"{p} exists and is a file")
        q = p
        while not q.exists() and q != _home():
            made.add(q)
            q = q.parent
        st.update(path=str(p), label=f"Make the folder “{p.name}” in {where(p.parent, ws)}" if not p.exists() else f"Use the folder “{p.name}” (already there)")
        if onedrive(p):
            st["warn"] = "It is in OneDrive: it syncs to SharePoint."
    elif op in ("copy", "move"):
        src = sources(s.get("from") or s.get("paths") or s.get("path"))
        dest = folder(s.get("to"))
        for p in src:
            if op == "move" and onedrive(p):
                raise ValueError(f"{p.name} is in OneDrive: moving it out breaks its links for everyone it is shared with. Copy it instead")
            if p == dest or p in dest.parents:
                raise ValueError(f"{p.name} cannot go into itself")
        n = len(src)
        what = f"“{src[0].name}”" if n == 1 else f"{n} {'items' if any(p.is_dir() for p in src) else 'files'}"
        size = sum(_size(p) for p in src)
        st.update(paths=[str(p) for p in src], to=str(dest), size=size,
                  label=f"{'Copy' if op == 'copy' else 'Move'} {what} into {where(dest, ws)}",
                  detail=[f"{p.name}{'/' if p.is_dir() else ''} · from {where(p.parent, ws)}" for p in src])
        warns = []
        if onedrive(dest):
            warns.append(f"Into OneDrive: the {'copies upload' if op == 'copy' else 'files upload'} to SharePoint.")
        if size > 2e9:
            warns.append(f"{_mb(size)} in all.")
        st["warn"] = " ".join(warns)
    elif op == "rename":
        p = check(s.get("path") or s.get("from"))
        name = str(s.get("name") or s.get("to") or "").strip()
        if "/" in name:
            name = name.rstrip("/").rsplit("/", 1)[-1]
        if not name or name.startswith(".") or ":" in name or len(name) > 255:
            raise ValueError("the new name is missing or not allowed")
        if onedrive(p):
            raise ValueError(f"{p.name} is in OneDrive: renaming it there renames it for everyone and breaks links to it")
        if (p.parent / name).exists():
            raise ValueError(f"there is already a “{name}” in {where(p.parent, ws)}")
        st.update(path=str(p), name=name, label=f"Rename “{p.name}” to “{name}”", detail=[f"in {where(p.parent, ws)}"])
    elif op == "trash":
        src = sources(s.get("path") or s.get("paths") or s.get("from"))
        for p in src:
            if onedrive(p):
                raise ValueError(f"{p.name} is in OneDrive: deleting it there deletes it for everyone")
        what = f"“{src[0].name}”" if len(src) == 1 else f"{len(src)} items"
        st.update(paths=[str(p) for p in src], label=f"Put {what} in the Trash",
                  detail=[f"{p.name}{'/' if p.is_dir() else ''} · from {where(p.parent, ws)}" for p in src])
    elif op == "download":
        url = str(s.get("url") or "").strip()
        dl = download_url(url, hosts)
        dest = folder(s.get("to") or str(HOME / "Downloads"))
        name = str(s.get("name") or "").strip().rsplit("/", 1)[-1] or link_name(url)
        if name.startswith("."):
            name = ""
        host = urlparse(url).netloc.lower()
        st.update(url=url, dl=dl, to=str(dest), name=name,
                  label=f"Download {('“' + name + '”') if name else 'the file'} from {'OneDrive' if '-my.' in host else 'SharePoint'} into {where(dest, ws)}",
                  detail=["Your browser downloads it with your sign-in; SleePO then moves it into place.", url])
        if onedrive(dest):
            st["warn"] = "Into OneDrive: it uploads to SharePoint."
    elif op in ("open", "show"):
        target = str(s.get("path") or s.get("url") or "").strip()
        if op == "open" and re.match(r"^[a-z]+://", target, re.I):
            u = urlparse(target)
            if u.scheme != "https" or not u.netloc:
                raise ValueError("only https links open in the browser")
            st.update(url=target, label=f"Open {u.netloc} in your browser", detail=[target])
            if u.netloc.lower() not in hosts:
                st["warn"] = f"A link outside the company's Microsoft 365: {u.netloc}."
        else:
            p = check(target)
            ext = p.suffix.lower().lstrip(".")
            if op == "open" and (ext in NO_OPEN or (p.is_file() and os.access(p, os.X_OK) and not ext)):
                raise ValueError(f"{p.name} is an app, script or installer: SleePO never opens those")
            verb = "Show" if op == "show" else "Open"
            st.update(path=str(p), label=f"{verb} “{p.name}”{' in Finder' if op == 'show' else ''}", detail=[f"in {where(p.parent, ws)}"])
    return st


def prepare(plan, ws=None, hosts=None):
    """(steps, errors): the plan checked and put in plain words; errors name each step that cannot be done as written."""
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except ValueError as e:
            return [], [f"The plan is not valid JSON ({e})"]
    if isinstance(plan, list):
        plan = {"steps": plan}
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if not isinstance(steps, list) or not steps:
        return [], ['The plan has no steps: {"why": "…", "steps": [{"do": "copy", "from": ["…"], "to": "…"}]}']
    if len(steps) > MAX_STEPS:
        return [], [f"At most {MAX_STEPS} steps in one plan"]
    hosts = tenant_hosts() if hosts is None else hosts
    made, out, errors = set(), [], []
    for i, s in enumerate(steps, 1):
        try:
            out.append(_step(s, ws, made, hosts))
        except ValueError as e:
            errors.append(f"Step {i}: {e}.")
    return out, errors


# ---------------------------------------------------------------- the request files

def _path(rid, ext=".json"):
    if not re.fullmatch(r"d[0-9a-f]{12}", rid or ""):
        raise ValueError("no such request")
    return job_dir() / f"{rid}{ext}"


def _write(req):
    job_dir().mkdir(parents=True, exist_ok=True)
    p = _path(req["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(req, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def _read(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def _answer(rid, ans):
    """Record the answer once: True when this call recorded it, False when there already was one."""
    job_dir().mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(_path(rid, ".decision.json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as f:
        json.dump(dict(ans, at=_now()), f)
    return True


def get(rid):
    """One request as the card shows it: its steps and their outcomes, the answer, and whether its process is gone."""
    try:
        req = _read(_path(rid))
    except ValueError:
        return None
    if not req:
        return None
    ans = _read(_path(rid, ".decision.json"))
    req["answer"] = ans
    limit = STALE_RUNNING if req.get("status") == "running" else STALE
    if req.get("status") in ("pending", "running") and time.time() - float(req.get("beat") or 0) > limit:
        req["status"] = "stopped" if req.get("status") == "running" or ans else "expired"
        req["lost"] = True
    return req


def for_thread(tid):
    """A conversation's requests, oldest first. Reads only."""
    d = job_dir()
    if not tid or not d.exists():
        return []
    out = []
    for f in d.glob("d*.json"):
        if f.name.endswith(".decision.json"):
            continue
        r = _read(f)
        if r and r.get("thread") == tid:
            out.append(get(r["id"]))
    return sorted([r for r in out if r], key=lambda r: r.get("created_at") or "")


def ids_for_run(run):
    d = job_dir()
    if not run or not d.exists():
        return []
    out = []
    for f in d.glob("d*.json"):
        if not f.name.endswith(".decision.json"):
            r = _read(f)
            if r and r.get("run") == run:
                out.append((r.get("created_at") or "", r["id"]))
    return [i for _, i in sorted(out)]


def decide(rid, approve, steps=None):
    """The user's answer from the app. Only for a request still waiting; steps: the indexes left ticked (all when None)."""
    req = get(rid)
    if not req:
        raise LookupError("no such request")
    if req.get("status") != "pending" or req.get("answer"):
        raise ValueError("this request is no longer waiting for an answer")
    n = len(req.get("steps") or [])
    chosen = list(range(n)) if steps is None else sorted({int(i) for i in steps if 0 <= int(i) < n})
    if approve and not chosen:
        raise ValueError("tick at least one step, or decline")
    if not _answer(rid, {"approve": bool(approve), "steps": chosen if approve else [], "by": "you"}):
        raise ValueError("this request has already been answered")
    return get(rid)


def stop_run(run):
    """A stopped chat turn stops its requests: one still waiting is answered 'stopped'; one running stops after its current step."""
    for rid in ids_for_run(run):
        if not _answer(rid, {"approve": False, "steps": [], "by": "stopped"}):
            try:
                _path(rid, ".stop").touch()
            except OSError:
                pass


def show(rid, step, n=0):
    """Show a step's result in Finder (the card's button; it changes nothing)."""
    req = get(rid)
    if not req:
        raise LookupError("no such request")
    try:
        st = req["steps"][int(step)]
        target = (st.get("out") or [])[int(n)]
    except (IndexError, ValueError, TypeError):
        raise LookupError("nothing to show")
    p = check(target)
    subprocess.run(["/usr/bin/open", "-R", str(p)], check=False, timeout=15)
    return {"ok": True}


def purge():
    """Requests older than the retention period go (called when a new request is made, never from a read)."""
    from .retention import RETENTION_DAYS
    d = job_dir()
    if not d.exists():
        return
    cut = time.time() - RETENTION_DAYS * 86400
    for f in d.iterdir():
        try:
            if f.stat().st_mtime < cut:
                f.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- carrying out a step

class Stopped(Exception):
    pass


def unique(folder, name):
    """folder/name, or "name 2.ext", "name 3.ext" when that is taken (Finder's way): nothing is overwritten."""
    folder = Path(folder)
    stem, suf = name, ""
    m = re.match(r"^(.+?)(\.[A-Za-z0-9]{1,8})$", name)
    if m:
        stem, suf = m.group(1), m.group(2)
    cand, n = folder / name, 2
    while cand.exists() or cand.is_symlink():
        cand, n = folder / f"{stem} {n}{suf}", n + 1
    return cand


def _opener(target):
    subprocess.run(["/usr/bin/open", target], check=False, timeout=30)


OPENER = _opener   # tests replace it


def _trash(p):
    """Into the Trash: Finder's own delete (Put Back works), else a move into ~/.Trash."""
    if HOME.resolve() == Path.home().resolve():   # (tests point HOME elsewhere: no Finder there)
        try:
            r = subprocess.run(["/usr/bin/osascript", "-e", f'tell application "Finder" to delete (POSIX file {json.dumps(str(p), ensure_ascii=False)})'],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    tr = HOME / ".Trash"
    tr.mkdir(exist_ok=True)
    shutil.move(str(p), str(unique(tr, p.name)))


def _base(n):
    """A downloaded name without the browser's " (1)" and partial endings, for matching."""
    for e in PARTIAL:
        if n.lower().endswith(e):
            n = n[: -len(e)]
    return re.sub(r" \(\d+\)(?=\.[^.]+$|$)", "", n).lower()


def _download(st, tick, ws):
    dl = HOME / "Downloads"
    dl.mkdir(exist_ok=True)
    before = set(os.listdir(dl))
    t0 = time.time()
    OPENER(st["dl"])
    want = (st.get("name") or "").lower()
    last, steady = None, 0
    while True:
        tick()
        new = [n for n in os.listdir(dl) if n not in before and not n.startswith(".")]
        partial = [n for n in new if n.lower().endswith(PARTIAL) or n.startswith("Unconfirmed ")]
        done = [n for n in new if n not in partial and (dl / n).is_file()]
        if want:
            done = [n for n in done if _base(n) == want] or ([] if any(_base(n) == want for n in partial) else done)
        pick = max(done, key=lambda n: (dl / n).stat().st_mtime) if done else None
        if pick:
            size = (dl / pick).stat().st_size
            busy = any(_base(n) == _base(pick) for n in partial)
            steady = steady + 1 if (pick, size) == last and size > 0 and not busy else 0
            last = (pick, size)
            if steady >= 2:
                break
        elapsed = time.time() - t0
        if not new and elapsed > DL_START:
            raise ValueError(f"nothing arrived in Downloads within {DL_START // 60} minutes. The link is open in your browser: if it "
                             "asked you to sign in, or shows the file instead of downloading it, download it there and ask me to move it")
        if elapsed > DL_MAX:
            raise ValueError(f"the download had not finished after {DL_MAX // 60} minutes; it may still be going in your browser")
        got = sum((dl / n).stat().st_size for n in partial if (dl / n).is_file())
        st["progress"] = f"{_mb(got)} so far" if got else "waiting for your browser"
        time.sleep(1 if POLL >= 0.5 else POLL)
    found = dl / pick
    dest = Path(st["to"])
    name = st.get("name") if st.get("name") and Path(st["name"]).suffix.lower() == found.suffix.lower() else re.sub(r" \(\d+\)(?=\.[^.]+$)", "", found.name)
    if dest.resolve() != dl.resolve():   # into Downloads itself: the browser's own name stays
        target = unique(dest, name)
        shutil.move(str(found), str(target))
        found = target
    st.pop("progress", None)
    return f"downloaded {found.name} ({_mb(found.stat().st_size)}) into {where(found.parent, ws)}", [str(found)]


def _do(st, tick, ws):
    """Carry out one step. Paths are checked again here: a link could have changed since the card was shown."""
    op = st["do"]
    if op == "folder":
        p = check(st["path"], must_exist=False)
        had = p.is_dir()
        p.mkdir(parents=True, exist_ok=True)
        return (f"the folder {where(p, ws)} was already there" if had else f"made the folder {where(p, ws)}"), [str(p)]
    if op in ("copy", "move"):
        dest = check(st["to"])
        if not dest.is_dir():
            raise ValueError(f"{where(dest, ws)} is not a folder")
        outs = []
        for s in st["paths"]:
            tick()
            p = check(s)
            if op == "move" and onedrive(p):
                raise ValueError(f"{p.name} is in OneDrive")
            target = unique(dest, p.name)
            if op == "move":
                shutil.move(str(p), str(target))
            elif p.is_dir():
                shutil.copytree(p, target, symlinks=True)
            else:
                shutil.copy2(p, target)
            outs.append(str(target))
        names = ", ".join(Path(o).name for o in outs)
        return f"{'copied' if op == 'copy' else 'moved'} {len(outs)} into {where(dest, ws)}: {names}", outs
    if op == "rename":
        p = check(st["path"])
        target = p.parent / st["name"]
        if target.exists():
            raise ValueError(f"there is already a “{st['name']}” there")
        p.rename(target)
        return f"renamed to {st['name']}", [str(target)]
    if op == "trash":
        done = []
        for s in st["paths"]:
            tick()
            p = check(s)
            if onedrive(p):
                raise ValueError(f"{p.name} is in OneDrive")
            _trash(p)
            done.append(p.name)
        return f"put in the Trash: {', '.join(done)}", []
    if op == "download":
        check(st["to"])
        return _download(st, tick, ws)
    if op == "open":
        if st.get("url"):
            OPENER(st["url"])
            return "opened in your browser", []
        p = check(st["path"])
        OPENER(str(p))
        return f"opened {p.name}", [str(p)]
    if op == "show":
        p = check(st["path"])
        subprocess.run(["/usr/bin/open", "-R", str(p)], check=False, timeout=15)
        return f"shown in Finder: {p.name}", [str(p)]
    raise ValueError(f"unknown step {op}")


# ---------------------------------------------------------------- ask-do: the chat's command

def _load_plan(arg, ws):
    arg = (arg or "").strip()
    if arg and not arg.startswith(("{", "[")):
        p = Path(os.path.expanduser(arg))
        p = p if p.is_absolute() else Path(ws) / p
        try:
            p = p.resolve()
            p.relative_to(Path(ws).resolve())
        except (OSError, ValueError):
            raise ValueError("the plan file must be in this conversation's workspace folder")
        try:
            arg = p.read_text()
        except OSError:
            raise ValueError(f"cannot read the plan file {p.name}")
    try:
        return json.loads(arg)
    except ValueError as e:
        raise ValueError(f"the plan is not valid JSON ({e})")


def run_request(req, ws=None, wait=None):
    """Wait for the answer, then carry out the steps allowed. Returns the request as it ended."""
    rid, wait = req["id"], WAIT if wait is None else wait
    t0, beat = time.time(), time.time()
    ans = None
    while ans is None:
        ans = _read(_path(rid, ".decision.json"))
        if ans:
            break
        if time.time() - t0 > wait:
            _answer(rid, {"approve": False, "steps": [], "by": "expired"})
            ans = _read(_path(rid, ".decision.json"))
            break
        if time.time() - beat > BEAT:
            req["beat"], beat = time.time(), time.time()
            _write(req)
        time.sleep(POLL)
    by = (ans or {}).get("by")
    if not ans or not ans.get("approve"):
        req["status"] = {"expired": "expired", "stopped": "stopped"}.get(by, "declined")
        for st in req["steps"]:
            st["state"] = "skipped"
        req["beat"] = time.time()
        _write(req)
        return req
    chosen = set(ans.get("steps") or [])
    req["status"] = "running"
    for i, st in enumerate(req["steps"]):
        if i not in chosen:
            st["state"] = "skipped"
    _write(req)
    last = [time.time()]

    def tick():
        if _path(rid, ".stop").exists():
            raise Stopped()
        if time.time() - last[0] > 2:
            last[0] = req["beat"] = time.time()
            _write(req)

    stopped = False
    for i, st in enumerate(req["steps"]):
        if i not in chosen:
            continue
        if stopped:
            st["state"], st["error"] = "skipped", "stopped before this step"
            continue
        st["state"] = "running"
        req["beat"] = time.time()
        _write(req)
        try:
            tick()
            st["result"], st["out"] = _do(st, tick, ws)
            st["state"] = "done"
        except Stopped:
            st["state"], st["error"], stopped = "failed", "stopped", True
        except Exception as e:
            st["state"], st["error"] = "failed", str(e)[:400]
        req["beat"] = time.time()
        _write(req)
    req["status"] = "stopped" if stopped else "done"
    req["beat"] = time.time()
    _write(req)
    return req


def report(req):
    """What the chat reads back: each step's outcome, in words it cannot mistake."""
    st = req.get("status")
    if st == "expired":
        return (f"No answer within {WAIT // 60} minutes: the request expired and nothing was done. Tell them, and that they can ask "
                "you to try again.")
    if st == "stopped" and not any(s.get("state") == "done" for s in req["steps"]):
        return "The turn was stopped: nothing was done."
    if st == "declined":
        return ("They declined: nothing was done. Do not ask again for the same steps in this answer; say what you would have "
                "done and ask what they want instead.")
    allowed = [s for s in req["steps"] if s.get("state") != "skipped" or s.get("error")]
    left = [s for s in req["steps"] if s.get("state") == "skipped" and not s.get("error")]
    lines = [f"Allowed {len(allowed)} of {len(req['steps'])} steps" + (" (the turn was then stopped)" if st == "stopped" else "") + ":"]
    for s in req["steps"]:
        mark = {"done": "✓", "failed": "✗"}.get(s.get("state"), "–")
        what = s.get("result") or (f"failed: {s['error']}" if s.get("error") else "not allowed, not done")
        lines.append(f"{mark} {s['label']}: {what}")
        if s.get("out") and s.get("state") == "done":
            lines.append("   " + "; ".join(s["out"][:12]))
    if left:
        lines.append("Steps marked – were left out by them: do not do them another way.")
    lines.append("Say what was done and what was not. Never say a step was done unless it is ✓ here.")
    return "\n".join(lines)


def ask(arg, env=None):
    """`assist.cli ask-do PLAN` (the chat): check the plan, ask, wait, carry out what is allowed, print the outcome."""
    env = os.environ if env is None else env
    from .chat_tools import workspace
    ws = workspace()
    thread, run = env.get("ASSIST_CHAT_THREAD"), env.get("ASSIST_CHAT_RUN") or ""
    if not thread or not ws:
        return "ask-do works only inside an Ask SleePO conversation.", 1
    try:
        plan = _load_plan(arg, ws)
    except ValueError as e:
        return f"Nothing was asked: {e}.", 1
    steps, errors = prepare(plan, ws)
    if errors:
        return "Nothing was asked. Fix these and run ask-do again:\n" + "\n".join(errors), 1
    purge()
    req = {"id": "d" + uuid.uuid4().hex[:12], "thread": thread, "run": run, "created_at": _now(), "beat": time.time(),
           "why": str((plan.get("why") if isinstance(plan, dict) else "") or "")[:300], "status": "pending", "steps": steps}
    _write(req)
    req = run_request(req, ws)
    return report(req), 0
