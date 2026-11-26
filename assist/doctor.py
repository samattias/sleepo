"""assist doctor: is this install ready, and what to do about each gap (16 Nov 2026, DESIGN-PERSONALISATION.md phase 6).

Reads only: it never creates, changes or sends anything. Each check is (status, what, how to fix): ok, warn (works, but
something is missing) or fail (SleePO cannot do its job until it is fixed).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import db, org, profile, soul

PAGES = ["memory/context/me.md", "memory/context/preferences.md", soul.FILES["company"], soul.FILES["sleepo"]]


def _keychain(service):
    """True when a Keychain item exists for SleePO's account (its secret is not read)."""
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", db.keychain_account()], capture_output=True, text=True)
    return r.returncode == 0


def checks():
    out = []
    add = lambda status, what, fix="": out.append((status, what, fix))   # noqa: E731

    v = sys.version_info
    add("ok" if v >= (3, 9) else "fail", f"Python {v.major}.{v.minor} at {sys.executable}", "" if v >= (3, 9) else "Python 3.9 or later is needed.")
    venv = Path.home() / ".assist" / "venv" / "bin" / "python"
    add("ok" if venv.exists() else "fail", f"Environment {venv}", "" if venv.exists() else "Run scripts/install.sh.")

    same = db.ASSIST == db.APP
    add("ok", f"Code {db.APP}" + ("" if same else f"; data {db.ASSIST}"))
    if not db.ASSIST.exists():
        add("fail", f"Data folder {db.ASSIST} is missing", "Run scripts/install.sh, or fix ~/.assist/home.")
    missing = [p for p in PAGES if not (db.ASSIST / p).exists()]
    add("warn" if missing else "ok", "Context pages" + (f": missing {', '.join(missing)}" if missing else " in memory/context"),
        "Copy them from templates/data/memory/context in the app and fill them in." if missing else "")
    skills = db.ASSIST / ".claude" / "skills"
    n = len(list(skills.glob("*/SKILL.md"))) if skills.exists() else 0
    add("ok" if n else "fail", f"Skills: {n} in {skills}", "" if n else "Copy .claude/skills from the app into the data folder.")
    add("ok" if (db.ASSIST / "CLAUDE.md").exists() else "warn", "Working memory CLAUDE.md in the data folder",
        "" if (db.ASSIST / "CLAUDE.md").exists() else "Copy templates/data/CLAUDE.md from the app.")

    dbp = db.db_path()
    c = profile.read_only(dbp)
    if c is None:
        add("fail", f"Database {dbp} does not exist", "Run: ~/.assist/venv/bin/python -m assist.cli migrate")
    else:
        try:
            ver = c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            add("ok", f"Database {dbp} (schema {ver})")
            p = profile.complete(profile.from_db(c))
            me = c.execute("SELECT name FROM people WHERE is_me=1").fetchone()
            if p["full_name"] and p["emails"]:
                add("ok", f"Profile: {p['full_name']} <{', '.join(p['emails'][:2])}>, {p['role'] or 'no role'}, {p['timezone']}")
            else:
                add("fail", "Profile: SleePO does not know who you are", "Fill in System › Personalisation (http://localhost:8765/#/settings).")
            add("ok" if me else "warn", f"Your person record: {me[0] if me else 'none'}", "" if me else "Saving the profile creates it.")
            pack = org.pack_path(c)
            o = org.get(c)
            add("ok" if pack.exists() else "warn", f"Org pack {pack}" + (f" ({o.get('name')})" if o.get("name") else ""),
                "" if pack.exists() else "Ask your company's SleePO owner for the org pack, or copy templates/org/example.json and fill it in.")
        except sqlite3.Error as e:
            add("fail", f"Database {dbp} cannot be read: {e}", "Run: ~/.assist/venv/bin/python -m assist.cli migrate")
        finally:
            c.close()

    claude = os.path.expanduser("~/.local/bin/claude")
    found = claude if os.path.exists(claude) else shutil.which("claude")
    add("ok" if found else "fail", f"Claude Code CLI: {found or 'not found'}", "" if found else "Install Claude Code (https://claude.com/claude-code) and sign in.")

    try:
        from . import applemail
        ok = Path(applemail.index_path()).exists() and os.access(applemail.index_path(), os.R_OK)
    except Exception:
        ok = False
    add("ok" if ok else "warn", "Mail.app's store readable (Full Disk Access)",
        "" if ok else f"System Settings › Privacy & Security › Full Disk Access: add {Path(sys.base_prefix) / 'Resources' / 'Python.app'}; mail then comes from the Microsoft 365 connector instead.")
    try:
        from . import applecal
        cc = applecal.connect()
        cc.close()
        ok = True
    except Exception:
        ok = False
    add("ok" if ok else "warn", "Calendar.app's store readable (Full Disk Access)", "" if ok else "Same Full Disk Access as Mail; otherwise the calendar comes from the connector.")

    # the two apps SleePO is built around (Sam, 25 Nov 2026: "almost critical alongside SleePO"): it runs without them
    from . import dictation
    for name, apps, why, link in (("Granola", ["/Applications/Granola.app"], "meeting notes and transcripts", "https://granola.ai"),
                                  ("FluidVoice", [dictation.APP], "dictation into SleePO's boxes", "https://github.com/altic-dev/FluidVoice")):
        has = any(os.path.exists(a) or os.path.exists(os.path.expanduser("~" + a)) for a in apps)
        add("ok" if has else "warn", f"{name}, recommended ({why}): {'installed' if has else 'not in Applications'}",
            "" if has else f"Install it from {link}.")

    for service, what, fix in (("granola-api", "Granola API key", "security add-generic-password -s granola-api -a %s -w <your Granola API key>"),
                               ("granola-mcp", "Granola sign-in for screenshots and the live call", "~/.assist/venv/bin/python -m assist.cli granola-login"),
                               ("assist-graph", "Microsoft Graph sign-in (optional)", "~/.assist/venv/bin/python -m assist.cli mail-login")):
        has = _keychain(service)
        add("ok" if has else "warn", f"{what} (Keychain {service}, account {db.keychain_account()})", "" if has else fix.replace("%s", db.keychain_account()))

    from . import web
    ok = (web.WEB_DIST / "index.html").exists()
    add("ok" if ok else "fail", f"App pages {web.WEB_DIST}", "" if ok else "Build the front end (assist-web: pnpm build) or set ASSIST_WEB_DIST.")
    try:
        running = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/status", timeout=3).read()) is not None
    except Exception:
        running = False
    add("ok" if running else "warn", "Server at http://localhost:8765", "" if running else "Open SleePO.command in the data folder, or: ~/.assist/venv/bin/python -m assist.cli serve")
    return out


def main():
    marks = {"ok": "✓", "warn": "!", "fail": "✗"}
    res = checks()
    for status, what, fix in res:
        print(f" {marks[status]} {what}")
        if fix:
            print(f"     → {fix}")
    bad = sum(1 for s, _, _ in res if s == "fail")
    print(f"\n{len(res)} checks: {sum(1 for s, _, _ in res if s == 'ok')} ok, {sum(1 for s, _, _ in res if s == 'warn')} to look at, {bad} blocking")
    return 1 if bad else 0
