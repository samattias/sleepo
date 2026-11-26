"""First-run setup and the demo copy (16 Nov 2026): the Welcome page (views/setup.tsx, assist/onboarding.py) and the Account
page's "Try setup as a new user" (assist/demo.py).

GETs read only. The POSTs are the user's clicks on those pages.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, demo, onboard_agent, onboarding
from ..web import _nocache, con, json_only

router = APIRouter()


@router.get("/api/setup")
def api_setup():
    c = con()
    try:
        return _nocache(onboarding.state(c))
    finally:
        c.close()


class KeyIn(BaseModel):
    key: str


@router.post("/api/setup/granola-key", dependencies=[Depends(json_only)])
def api_setup_granola(body: KeyIn):
    try:
        onboarding.save_granola_key(body.key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "checks": onboarding.checks()}


class PackIn(BaseModel):
    data: Dict[str, Any]


@router.post("/api/setup/org-pack", dependencies=[Depends(json_only)])
def api_setup_pack(body: PackIn):
    c = con()
    try:
        onboarding.save_org_pack(c, body.data)
        return _nocache(onboarding.state(c))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class BetsIn(BaseModel):
    rows: List[Dict[str, Any]]


@router.post("/api/setup/initiatives", dependencies=[Depends(json_only)])
def api_setup_bets(body: BetsIn):
    c = con()
    try:
        return {"initiatives": onboarding.save_initiatives(c, body.rows)}
    finally:
        c.close()


class OpenIn(BaseModel):
    what: str


@router.post("/api/setup/open", dependencies=[Depends(json_only)])
def api_setup_open(body: OpenIn):
    try:
        onboarding.open_settings(body.what)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class FinishIn(BaseModel):
    restart: Optional[bool] = True


@router.post("/api/setup/finish", dependencies=[Depends(json_only)])
def api_setup_finish(body: FinishIn):
    """Setup is done: never shown again by itself. The server restarts so every prompt reads the new profile (not while a
    refresh runs: it then restarts at the next Apply or restart)."""
    from datetime import datetime
    from .. import api
    c = con()
    try:
        onboarding.finish(c)
    finally:
        c.close()
    restarting = bool(body.restart) and not api.STATE.get("running")
    if restarting:
        db.reload_trigger().write_text(datetime.now().isoformat())
    return {"ok": True, "restarting": restarting}


# ---------------------------------------------------------------- the onboarding agent (assist/onboard_agent.py)
@router.get("/api/setup/scan")
def api_setup_scan():
    return _nocache(onboard_agent.view())


class ScanIn(BaseModel):
    chat: Optional[bool] = False   # also pull Teams and Slack through Claude's connectors


@router.post("/api/setup/scan", dependencies=[Depends(json_only)])
def api_setup_scan_start(body: ScanIn):
    """Start the agent: keep Calendar.app's address as the user's when the profile has none, then import, read and think in
    its own process. One at a time; not during a full refresh."""
    from .. import api
    if api.STATE.get("running") and api.STATE.get("mode") == "full":
        raise HTTPException(409, "A full refresh is running; start when it ends.")
    c = con()
    try:
        onboard_agent.provisional_identity(c)
    finally:
        c.close()
    onboard_agent.start(bool(body.chat))
    return _nocache(onboard_agent.view())


class ApplyIn(BaseModel):
    draft: Dict[str, Any]


@router.post("/api/setup/apply", dependencies=[Depends(json_only)])
def api_setup_apply(body: ApplyIn):
    """Save what the user confirmed on the review (the profile, company, bets, About me and voice pages)."""
    c = con()
    try:
        onboard_agent.apply(c, body.draft)
        return _nocache(onboarding.state(c))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- the demo copy
@router.get("/api/demo")
def api_demo():
    return _nocache({**demo.status(), "this_is_demo": db.DEMO})


@router.post("/api/demo/{action}")
def api_demo_action(action: str):
    """Start, stop or reset the demo copy, detached (a reset from inside the demo stops this very server)."""
    if action not in ("start", "stop", "reset"):
        raise HTTPException(404, "unknown action")
    if action == "start" and db.DEMO:
        raise HTTPException(400, "This is the demo copy already.")
    demo.spawn(action)
    return {"ok": True, "action": action}
