"""System › Personalisation (16 Nov 2026, DESIGN-PERSONALISATION.md): everything that is the user's own, in one place.

GET reads only. PUT saves the profile (settings 'profile'), the followed Slack channels, the day-to-day areas, this
install's org overrides and which org pack it reads. Prompts read the profile when the server starts, so a save says
restart_needed and POST /api/profile/apply restarts the server (after a running refresh). Export and import move it all
between Macs as one JSON file.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, org, profile, soul, tasks
from ..web import _nocache, con, json_only

router = APIRouter()

PAGES = [   # (key, label, path or a function of the profile, where the app shows it)
    ("me", "About you", lambda p: "memory/context/me.md", "/me"),
    ("voice", "Your voice and calendar rules", lambda p: "memory/context/preferences.md", None),
    ("plan", "Your plan", lambda p: p["plan_file"] or "memory/context/plan.md", None),
    ("strategy", "Strategy frame and bets", lambda p: "memory/context/strategy.md", None),
    ("initiatives", "Your initiatives (seed)", lambda p: "memory/context/initiatives.json", "/initiatives"),
    ("role_soul", "Role soul", lambda p: p["role_soul_file"] or "memory/context/role-soul.md", "/soul/cpo"),
    ("company_soul", "Company soul", lambda p: soul.FILES["company"], "/soul"),
    ("assistant_soul", "SleePO's soul", lambda p: soul.FILES["sleepo"], "/soul/sleepo"),
    ("company", "Company overview", lambda p: "memory/context/company.md", None),
]


def _settings_list(c, key, default):
    try:
        v = json.loads(db.get_setting(c, key) or "null")
    except ValueError:
        v = None
    return v if isinstance(v, list) else default


def _pages(p):
    out = []
    for key, label, path, route in PAGES:
        rel = path(p)
        f = db.ASSIST / rel
        out.append({"key": key, "label": label, "path": rel, "exists": f.exists(), "route": route,
                    "updated": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d") if f.exists() else None})
    return out


def _org_summary(c):
    o = org.get(c)
    path = org.pack_path(c)
    chart = o.get("org_chart") or {}
    return {"name": o.get("name") or "", "pack_path": str(path), "pack_exists": path.exists(), "domains": o.get("domains") or [],
            "overrides": org._settings(c), "pack_setting": db.get_setting(c, "org_pack") or "",
            "has": {"org_chart": len(chart.get("tree") or {}), "known_people": len(o.get("known_people") or {}),
                    "products": len(o.get("products") or []), "jira_projects": len((o.get("jira") or {}).get("projects") or []),
                    "crm": bool(o.get("crm")), "roadmap": bool((o.get("roadmap") or {}).get("file")), "kb": bool(o.get("kb")),
                    "noise_senders": len(o.get("noise_senders") or []), "shared_mailboxes": len(o.get("shared_mailboxes") or [])}}


def suggest(c):
    """First-run guesses: the user's address from Calendar.app (its own identity), a name from that address or the person who
    has it, the Mac's time zone, and the org pack whose domains hold the address. Reads only."""
    out = {"timezone": profile.system_timezone()}
    try:
        from .. import applecal
        cc = applecal.connect()
        try:
            cal = applecal.calendar_row(cc)
            email = applecal._me(cc, cal) if cal else ""
        finally:
            cc.close()
    except Exception:
        email = ""
    if email:
        out["emails"] = [email.lower()]
        r = c.execute("SELECT p.name, p.title, p.role FROM people_aliases a JOIN people p ON p.id=a.person_id WHERE a.alias=?", (email.lower(),)).fetchone()
        local = email.split("@")[0]
        out["full_name"] = r["name"] if r else " ".join(w.capitalize() for w in local.replace("_", ".").split(".") if w)
        if r and (r["title"] or r["role"]):
            out["role"] = r["title"] or r["role"]
        dom = email.split("@")[-1].lower()
        out["org_matches"] = dom in [d.lower() for d in org.get(c).get("domains") or []]
    return out


def payload(c):
    stored = {}
    try:
        stored = json.loads(db.get_setting(c, "profile") or "{}")
    except ValueError:
        stored = {}
    p = profile.complete(profile.from_db(c))
    me = c.execute("SELECT id, name FROM people WHERE is_me=1 ORDER BY id LIMIT 1").fetchone()
    out = {"profile": p, "stored": stored, "defaults": profile.DEFAULTS, "me_person": dict(me) if me else None,
           "followed_channels": _settings_list(c, "followed_channels", []),
           "task_areas": tasks.areas(c), "org": _org_summary(c), "pages": _pages(p),
           "needs_setup": not p["full_name"] or not p["emails"]}
    if out["needs_setup"]:
        out["suggest"] = suggest(c)
    return out


@router.get("/api/profile")
def api_profile():
    c = con()
    try:
        return _nocache(payload(c))
    finally:
        c.close()


class ProfileIn(BaseModel):
    fields: Optional[Dict[str, Any]] = None        # profile fields; null removes one (back to its default)
    followed_channels: Optional[List[str]] = None
    task_areas: Optional[List[Dict[str, str]]] = None   # [{key, name, hint}]: the day-to-day areas (tasks.AREAS)
    org: Optional[Dict[str, Any]] = None           # this install's org overrides (name)
    org_pack: Optional[str] = None                 # which pack file to read; "" for the default


def ensure_me(c):
    """A person marked is_me for the profile's name and addresses, when there is none yet (a new install)."""
    if c.execute("SELECT 1 FROM people WHERE is_me=1").fetchone():
        return None
    p = profile.complete(profile.from_db(c))
    if not p["full_name"]:
        return None
    pid = db.get_or_create_person(c, p["full_name"], role=p["role"] or None, aliases=[p["first_name"], *p["emails"], *p["aliases"]])
    c.execute("UPDATE people SET is_me=1 WHERE id=?", (pid,))
    c.commit()
    return pid


def save(c, body):
    if body.fields:
        bad = [k for k in body.fields if k not in profile.DEFAULTS]
        if bad:
            raise HTTPException(400, f"unknown profile fields: {', '.join(bad)}")
        profile.save(c, **{k: (None if v in ("", [], None) else v) for k, v in body.fields.items()})
    if body.followed_channels is not None:
        new = json.dumps([str(x).strip() for x in body.followed_channels if str(x).strip()], ensure_ascii=False)
        if db.get_setting(c, "followed_channels") != new:
            db.set_setting(c, "followed_channels", new)
    if body.task_areas is not None:
        areas = [{"key": str(a.get("key") or "").strip(), "name": str(a.get("name") or "").strip(), "hint": str(a.get("hint") or "").strip()}
                 for a in body.task_areas]
        if any(not a["key"] or not a["name"] for a in areas) or len({a["key"] for a in areas}) != len(areas):
            raise HTTPException(400, "each area needs a unique key and a name")
        if areas != tasks.areas(c):
            db.set_setting(c, "task_areas", None if areas == tasks.AREAS else json.dumps(areas, ensure_ascii=False))
    if body.org is not None:
        org.save(c, **{k: (None if v in ("", None) else v) for k, v in body.org.items()})
    if body.org_pack is not None:
        if body.org_pack and not Path(body.org_pack).expanduser().exists():
            raise HTTPException(400, f"no org pack at {body.org_pack}")
        if (db.get_setting(c, "org_pack") or "") != body.org_pack:
            db.set_setting(c, "org_pack", body.org_pack or None)
        org._cache.clear()
    ensure_me(c)
    profile.reload()


@router.put("/api/profile", dependencies=[Depends(json_only)])
def api_profile_save(body: ProfileIn):
    c = con()
    try:
        save(c, body)
        return {**payload(c), "restart_needed": True}
    finally:
        c.close()


@router.post("/api/profile/apply")
def api_profile_apply():
    """Restart the server so every prompt reads the saved profile; refused while a refresh runs (try again after it)."""
    from .. import api
    if api.STATE.get("running"):
        return {"restarting": False, "reason": "A refresh is running; apply when it ends."}
    db.reload_trigger().write_text(datetime.now().isoformat())
    return {"restarting": True}


@router.get("/api/profile/export")
def api_profile_export():
    """Everything personal in one file: the profile, settings, org overrides and pack path, and the initiatives seed."""
    c = con()
    try:
        seed = db.ASSIST / "memory" / "context" / "initiatives.json"
        data = {"sleepo_profile": 1, "exported": datetime.now().isoformat(timespec="seconds"),
                "profile": json.loads(db.get_setting(c, "profile") or "{}"), "followed_channels": _settings_list(c, "followed_channels", []),
                "task_areas": tasks.areas(c), "org": org._settings(c), "org_pack": db.get_setting(c, "org_pack") or "",
                "initiatives": json.loads(seed.read_text()) if seed.exists() else None}
        r = _nocache(data)
        r.headers["Content-Disposition"] = f'attachment; filename="sleepo-profile-{datetime.now():%Y-%m-%d}.json"'
        return r
    finally:
        c.close()


class ImportIn(BaseModel):
    data: Dict[str, Any]


@router.post("/api/profile/import", dependencies=[Depends(json_only)])
def api_profile_import(body: ImportIn):
    """Load an export: the profile and settings replace this install's; the initiatives seed is written only when none exists."""
    d = body.data
    if d.get("sleepo_profile") != 1:
        raise HTTPException(400, "not a SleePO profile export")
    c = con()
    try:
        fields = {k: v for k, v in (d.get("profile") or {}).items() if k in profile.DEFAULTS}
        save(c, ProfileIn(fields=fields, followed_channels=d.get("followed_channels"), task_areas=d.get("task_areas"),
                          org=d.get("org"), org_pack=d.get("org_pack") if d.get("org_pack") and Path(d["org_pack"]).expanduser().exists() else None))
        seed = db.ASSIST / "memory" / "context" / "initiatives.json"
        wrote_seed = False
        if d.get("initiatives") and not seed.exists():
            seed.parent.mkdir(parents=True, exist_ok=True)
            seed.write_text(json.dumps(d["initiatives"], indent=2, ensure_ascii=False) + "\n")
            wrote_seed = True
        return {**payload(c), "restart_needed": True, "wrote_seed": wrote_seed}
    finally:
        c.close()


# ---------------------------------------------------------------- the account (16 Nov 2026)
# The top bar's account menu and the Account page. An install belongs to one person on their Mac: there is no sign-in
# (Sam, 26 Nov 2026: "Remove also the login functionality because we don't need this for now").


def _avatar(fname):
    """The user's picture as a data URI (the People avatars, as views.py serves them), or ""."""
    import base64
    f = db.db_path().parent / "avatars" / fname if fname else None
    return ("data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()) if f and f.exists() else ""


@router.get("/api/account")
def api_account():
    c = con()
    try:
        p = profile.complete(profile.from_db(c))
        me = c.execute("SELECT id, avatar FROM people WHERE is_me=1 ORDER BY id LIMIT 1").fetchone()
        work = sorted(p["emails"], key=lambda e: (not org.is_primary_address(e), e))
        return _nocache({
            "known": bool(p["full_name"]),
            "user": {"name": p["full_name"], "first_name": p["first_name"], "email": work[0] if work else "", "emails": work,
                     "role": p["role"], "company": org.name(c), "avatar": _avatar(me["avatar"] if me else None),
                     "person_id": me["id"] if me else None},
            "data": {"folder": str(db.ASSIST), "code": str(db.APP), "database": str(db.db_path())}})
    finally:
        c.close()
