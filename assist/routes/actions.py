"""The Actions page (assist/actions_view.py; Sam, 25 Nov 2026): reactive and proactive actions, in place of Today. Reads only:
what the user does on a row goes through that thing's own routes (the Inbox's Needs response, the register, Tasks, Drafts)."""
from fastapi import APIRouter

from ..web import _nocache, con

router = APIRouter()


@router.get("/api/actions")
def api_actions():
    from .. import actions_view
    c = con()
    try:
        return _nocache(actions_view.build(c))
    finally:
        c.close()
