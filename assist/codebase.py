"""The company's source code, from the git clones on this Mac (Sam, 20 Nov 2026: "a page with the code base ... the full
[company] code base that we have in GitLab with the monolith ... cloned locally ... if ever the assistant needs to query
the code directly ... Not always, 'cause I guess it's a big query, but I want it there").

The case that asked for it: a sales leader asked how the platform supports certain user roles; the emery yates and the
product docs did not say, the code does. So the code is the last place SleePO looks for how the product behaves, not the first.

Where it comes from. Clones are found, not configured: the folders in the home folder (two levels down) whose `origin` is
on the company's code host (org pack `code.hosts`, e.g. "gitlab.com/acme/"), plus any folder added on the Code base page
(settings `code_repos` {"add": [...], "hide": [...]}). Nothing is copied into SleePO: every read is `git` on the clone.

What is read. The clone's default branch as GitLab last gave it (refs/remotes/origin/<branch>), never the working tree, so
local edits and build output in the folder do not count and an update never touches them. Update (`fetch`) runs
`git fetch` for that one branch into that remote-tracking ref (over the clone's own remote, or SSH when its HTTPS token is
refused); the working tree, local branches and stashes are left alone. Weekly from the full refresh, and on the page.

Who reads it.
- The Code base page (Knowledge › Product): the clones, how current each is, search, and links into GitLab.
- Ask SleePO through `assist.cli ask-code` (repos, search, files, ls, read). Its instructions say to try the emery yates and the product docs first and to read code only for how the product actually behaves (roles and permissions,
  settings, limits, APIs), or when asked.
Key files, certificates and env files are never searched or read, and values that look like passwords or tokens are
masked in what comes back. Reads only, except fetch() and settings changes made from the page.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db

HOME = Path.home()
SKIP_DIRS = {"Library", "Applications", "Movies", "Music", "Pictures", "Public", "node_modules", "SleePO Workspace", "Desktop", "Downloads"}
EXTRA_ROOTS = ("Documents/GitHub", "Documents/GitLab", "Documents/code", "Documents/repos")
JOB = db.db_path().parent / "jobs" / "code_fetch.json"
LOCK = "code-fetch"
EVERY_DAYS = 7
GIT_TIMEOUT = 30
FETCH_TIMEOUT = 1800
MAX_READ = 60000
_cache = {}

# never searched or read: keys, certificates, keystores, env and credential files, lock files and minified bundles
SECRET_GLOBS = ("**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx", "**/*.jks", "**/*.keystore", "**/*.crt", "**/*.cer",
                "**/.env", "**/.env.*", "**/*.env", "**/.npmrc", "**/.netrc", "**/.pypirc", "**/id_rsa*", "**/id_ed25519*",
                "**/*private.properties*", "**/*secrets*.json", "**/*secrets*.y*ml", "**/*credentials*.json")
NOISE_GLOBS = ("**/node_modules/**", "**/*.min.js", "**/*.min.css", "**/*.map", "**/package-lock.json", "**/yarn.lock",
               "**/pnpm-lock.yaml", "**/*.lock", "**/*.svg")
SECRET_PATH = re.compile(r"(\.(pem|key|p12|pfx|jks|keystore|crt|cer|env)$|(^|/)\.env(\.|$)|(^|/)\.(npmrc|netrc|pypirc)$|(^|/)id_(rsa|ed25519)|"
                         r"private\.properties|secrets?[^/]*\.(json|ya?ml)$|credentials[^/]*\.json$)", re.I)
SECRET_VALUE = re.compile(r"((?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret)"
                          r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{8,})", re.I)
LANG = {".java": "Java", ".kt": "Kotlin", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
        ".cs": ".NET (C#)", ".py": "Python", ".go": "Go", ".sql": "SQL", ".less": "CSS", ".css": "CSS", ".scss": "CSS",
        ".html": "HTML", ".jsp": "JSP", ".xml": "XML", ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".md": "Docs",
        ".properties": "Config", ".sh": "Shell", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".c": "C", ".cpp": "C++", ".h": "C"}
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|e2e)(/|$)|\.(spec|test)\.\w+$|Tests?\.(java|kt|cs)$", re.I)


# ---------------------------------------------------------------- configuration
def config():
    """The org pack's `code` section: hosts (where the company's code lives, as it appears in a remote URL), host_name,
    map_doc (the emery yates note that maps repositories to products) and repos ({name: {label, about}})."""
    from . import org
    c = org.section("code", {}) or {}
    return c if isinstance(c, dict) else {}


def _settings(con=None):
    from .profile import read_only
    c = con or read_only(db.db_path())
    try:
        r = c.execute("SELECT value FROM settings WHERE key='code_repos'").fetchone() if c is not None else None
        v = json.loads(r[0]) if r and r[0] else {}
    except Exception:
        v = {}
    finally:
        if con is None and c is not None:
            c.close()
    v = v if isinstance(v, dict) else {}
    return {"add": [str(p) for p in v.get("add") or []], "hide": [str(p) for p in v.get("hide") or []]}


def save_settings(con, add=None, hide=None, show=None):
    """The page's Add a clone / Remove / show again. Writes the settings row only when it changes."""
    s = _settings(con)
    if add:
        p = str(Path(os.path.expanduser(add)).resolve())
        if not (Path(p) / ".git").exists():
            raise ValueError("That folder is not a git clone (it has no .git folder).")
        s["add"] = [x for x in s["add"] if x != p] + [p]
        s["hide"] = [x for x in s["hide"] if x != p]
    if hide:
        s["hide"] = sorted(set(s["hide"]) | {str(hide)})
        s["add"] = [x for x in s["add"] if x != str(hide)]
    if show:
        s["hide"] = [x for x in s["hide"] if x != str(show)]
    v = json.dumps(s)
    old = con.execute("SELECT value FROM settings WHERE key='code_repos'").fetchone()
    if not old or old[0] != v:
        con.execute("INSERT INTO settings (key, value) VALUES ('code_repos', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (v,))
        con.commit()
    _cache.clear()
    return s


# ---------------------------------------------------------------- git
def _git(path, *args, timeout=GIT_TIMEOUT, env=None, text=True):
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=text, timeout=timeout,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0", **(env or {})))
    return r


def _out(path, *args):
    try:
        r = _git(path, *args)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _remote(path):
    return _out(path, "config", "--get", "remote.origin.url")


def web_url(remote):
    """https://host/group/repo from an SSH or HTTPS remote, without credentials or .git."""
    r = (remote or "").strip()
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", r)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", r)
    return f"https://{m.group(1)}/{m.group(2)}" if m else ""


def ssh_url(remote):
    """The SSH form of an HTTPS remote (git@host:group/repo.git), or None."""
    m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", (remote or "").strip())
    return f"git@{m.group(1)}:{m.group(2)}.git" if m else None


def _ours(remote, hosts):
    r = (remote or "").lower()
    return any(h.lower() in r for h in hosts if h)


def _candidates():
    roots, seen = [], set()
    for d in [HOME] + [HOME / x for x in EXTRA_ROOTS]:
        if d.is_dir():
            roots.append(d)
    out = []
    for root in roots:
        try:
            first = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_DIRS
                     and not p.name.startswith("OneDrive")]
        except OSError:
            continue
        for p in first:
            for q in [p] + ([c for c in _subdirs(p)] if root == HOME else []):
                if q not in seen and (q / ".git").exists():
                    seen.add(q)
                    out.append(q)
    return out


def _subdirs(p):
    try:
        return [c for c in p.iterdir() if c.is_dir() and not c.name.startswith(".") and c.name not in SKIP_DIRS]
    except OSError:
        return []


def clones(con=None):
    """[{name, path, remote, web}] for the company's code on this Mac, the hidden ones left out. Cached 10 minutes."""
    hit = _cache.get("clones")
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    hosts = config().get("hosts") or []
    s = _settings(con)
    paths = [p for p in _candidates() if hosts and _ours(_remote(p), hosts)]
    for a in s["add"]:
        p = Path(a)
        if (p / ".git").exists() and p not in paths:
            paths.append(p)
    out = []
    for p in paths:
        if str(p) in s["hide"]:
            continue
        rem = _remote(p)
        web = web_url(rem)
        out.append({"name": (web.rsplit("/", 1)[-1] if web else p.name), "path": str(p), "remote": rem, "web": web})
    out.sort(key=lambda r: r["name"].lower())
    _cache["clones"] = (time.time(), out)
    return out


def hidden(con=None):
    return _settings(con)["hide"]


def find(name, con=None):
    """A clone by its name (or folder name, or path); None when there is none."""
    n = (name or "").strip().lower()
    for r in clones(con):
        if n in (r["name"].lower(), Path(r["path"]).name.lower(), r["path"].lower()):
            return r
    return None


def branch(path):
    """The branch GitLab calls default (origin/HEAD), else main, master or develop, whichever origin has."""
    b = _out(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if b.startswith("origin/"):
        return b[len("origin/"):]
    for x in ("main", "master", "develop"):
        if _out(path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{x}"):
            return x
    return _out(path, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"


def ref(path):
    """(ref read, its commit sha, branch): the remote-tracking branch when there is one, else the clone's HEAD."""
    b = branch(path)
    r = f"refs/remotes/origin/{b}"
    sha = _out(path, "rev-parse", "--verify", "--quiet", r + "^{commit}")
    if not sha:
        r, sha = "HEAD", _out(path, "rev-parse", "HEAD")
    return r, sha, b


def _files(path, sha):
    key = ("files", path, sha)
    hit = _cache.get(key)
    if hit:
        return hit
    out = _out(path, "ls-tree", "-r", "--name-only", "--full-tree", sha)
    names = [n for n in out.split("\n") if n]
    _cache[key] = names
    return names


def describe(r, con=None):
    """A clone as the page and the chat show it: what it is, the branch read, how current, what is in it."""
    path = r["path"]
    rf, sha, b = ref(path)
    key = ("describe", path, sha)
    if key in _cache:
        d = dict(_cache[key])
    else:
        log = _out(path, "log", "-1", "--format=%cI%x1f%s", sha) if sha else ""
        as_of, subject = (log.split("\x1f", 1) + [""])[:2] if log else ("", "")
        names = _files(path, sha) if sha else []
        langs, tops = {}, {}
        for n in names:
            lang = LANG.get(os.path.splitext(n)[1].lower())
            if lang and lang not in ("JSON", "YAML", "XML", "Docs", "Config"):
                langs[lang] = langs.get(lang, 0) + 1
            if "/" in n and not n.startswith("."):
                t = n.split("/", 1)[0]
                tops[t] = tops.get(t, 0) + 1
        guide = next((n for n in ("CLAUDE.md", "README.md", "readme.md") if n in names), None)
        d = {"ref": rf, "sha": sha, "branch": b, "as_of": as_of, "subject": subject[:160], "files": len(names),
             "languages": sorted(langs.items(), key=lambda x: -x[1])[:6], "folders": sorted(tops.items(), key=lambda x: -x[1])[:12],
             "guide": guide, "tracking": rf != "HEAD"}
        _cache[key] = dict(d)
    meta = (config().get("repos") or {}).get(r["name"]) or {}
    st = (state().get("repos") or {}).get(path) or {}
    fetched = st.get("fetched_at")
    if not fetched:
        fh = Path(path) / ".git" / "FETCH_HEAD"
        fetched = datetime.fromtimestamp(fh.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if fh.exists() else None
    return {**r, **d, "label": meta.get("label") or "", "about": meta.get("about") or "", "fetched_at": fetched,
            "fetch": {k: st.get(k) for k in ("ok", "note", "new_commits", "finished") if k in st}}


def overview(con=None):
    """GET /api/code: the clones, described; the repositories the emery yates names that are not on this Mac; settings."""
    cl = [describe(r, con) for r in clones(con)]
    have = {r["web"].lower() for r in cl if r.get("web")}
    cfg = config()
    return {"repos": cl, "not_cloned": [x for x in known(con) if x["url"].lower() not in have], "hidden": hidden(con),
            "host": cfg.get("host_name") or "GitLab", "map_doc": cfg.get("map_doc") or "", "fetch": state(),
            "configured": bool(cfg.get("hosts"))}


def known(con=None):
    """The repositories the emery yates's map names ([{path, url, about}]), read from SleePO's copy of that note."""
    doc = config().get("map_doc")
    if not doc:
        return []
    c = con or db.connect()
    try:
        row = c.execute("SELECT body_md FROM documents WHERE id=?", (doc,)).fetchone()
    except Exception:
        row = None
    finally:
        if con is None:
            c.close()
    body = (row[0] if row else "") or ""
    out, seen, hosts = [], set(), config().get("hosts") or []
    for m in re.finditer(r"\[([\w./-]+)\]\((https://[^)\s]+)\)\**\s*(?:\||[—-])\s*([^|\n]+)", body):
        url, about = m.group(2).rstrip("/"), m.group(3).strip(" *|")
        if url in seen or not _ours(url, hosts):
            continue
        seen.add(url)
        out.append({"path": url.split("://", 1)[1].split("/", 1)[1], "url": url, "about": re.sub(r"\*\*|\[\[|\]\]", "", about)[:200]})
    return out


# ---------------------------------------------------------------- reading
def _mask(line):
    return SECRET_VALUE.sub(lambda m: m.group(1) + "[hidden]", line)


def _pathspec(path_glob=None):
    spec = []
    g = (path_glob or "").strip()
    if g:
        if any(ch in g for ch in "*?["):   # "*.java" means any Java file, not only those at the top
            spec.append(f":(icase,glob){g if '/' in g else '**/' + g}")
        else:
            g = g.strip("/")
            spec += [f":(icase,glob)**/*{g}*", f":(icase,glob)**/*{g}*/**"] if "/" not in g else [f":(icase,glob){g}/**", f":(icase,glob){g}"]
    return spec + [f":(exclude,glob){x}" for x in SECRET_GLOBS + NOISE_GLOBS]


def _targets(repo=None, con=None):
    if repo:
        r = find(repo, con)
        return [r] if r else []
    return clones(con)


def search(pattern, repo=None, path_glob=None, files_max=40, per_file=6, con=None):
    """Lines matching an extended regular expression (case-insensitive) in the branch each clone reads:
    {repos: [{name, ref, sha, as_of, web, total, files: [{path, hits, test, link, lines: [{n, text, link}]}]}], error}."""
    pattern = (pattern or "").strip()
    if not pattern:
        return {"repos": [], "error": "Nothing to search for."}
    out = []
    for r in _targets(repo, con):
        rf, sha, b = ref(r["path"])
        if not sha:
            continue
        try:
            p = _git(r["path"], "grep", "-n", "-I", "-i", "-E", "--full-name", "-e", pattern, sha, "--", *_pathspec(path_glob),
                     timeout=60)
        except subprocess.TimeoutExpired:
            out.append({"name": r["name"], "error": "The search took too long; narrow it with a path."})
            continue
        if p.returncode not in (0, 1):
            return {"repos": out, "error": (p.stderr or "").strip().splitlines()[-1][:300] if p.stderr else "git grep failed"}
        files = {}
        pre = sha + ":"
        for line in p.stdout.splitlines():
            if not line.startswith(pre):
                continue
            rest = line[len(pre):]
            m = re.match(r"(.+?):(\d+):(.*)$", rest)
            if not m:
                continue
            fp, n, text = m.group(1), int(m.group(2)), m.group(3)
            if SECRET_PATH.search(fp):
                continue
            f = files.setdefault(fp, {"path": fp, "hits": 0, "lines": []})
            f["hits"] += 1
            if len(f["lines"]) < per_file:
                f["lines"].append({"n": n, "text": _mask(text.strip())[:220], "link": blob(r, sha, fp, n)})
        ranked = sorted(files.values(), key=lambda f: (bool(TEST_PATH.search(f["path"])), -min(f["hits"], 25), f["path"]))
        for f in ranked:
            f["test"] = bool(TEST_PATH.search(f["path"]))
            f["link"] = blob(r, sha, f["path"])
        log = _out(r["path"], "log", "-1", "--format=%cI", sha)
        out.append({"name": r["name"], "ref": rf, "branch": b, "sha": sha, "as_of": log, "web": r["web"],
                    "total": sum(f["hits"] for f in files.values()), "file_count": len(files), "files": ranked[:files_max]})
    return {"repos": out, "error": None if out or not repo else f"No clone called “{repo}”."}


def blob(r, sha, path, line=None):
    """The file at that commit in GitLab (the exact version read), at a line."""
    if not r.get("web"):
        return ""
    from urllib.parse import quote
    return f"{r['web']}/-/blob/{sha}/{quote(path)}" + (f"#L{line}" if line else "")


def files(words, repo=None, limit=80, con=None):
    """Files whose path holds every word (case-insensitive): [{name, path, link}]."""
    ws = [w.lower() for w in re.split(r"\s+", words or "") if w]
    out = []
    for r in _targets(repo, con):
        rf, sha, b = ref(r["path"])
        for n in _files(r["path"], sha) if sha else []:
            low = n.lower()
            if all(w in low for w in ws) and not SECRET_PATH.search(n):
                out.append({"name": r["name"], "path": n, "link": blob(r, sha, n)})
                if len(out) >= limit:
                    return out
    return out


def ls(repo, folder="", con=None):
    """A folder of a clone: its subfolders (with file counts) and files."""
    r = find(repo, con)
    if not r:
        return None
    rf, sha, b = ref(r["path"])
    pre = folder.strip("/") + "/" if folder.strip("/") else ""
    dirs, fs = {}, []
    for n in _files(r["path"], sha):
        if not n.startswith(pre):
            continue
        rest = n[len(pre):]
        if "/" in rest:
            d = rest.split("/", 1)[0]
            dirs[d] = dirs.get(d, 0) + 1
        elif not SECRET_PATH.search(n):
            fs.append(rest)
    return {"repo": r["name"], "folder": pre, "dirs": sorted(dirs.items()), "files": sorted(fs)}


def read(repo, path, start=1, end=None, con=None):
    """A file at the branch read, with line numbers: {repo, path, link, start, end, lines, total, text} or {error}."""
    r = find(repo, con)
    if not r:
        return {"error": f"No clone called “{repo}”. Run ask-code repos."}
    path = (path or "").strip().lstrip("/")
    if SECRET_PATH.search(path):
        return {"error": "That file holds keys or credentials; SleePO does not read it."}
    rf, sha, b = ref(r["path"])
    try:
        p = _git(r["path"], "show", f"{sha}:{path}", text=False)
    except (OSError, subprocess.SubprocessError):
        return {"error": "git could not read it."}
    if p.returncode != 0:
        near = [f["path"] for f in files(os.path.basename(path), r["name"], limit=5, con=con)]
        return {"error": f"No file {path} on {b}." + (" Did you mean: " + ", ".join(near) if near else "")}
    data = p.stdout
    if b"\0" in data[:8000]:
        return {"error": "That is a binary file."}
    lines = data.decode("utf-8", "replace").removesuffix("\n").split("\n")
    start = max(1, int(start or 1))
    end = min(len(lines), int(end or start + 399))
    body, size = [], 0
    for i in range(start, end + 1):
        t = f"{i:>5}  {_mask(lines[i - 1])}"
        size += len(t) + 1
        if size > MAX_READ:
            end = i - 1
            break
        body.append(t)
    return {"repo": r["name"], "path": path, "branch": b, "sha": sha, "link": blob(r, sha, path, start if start > 1 else None),
            "start": start, "end": end, "total": len(lines), "text": "\n".join(body)}


# ---------------------------------------------------------------- updating from GitLab
def state():
    try:
        return json.loads(JOB.read_text())
    except (OSError, ValueError):
        return {}


def running():
    from . import jobs
    return jobs.held(LOCK)


def _write(d):
    JOB.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOB.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    tmp.replace(JOB)


def due(now=None):
    """True when no clone has been updated in EVERY_DAYS (the full refresh's weekly update)."""
    now = now or datetime.now(timezone.utc)
    last = state().get("finished")
    try:
        t = datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
    except ValueError:
        t = None
    return t is None or (now - t).days >= EVERY_DAYS


def start(repo=None):
    """Update in the background (Code base › Update): one at a time; returns the state."""
    from . import jobs
    if running():
        return state() | {"running": True}
    jobs.spawn_cli("code-fetch", *(["--repo", repo] if repo else []))
    return state() | {"running": True, "started": db.now()}


def _fetch_one(r, log=print):
    path, rem = r["path"], r["remote"]
    b = branch(path)
    before = _out(path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{b}^{{commit}}")
    spec = f"+refs/heads/{b}:refs/remotes/origin/{b}"
    env = {"GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15", "GIT_ASKPASS": "/usr/bin/false", "SSH_ASKPASS": "/usr/bin/false"}
    tries = [("origin", "its remote")] + ([(ssh_url(rem), "SSH")] if ssh_url(rem) else [])
    err = ""
    for src, how in tries:
        try:
            p = _git(path, "fetch", "--no-tags", "--quiet", src, spec, timeout=FETCH_TIMEOUT, env=env)
        except subprocess.TimeoutExpired:
            err = "the download took over 30 minutes"
            continue
        if p.returncode == 0:
            after = _out(path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{b}^{{commit}}")
            new = int(_out(path, "rev-list", "--count", f"{before}..{after}") or 0) if before and after else None
            note = (f"{new} new commit{'s' if new != 1 else ''} on {b}" if new else f"{b} was already current") if new is not None else f"read {b}"
            log(f"{r['name']}: {note} (via {how})")
            return {"ok": True, "note": note, "new_commits": new, "via": how}
        err = ((p.stderr or "").strip().splitlines() or ["git fetch failed"])[-1][:300]
        log(f"{r['name']}: {how} refused: {err}")
    return {"ok": False, "note": f"{config().get('host_name') or 'The code host'} refused the update: {err}"}


def fetch(repo=None, log=print):
    """Body of `assist.cli code-fetch`: update each clone's default branch from its remote. Never touches the working tree."""
    from . import jobs
    with jobs.exclusive(LOCK) as got:
        if not got:
            log("code-fetch: another update is running")
            return False
        st = state()
        st.update(running=True, started=db.now())
        _write(st)
        ok = True
        targets = _targets(repo)
        for r in targets:
            res = _fetch_one(r, log)
            ok &= res["ok"]
            st.setdefault("repos", {})[r["path"]] = res | {"finished": db.now(), **({"fetched_at": db.now()} if res["ok"] else
                                                          {"fetched_at": (st.get("repos", {}).get(r["path"]) or {}).get("fetched_at")})}
        _cache.clear()
        st.update(running=False, finished=db.now(), ok=ok)
        _write(st)
        return ok


# ---------------------------------------------------------------- the chat's tool (assist.cli ask-code)
USAGE = """ask-code repos                                  the clones, what each is, the branch read and how current
ask-code search "REGEX" [--repo NAME] [--path GLOB]   matching lines (case-insensitive extended regex), by file
ask-code files "WORDS" [--repo NAME]           files whose path holds every word
ask-code ls NAME [FOLDER]                      a folder's subfolders and files
ask-code read NAME PATH [FROM-TO]              a file with line numbers (400 lines at a time)"""


def _age(iso):
    try:
        t = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    d = (datetime.now(timezone.utc) - t).days
    return f"{t:%-d %b %Y} ({d} days ago)" if d > 1 else f"{t:%-d %b %Y}"


def ask(argv):
    """The text `assist.cli ask-code ...` prints for the chat."""
    if not argv:
        return USAGE
    cmd, rest = argv[0], argv[1:]
    opts, pos = {}, []
    i = 0
    while i < len(rest):
        if rest[i] in ("--repo", "--path") and i + 1 < len(rest):
            opts[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            pos.append(rest[i])
            i += 1
    if cmd == "repos":
        ov = overview()
        if not ov["repos"]:
            return "No clone of the company's code is on this Mac (the Code base page, Knowledge › Product, adds one)."
        L = []
        for r in ov["repos"]:
            L.append(f"## {r['name']}" + (f": {r['label']}" if r["label"] else ""))
            if r["about"]:
                L.append(r["about"])
            L.append(f"Reads {r['branch']} as of {_age(r['as_of'])}: {r['subject']}" + ("" if r["tracking"] else " (the clone's own HEAD)"))
            L.append(f"{r['files']:,} files · " + ", ".join(f"{k} {v:,}" for k, v in r["languages"]) + f" · {r['web']}")
            L.append("Top folders: " + ", ".join(f"{k} ({v:,})" for k, v in r["folders"]))
            if r["guide"]:
                L.append(f"Developers' guide: ask-code read {r['name']} {r['guide']}")
            L.append("")
        if ov["not_cloned"]:
            L.append("In GitLab but not on this Mac (cannot be read; name them when the answer may live there):")
            L += [f"- {x['path']}: {x['about']}" for x in ov["not_cloned"][:30]]
        return "\n".join(L)
    if cmd == "search":
        if not pos:
            return USAGE
        res = search(pos[0], opts.get("repo"), opts.get("path"))
        if res.get("error") and not res["repos"]:
            return res["error"]
        L = []
        for r in res["repos"]:
            if r.get("error"):
                L.append(f"## {r['name']}: {r['error']}")
                continue
            L.append(f"## {r['name']} ({r['branch']} as of {_age(r['as_of'])}): {r['total']:,} lines in {r['file_count']:,} files"
                     + (f", the first {len(r['files'])} shown (tests last)" if r["file_count"] > len(r["files"]) else ""))
            if r["web"]:
                L.append(f"Link a file as {r['web']}/-/blob/{r['sha']}/<path>#L<line>")
            for f in r["files"]:
                L.append(f"{f['path']}  ({f['hits']} line{'s' if f['hits'] != 1 else ''}{', test' if f['test'] else ''})")
                L += [f"  {x['n']}: {x['text']}" for x in f["lines"]]
        if res.get("error"):
            L.append(res["error"])
        return "\n".join(L) or "No match."
    if cmd == "files":
        fs = files(" ".join(pos), opts.get("repo"))
        return "\n".join(f"{f['name']}  {f['path']}" for f in fs) or "No file path holds all those words."
    if cmd == "ls":
        if not pos:
            return USAGE
        d = ls(pos[0], pos[1] if len(pos) > 1 else "")
        if d is None:
            return f"No clone called “{pos[0]}”. Run ask-code repos."
        return "\n".join([f"{d['repo']}/{d['folder']}"] + [f"  {k}/  ({v:,} files)" for k, v in d["dirs"]] + [f"  {f}" for f in d["files"]])
    if cmd == "read":
        if len(pos) < 2:
            return USAGE
        a, b = 1, None
        if len(pos) > 2:
            m = re.match(r"(\d+)(?:\s*[-:,]\s*(\d+))?$", pos[2])
            if m:
                a, b = int(m.group(1)), int(m.group(2)) if m.group(2) else None
        d = read(pos[0], pos[1], a, b)
        if d.get("error"):
            return d["error"]
        more = f"\n… lines {d['end'] + 1}-{d['total']} not shown: ask-code read {d['repo']} {d['path']} {d['end'] + 1}-{d['end'] + 400}" if d["end"] < d["total"] else ""
        return f"# {d['repo']}/{d['path']} ({d['branch']}, lines {d['start']}-{d['end']} of {d['total']})\n{d['link']}\n{d['text']}{more}"
    return USAGE
