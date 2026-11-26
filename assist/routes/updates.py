"""Check for updates and Update now (assist/updates.py; Sam, 26 Nov 2026): the account menu under the user's picture and the
Account page. The GET reads the last check and may start the daily one in the background (it writes only a job file, never the
database); Check asks GitHub now; Update starts `assist.cli update` detached, only on the user's click."""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from .. import updates
from ..web import _nocache, con

router = APIRouter()


@router.get("/api/updates")
def api_updates():
    c = con()
    try:
        updates.check_soon(c)
        return _nocache(updates.status(c))
    finally:
        c.close()


@router.post("/api/updates/check")
def api_updates_check():
    updates.check(force=True)
    c = con()
    try:
        return _nocache(updates.status(c))
    finally:
        c.close()


class InstallRequest(BaseModel):
    tag: Optional[str] = None


@router.post("/api/updates/install")
def api_updates_install(body: InstallRequest):
    res = updates.start(body.tag if body.tag and updates.parse(body.tag) else None)
    c = con()
    try:
        return _nocache(updates.status(c) | res)
    finally:
        c.close()
