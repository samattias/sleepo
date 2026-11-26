"""Connection problems (assist/connections.py; Sam, 17 Nov 2026): what SleePO cannot reach and what to do about it. The
Refresh button's dot and menu and the Sources page read GET /api/connections (reads only). Check again and the fix
buttons (Sign in, open System Settings or an app) are Sam's clicks."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import connections, db
from ..web import _nocache, con, json_only

router = APIRouter()


@router.get("/api/connections")
def api_connections():
    c = con()
    try:
        return _nocache(connections.snapshot(c))
    finally:
        c.close()


@router.post("/api/connections/check", dependencies=[Depends(json_only)])
def api_connections_check():
    """Check again: start Claude only to read which connectors are signed in (about 5 s), record it, return the new state."""
    found = connections.check("check", db.ASSIST)
    c = con()
    try:
        out = connections.snapshot(c)
    finally:
        c.close()
    out["checked_now"] = found is not None
    return _nocache(out)


class LoginIn(BaseModel):
    key: str


@router.post("/api/connections/login", dependencies=[Depends(json_only)])
def api_connections_login(body: LoginIn):
    """Sign in to a connector again: Claude Code's sign-in link for it, opened in the browser (connections.login)."""
    c = con()
    try:
        return connections.login(c, body.key, db.ASSIST)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class OpenIn(BaseModel):
    what: str


@router.post("/api/connections/open", dependencies=[Depends(json_only)])
def api_connections_open(body: OpenIn):
    """Open a fixed target a fix names (System Settings at Full Disk Access, Python in Finder, Mail, Calendar)."""
    try:
        connections.open_target(body.what)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}
