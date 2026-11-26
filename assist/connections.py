"""Can SleePO reach what it reads? (Sam, 17 Nov 2026: "now it's asking me to sign back into my Microsoft 365 account. I want
this to be flagged to me ... I would click on something and it would take me to the login page ... right now I only see these
issues when I go looking for them.")

Microsoft 365 had needed a new sign-in since 15 Nov 2026. Every pull of Teams failed, and so did the Outlook fallback and the
roadmap check. The pulls' notes said so in prose, and the Sources page still said Up to date because a failed pull moves
last_pull_at.

What is checked
  connectors  the claude.ai connectors the pulls use (Microsoft 365, Slack, the org pack's CRM connector). `probe` runs
              `claude mcp list`, which checks every MCP server Claude Code would load here and prints Connected, Needs
              authentication or Failed to connect for each (about 7 s, no model call, no session). It runs at the start of
              every refresh, at server start when the last check is over an hour old, and on Check again. Every pull's
              stream-json init event lists the servers too (`seen_init`), but the claude.ai connectors are usually still
              "pending" there, so it only adds a status when one is already known.
  local       what the refresh reads on this Mac: Apple Mail and Calendar.app (Full Disk Access, Mail running, Calendar
              synced) and Granola's screenshots (SleePO's own Granola sign-in), from the import's exit code (`note_local`).

Stored as one settings row `connections` (JSON). It is written only when a status changes or the last check is over an
hour old, so the 30-minute quick sync does not rewrite it. `issues(con)` reads it and never writes. For each problem it
says what stopped, since when, which sources are affected and when each last came in, and what to do (`fix`). For a
connector that is Sign in: `login` asks Claude Code for its sign-in link and opens it in the browser.
"""
import json
import os
import re
import subprocess
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import db, org

KEY = "connections"
# Signing in again (17 Nov 2026: claude.ai/settings/connectors, the first fix, now only says connectors have moved):
# `claude mcp login "<server>"` is Claude Code's own sign-in for a connector. For a claude.ai connector it prints a claude.ai
# authorisation link and exits (--no-browser); SleePO opens that link in the browser (`login`). Only claude.ai links are opened.
SIGNIN_HOST = "claude.ai"
REWRITE_AFTER = timedelta(hours=1)   # a check that changed nothing still refreshes `checked` this often
UNREACHABLE_GRACE = timedelta(hours=6)   # a connector that does not answer is flagged in the header only after this long
BAD = {"needs-auth": "signin", "failed": "unreachable", "no-access": "access", "not-running": "app", "not-synced": "app",
       "signed-out": "signin"}
_LOCK = threading.Lock()


def _norm(name):
    """'claude.ai Microsoft 365' and the tool prefix 'Microsoft_365' both become 'Microsoft_365'."""
    name = re.sub(r"^claude\.ai\s+", "", name or "")
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def watched():
    """What SleePO reads through, with what each brings and the sources it feeds. Products, not people or company data;
    the CRM connector comes from the org pack."""
    rows = [
        {"key": "Microsoft_365", "name": "Microsoft 365", "kind": "connector",
         "feeds": "Teams messages, SharePoint documents and the roadmap workbook, and Outlook mail when Apple Mail cannot be read",
         "sources": ["teams", "sharepoint", "roadmap", "outlook.inbox", "outlook.sent"]},
        # Claude Code loads Slack as the claude.ai connector or the productivity plugin's server (it keeps one when both
        # point at the same address); either one connected is enough
        {"key": "Slack", "name": "Slack", "kind": "connector", "feeds": "Slack messages", "sources": ["slack"],
         "aliases": ["plugin_productivity_slack"]},
    ]
    crm = org.section("crm", {}) or {}
    if crm.get("connector"):
        rows.append({"key": _norm(crm["connector"]), "name": crm["connector"].replace("_", " "), "kind": "connector",
                     "feeds": f"the {crm.get('system') or 'CRM'} pipeline", "sources": ["salesforce"]})
    rows += [
        {"key": "apple-mail", "name": "Apple Mail", "kind": "local", "feeds": "your mail", "sources": ["outlook.inbox", "outlook.sent"]},
        {"key": "calendar-app", "name": "Calendar.app", "kind": "local", "feeds": "your calendar", "sources": ["calendar"]},
        {"key": "granola-mcp", "name": "Granola screenshots", "kind": "local", "feeds": "what was on screen in your meetings", "sources": []},
    ]
    return rows


def _by_key():
    return {w["key"]: w for w in watched()}


RANK = {"connected": 0, "failed": 1, "needs-auth": 2}   # the best status wins when a connector is loaded under two names


def _fold(found, raw=None, names=None):
    """{server key: status} -> {watched connector key: status}, with aliases folded in (the best status wins).
    raw {server key: the server's own name}; names, when given, is filled with {connector key: the winning server's name}."""
    alias = {}
    for w in watched():
        if w["kind"] == "connector":
            for k in [w["key"], *w.get("aliases", [])]:
                alias[k] = w["key"]
    out = {}
    for k, st in found.items():
        if k in alias and st in RANK:
            key = alias[k]
            if key not in out or RANK[st] < RANK[out[key]]:
                out[key] = st
                if names is not None and raw and k in raw:
                    names[key] = raw[k]
    return out


# ---- reading and writing the one settings row

def load(con):
    try:
        d = json.loads(db.get_setting(con, KEY) or "{}")
    except ValueError:
        d = {}
    d.setdefault("items", {})
    return d


def record(con, statuses, via, now=None, servers=None):
    """Merge {key: status} into the stored state. Writes only when a status changed, or the last check is over an hour old.
    `since` is when a status began; `seen` is the last check that saw it; `server` the name Claude Code knows it by (for
    signing in again), from `servers`. Returns True when it wrote."""
    now = now or db.now()
    known = _by_key()
    statuses = {k: v for k, v in statuses.items() if k in known and v}
    if not statuses:
        return False
    with _LOCK:
        d = load(con)
        changed = False
        for k, st in statuses.items():
            cur = d["items"].get(k)
            server = (servers or {}).get(k) or (cur or {}).get("server")
            if not cur or cur.get("status") != st or cur.get("server") != server:
                d["items"][k] = {"status": st, "since": now if not cur or cur.get("status") != st else cur["since"], "seen": now, "via": via}
                if server:
                    d["items"][k]["server"] = server
                changed = True
            else:
                cur["seen"], cur["via"] = now, via
        old = d.get("checked")
        stale = not old or _ts(now) - _ts(old) >= REWRITE_AFTER
        if not (changed or stale):
            return False
        d["checked"] = now
        db.set_setting(con, KEY, json.dumps(d, sort_keys=True))
        return True


def _ts(iso):
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return datetime.fromtimestamp(0, timezone.utc)


def from_init(ev):
    """{key: status} for the connectors SleePO uses, from a Claude stream-json init event; None when it is not one."""
    if not isinstance(ev, dict) or ev.get("type") != "system" or ev.get("subtype") != "init":
        return None
    servers = ev.get("mcp_servers") or []   # pending says nothing yet
    return _fold({_norm(s.get("name")): s.get("status") for s in servers})


def seen_init(line, via="pull"):
    """Called with every stream-json line a Claude run prints: records the connector statuses from its init event.
    Cheap for every other line (two substring tests before any parsing). Never raises."""
    if not line or '"init"' not in line or '"mcp_servers"' not in line:
        return None
    try:
        st = from_init(json.loads(line))
    except ValueError:
        return None
    if not st:
        return None
    try:
        c = db.connect()
        try:
            record(c, st, via)
        finally:
            c.close()
    except Exception:
        pass
    return st


def note_local(key, status, via="refresh"):
    """A local import's result: 'ok', 'no-access' (no Full Disk Access), 'not-running', 'not-synced', 'signed-out'. Never raises."""
    try:
        c = db.connect()
        try:
            record(c, {key: status}, via)
        finally:
            c.close()
    except Exception:
        pass


# ---- the probe: start Claude only to read which connectors are signed in

def _claude():
    p = os.path.expanduser("~/.local/bin/claude")
    return p if os.path.exists(p) else "claude"


# one line of `claude mcp list`: "claude.ai Microsoft 365: https://… - ! Needs authentication"
_LINE = re.compile(r"^(?P<name>.+?): .* - (?:\S+ )?(?P<st>Connected|Needs authentication|Failed to connect)\b")
_STATUS = {"Connected": "connected", "Needs authentication": "needs-auth", "Failed to connect": "failed"}


def parse_list(text, names=None):
    """{connector key: status} from `claude mcp list` output (servers SleePO does not use are left out). names, when given,
    is filled with {connector key: server name}."""
    found, raw = {}, {}
    for line in (text or "").splitlines():
        m = _LINE.match(line.strip())
        if m:
            found[_norm(m["name"])] = _STATUS[m["st"]]
            raw[_norm(m["name"])] = m["name"]
    return _fold(found, raw, names)


def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_CODE_"))}   # not a child of a session


def probe(cwd=None, timeout=60, names=None):
    """{connector key: status} from `claude mcp list` run where the pulls run, so the same servers load. None when Claude
    could not be run or listed none of them. names: filled with {connector key: server name}."""
    try:
        p = subprocess.run([_claude(), "mcp", "list"], cwd=str(cwd or db.ASSIST), capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL, env=_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_list(p.stdout, names) or None


def check(via="check", cwd=None):
    """Probe and record. Returns the statuses found (None when Claude said nothing)."""
    names = {}
    st = probe(cwd, names=names)
    if st:
        c = db.connect()
        try:
            record(c, st, via, servers=names)
        finally:
            c.close()
    return st


def check_in_background(via="refresh", cwd=None, older_than=None):
    """Probe in a thread (the refresh does not wait for it). older_than: only when the last check is older than this."""
    if older_than is not None:
        try:
            c = db.connect()
            try:
                last = load(c).get("checked")
            finally:
                c.close()
        except Exception:
            last = None
        if last and datetime.now(timezone.utc) - _ts(last) < older_than:
            return None
    t = threading.Thread(target=lambda: _quiet(check, via, cwd), daemon=True)
    t.start()
    return t


def _quiet(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass


# ---- what the app shows

def default_server(w):
    """The name Claude Code gives a claude.ai connector when no check has recorded it yet."""
    return "claude.ai " + w["name"]


def _fix(w, status, server=None):
    """What to do, by what is wrong. Each has a label and one of: login (SleePO opens Claude's sign-in for that connector,
    `login`), open (a fixed target the server opens: disk, python, mail, calendar), command (copied to run in Terminal),
    check (Check again)."""
    name = w["name"]
    if w["kind"] == "connector":
        cmd = f'claude mcp login "{server or default_server(w)}"'
        if status == "needs-auth":
            return {"label": f"Sign in to {name}", "login": w["key"], "also": {"label": "Copy the Terminal command", "command": cmd},
                    "steps": "Opens Claude's sign-in for it in your browser. Sign in with your work account, then come back here: "
                             "SleePO checks again when you do."}
        return {"label": "Sign in again", "login": w["key"],
                "steps": f"The {name} connector did not answer, so its service may be down. SleePO tries again on every refresh. "
                         "If it keeps failing, sign in to it again."}
    if status == "no-access":
        return {"label": "Open Full Disk Access", "open": "disk", "also": {"label": "Show Python in Finder", "open": "python"},
                "steps": "In System Settings › Privacy & Security › Full Disk Access, press + and add the Python app "
                         "(Show Python in Finder shows it), then restart SleePO."}
    if w["key"] == "apple-mail":
        return {"label": "Open Mail", "open": "mail",
                "steps": "Mail was not running, so the import read nothing new. Open Mail and leave it running; the next sync reads it."}
    if w["key"] == "calendar-app":
        return {"label": "Open Calendar", "open": "calendar",
                "steps": "Calendar.app has not synced your Exchange calendar for over 6 hours. Open it and check the account is online."}
    if w["key"] == "granola-mcp":
        return {"label": "Copy the command", "command": "~/.assist/venv/bin/python -m assist.cli granola-login",
                "steps": "SleePO's own Granola sign-in has lapsed. Run this in Terminal and follow the code it shows."}
    return {"label": "Check again", "check": True, "steps": ""}


HEADLINE = {"needs-auth": "{name} needs you to sign in again", "signed-out": "{name} needs you to sign in again",
            "failed": "{name} is not answering", "no-access": "SleePO cannot read {name}",
            "not-running": "{name} is not running", "not-synced": "{name} has not synced lately"}


def _stream_state(con, sid):
    """The latest real pull of a source (complete or not) and its newest complete pull. The importer's re-reads of the
    calendar file say nothing about whether the source can be reached."""
    q = ("SELECT finished_at, complete FROM pulls WHERE source_id=? AND agent NOT IN ('claude-code (prototype)', 'importer') "
         "ORDER BY finished_at DESC, id DESC LIMIT 1")
    last = con.execute(q, (sid,)).fetchone()
    ok = con.execute("SELECT MAX(finished_at) FROM pulls WHERE source_id=? AND complete=1 AND agent NOT IN "
                     "('claude-code (prototype)', 'importer')", (sid,)).fetchone()[0]
    return last, ok


def issues(con, now=None):
    """Every current problem, worst first. Reads only.
      key, name, status, kind (signin, unreachable, access, app), headline, feeds, since, seen, urgent (show in the header),
      affected: [{id, name, last_ok}] the sources that did not come in because of it, fix: see _fix."""
    now = now or datetime.now(timezone.utc)
    d = load(con)
    known = _by_key()
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM sources")}
    from .source_status import DEFAULT_MAX_AGE, _max_age
    limits = _max_age(con)
    out = []
    for k, it in d["items"].items():
        w, st = known.get(k), it.get("status")
        if not w or st not in BAD:
            continue
        affected = []
        for sid in w["sources"]:
            if sid not in names:
                continue
            last, ok = _stream_state(con, sid)
            # a source whose latest pull failed, or that has gone stale (Salesforce, a month without a pull while its
            # connector failed). One another route still delivers (Outlook mail from Apple Mail) is not affected, and one
            # read only when it changes (the roadmap) is not known to be.
            limit = limits.get(sid, DEFAULT_MAX_AGE)
            stale = limit is not None and ok is not None and (now - _ts(ok)).total_seconds() / 3600 > limit
            if (last is not None and not last["complete"]) or stale:   # a source never pulled is not news
                affected.append({"id": sid, "name": names[sid], "last_ok": ok})
        kind = BAD[st]
        long_enough = now - _ts(it.get("since")) >= UNREACHABLE_GRACE
        out.append({"key": k, "name": w["name"], "status": st, "kind": kind, "headline": HEADLINE.get(st, "{name} has a problem").format(name=w["name"]),
                    "feeds": w["feeds"], "since": it.get("since"), "seen": it.get("seen"), "affected": affected,
                    "urgent": kind != "unreachable" or long_enough, "fix": _fix(w, st, it.get("server"))})
    order = {"signin": 0, "access": 1, "app": 2, "unreachable": 3}
    out.sort(key=lambda x: (order.get(x["kind"], 9), x["name"]))
    return out


def affected_sources(con, now=None):
    """{source_id: issue} for the sources a current problem stopped (source_status marks them), reads only."""
    out = {}
    for i in issues(con, now):
        for a in i["affected"]:
            out.setdefault(a["id"], i)
    return out


def snapshot(con, now=None):
    """GET /api/connections."""
    d = load(con)
    return {"checked": d.get("checked"), "issues": issues(con, now)}


def needs_signin(con, source_ids):
    """The sources among these that a connector waiting for a sign-in feeds (the refresh does not retry them: a retry
    cannot sign in). By the connector alone: these are the sources the run already found missing."""
    known = _by_key()
    blocked = {sid for k, it in load(con)["items"].items() if it.get("status") == "needs-auth" and k in known
               and known[k]["kind"] == "connector" for sid in known[k]["sources"]}
    return [s for s in source_ids if s in blocked]


_URL = re.compile(r"https://[^\s'\"<>]+")


def login(con, key, cwd=None, timeout=30):
    """Sign in to a connector again: `claude mcp login --no-browser "<server>"` prints Claude's authorisation link for a
    claude.ai connector and exits; the link is opened in the browser here. Only a connector SleePO uses, and only an https
    link on claude.ai. Returns {"url": the link or None, "opened": bool, "note": what happened}."""
    w = _by_key().get(key)
    if not w or w["kind"] != "connector":
        raise ValueError("unknown connector")
    server = load(con)["items"].get(key, {}).get("server") or default_server(w)
    try:
        p = subprocess.run([_claude(), "mcp", "login", "--no-browser", server], cwd=str(cwd or db.ASSIST), capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=_env())
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:   # a server that waits for the redirect to be pasted: its link is printed first
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    except OSError as e:
        return {"url": None, "opened": False, "note": f"Claude Code could not be started: {e}"}
    url = next((u for u in _URL.findall(out) if urllib.parse.urlsplit(u).hostname == SIGNIN_HOST), None)
    if not url:
        return {"url": None, "opened": False, "note": (out.strip().splitlines() or ["Claude Code gave no sign-in link"])[-1][:200]}
    subprocess.run(["open", url], check=False)
    return {"url": url, "opened": True, "note": "Opened Claude's sign-in in your browser"}


OPEN_TARGETS = {"mail": ["open", "-a", "Mail"], "calendar": ["open", "-a", "Calendar"]}


def open_target(what):
    """Open one of the fixed targets a fix names. Nothing else."""
    if what in ("disk", "python"):
        from . import onboarding
        return onboarding.open_settings(what)
    if what not in OPEN_TARGETS:
        raise ValueError("unknown target")
    subprocess.run(OPEN_TARGETS[what], check=False)
