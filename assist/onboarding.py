"""First-run setup (Sam, 16 Nov 2026: "as a new user that's never used SleePO before ... an onboarding flow that allows them
to set up the app on their computer"). The app's Welcome page (`/welcome`, views/setup.tsx) walks a new user through it; this
module says where the install stands and does the few things the page asks for. It replaces the "Next:" list that
scripts/install.sh used to print.

Steps: who you are (the profile, assist/profile.py), your company (the org pack, assist/org.py), what SleePO can read on this
Mac (checks below), your bets (initiatives), the first import (the quick sync, api.post_refresh) and done.

state() and checks() read only. The writes are the user's own clicks: a Granola key into the Keychain (under this install's
account), an org pack file into the data folder, the initiatives seed and its ingest bundle, and settings 'onboarding_done'.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import db, org, profile

DISK_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
CONNECTORS_URL = "https://claude.ai/settings/connectors"
CLAUDE_URL = "https://claude.com/claude-code"
GRANOLA_API = "https://public-api.granola.ai/v1"
# the two apps SleePO is built around (Sam, 25 Nov 2026: "almost critical alongside SleePO"): strongly recommended, not needed
GRANOLA_APP = "/Applications/Granola.app"
GRANOLA_URL = "https://granola.ai"
FLUIDVOICE_URL = "https://github.com/altic-dev/FluidVoice"


def _installed(app):
    """An app in /Applications or the user's own ~/Applications."""
    return os.path.exists(app) or os.path.exists(os.path.expanduser("~" + app))


def python_app():
    """The app macOS asks Full Disk Access for: the real Python behind the venv (the venv's python is a symlink)."""
    return Path(sys.base_prefix) / "Resources" / "Python.app"


def _keychain(service):
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", db.keychain_account()], capture_output=True, text=True)
    return r.returncode == 0


def _claude():
    exe = os.path.expanduser("~/.local/bin/claude")
    exe = exe if os.path.exists(exe) else shutil.which("claude")
    # Claude Code keeps its sign-in in the login Keychain; its presence is checked, never read
    signed = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials"], capture_output=True).returncode == 0
    return exe, signed


def checks():
    """What SleePO can use on this Mac, each {id, title, why, status: ok|todo|optional, detail}. Granola and FluidVoice are
    marked recommended, with whether the app is installed (app) and where to get it (url). Reads only."""
    out = []
    exe, signed = _claude()
    out.append({"id": "claude", "title": "Claude Code", "required": True,
                "why": "I think with Claude Code on this Mac: reading, drafting, briefs and the chat.",
                "status": "ok" if exe and signed else "todo",
                "detail": ("Installed and signed in." if exe and signed else
                           "Installed, not signed in yet: open Terminal, run claude and sign in." if exe else
                           "Not installed yet.")})
    try:
        from . import applemail
        mail = Path(applemail.index_path()).exists() and os.access(applemail.index_path(), os.R_OK)
    except Exception:
        mail = False
    try:
        from . import applecal
        cc = applecal.connect()
        cc.close()
        cal = True
    except Exception:
        cal = False
    out.append({"id": "disk", "title": "Mail and Calendar on this Mac", "required": False,
                "why": "I read your mail and calendar from Mail.app and Calendar.app, in seconds.",
                "status": "ok" if mail and cal else "todo",
                "detail": ("Mail.app and Calendar.app can be read." if mail and cal else
                           "Calendar can be read; Mail.app cannot yet." if cal else
                           "Mail.app can be read; Calendar.app cannot yet." if mail else
                           "SleePO needs Full Disk Access to read them."),
                "python_app": str(python_app())})
    key, granola = _keychain("granola-api"), _installed(GRANOLA_APP)
    out.append({"id": "granola", "title": "Granola meeting notes", "required": False, "recommended": True, "app": granola,
                "url": GRANOLA_URL,
                "why": "Your meeting notes and transcripts: what was said, decided and promised. Without them I only see that a "
                       "meeting happened.",
                "status": "ok" if key else "todo",
                "detail": ("Connected." if key else "Paste your Granola API key (Granola › Settings › API)." if granola else
                           "Install Granola, then paste its API key here (Granola › Settings › API).")})
    from . import dictation
    fluid, allowed = _installed(dictation.APP), dictation.trusted()
    out.append({"id": "fluidvoice", "title": "FluidVoice dictation", "required": False, "recommended": True, "app": fluid,
                "allowed": allowed, "url": FLUIDVOICE_URL,
                "why": "Talk instead of typing: every box where you tell me what you want has a microphone, and FluidVoice "
                       "types what you say.",
                "status": "ok" if fluid and allowed else "todo",
                "detail": ("Installed, and macOS lets me start it." if fluid and allowed else
                           "Installed. Try the microphone below: the first time, macOS asks to let Python control your computer "
                           "(Accessibility). Allow it, then press Check again." if fluid else
                           "Install FluidVoice (free), open it once to choose its shortcut, then press Check again.")})
    out.append({"id": "connectors", "title": "Teams, Slack and SharePoint", "required": False,
                "why": "Your chats and shared documents, through Claude's Microsoft 365 and Slack connectors.",
                "status": "optional", "detail": "Authorise them in Claude's settings. SleePO cannot check them from here.",
                "url": CONNECTORS_URL})
    return out


def _initiatives(con):
    return [{"slug": r["slug"], "name": r["name"], "weight": r["weight"], "goal": r["goal"] or ""}
            for r in con.execute("SELECT slug, name, weight, goal FROM initiatives WHERE COALESCE(active,1)=1 ORDER BY weight DESC, name")]


def state(con):
    """Where setup stands, for the Welcome page. Reads only."""
    from .routes.profile import suggest
    p = profile.complete(profile.from_db(con))
    o = org.get(con)
    pack = org.pack_path(con)
    me = bool(p["full_name"] and p["emails"])
    return {"needed": not me, "done": bool(db.get_setting(con, "onboarding_done")), "demo": db.DEMO,
            "profile": {k: p[k] for k in ("full_name", "first_name", "emails", "role", "timezone", "signoff")},
            "suggest": suggest(con) if not me else {},
            "org": {"name": o.get("name") or "", "domains": o.get("domains") or [], "pack": pack.exists(), "pack_path": str(pack),
                    "crm": bool(o.get("crm")), "jira": bool(o.get("jira")), "roadmap": bool((o.get("roadmap") or {}).get("file"))},
            "checks": checks(), "initiatives": _initiatives(con),
            "imported": con.execute("SELECT COUNT(*) FROM items").fetchone()[0]}


# ---------------------------------------------------------------- the user's clicks
def save_granola_key(key):
    """Check the key with Granola (one read of a single note's title), then keep it in the Keychain under this install's
    account. A key Granola refuses is not kept."""
    key = (key or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-\.]{16,200}", key):
        raise ValueError("That does not look like a Granola API key.")
    req = urllib.request.Request(f"{GRANOLA_API}/notes?limit=1", headers={"Authorization": f"Bearer {key}"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except urllib.error.HTTPError as e:
        raise ValueError("Granola did not accept that key." if e.code in (401, 403) else f"Granola answered {e.code}; try again.")
    except Exception:
        raise ValueError("Could not reach Granola to check the key; try again.")
    r = subprocess.run(["security", "add-generic-password", "-U", "-s", "granola-api", "-a", db.keychain_account(), "-w", key],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError("The Keychain refused to store it: " + (r.stderr.strip() or "unknown error"))


def save_org_pack(con, data):
    """The company's org pack, as the person who set SleePO up at the company shared it: kept as org/pack.json in the data
    folder (a pack already there is kept as pack.json.bak)."""
    if not isinstance(data, dict) or not (data.get("name") and isinstance(data.get("domains"), list) and data["domains"]):
        raise ValueError("That file is not an org pack: it needs a name and the company's mail domains.")
    dst = db.ASSIST / "org" / "pack.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.copy2(dst, dst.with_suffix(".json.bak"))
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    if db.get_setting(con, "org_pack"):
        db.set_setting(con, "org_pack", None)   # read the data folder's pack
    org._cache.clear()


def _slug(name, taken):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "bet"
    s, n = base, 2
    while s in taken:
        s, n = f"{base}-{n}", n + 1
    taken.add(s)
    return s


def save_initiatives(con, rows):
    """The user's bets: written to the seed (memory/context/initiatives.json) and stored through an ingest bundle, as the
    canonical list is everywhere else. Bets left out of the list are kept (a later edit on the Initiatives page decides)."""
    from . import ingest
    taken = {r["slug"] for r in con.execute("SELECT slug FROM initiatives")}
    have = {r["name"].lower(): r["slug"] for r in con.execute("SELECT slug, name FROM initiatives")}
    defs = []
    for r in rows[:12]:
        name = re.sub(r"\s+", " ", str(r.get("name") or "")).strip()[:80]
        if not name:
            continue
        slug = have.get(name.lower()) or _slug(name, taken)
        try:
            weight = min(max(int(r["weight"] if r.get("weight") is not None else 3), 1), 5)
        except (TypeError, ValueError):
            weight = 3
        defs.append({"slug": slug, "name": name, "weight": weight, "goal": str(r.get("goal") or "").strip()[:240] or None,
                     "owner": None, "v2mom": None, "key_people": [], "themes": [], "regex": None, "files": []})
    if not defs:
        return []
    seed = db.ASSIST / "memory" / "context" / "initiatives.json"
    try:
        d = json.loads(seed.read_text())
    except (OSError, ValueError):
        d = {}
    known = {x.get("slug"): x for x in d.get("initiatives") or []}
    known.update({x["slug"]: x for x in defs})
    d["initiatives"] = list(known.values())
    d.setdefault("folds", [])
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    ingest.ingest_bundle(con, {"agent": "assist:onboarding", "prompt_version": "onboarding-2026-11",
                               "initiatives": [{k: v for k, v in x.items() if k != "files"} for x in defs]})
    con.commit()
    return _initiatives(con)


def open_settings(what):
    """Open System Settings at Full Disk Access, or show the Python app to add there in Finder. Fixed targets only."""
    if what == "disk":
        subprocess.run(["open", DISK_SETTINGS], check=False)
    elif what == "python":
        subprocess.run(["open", "-R", str(python_app())], check=False)
    else:
        raise ValueError("unknown target")


def finish(con):
    if not db.get_setting(con, "onboarding_done"):
        db.set_setting(con, "onboarding_done", db.now())
        con.commit()
