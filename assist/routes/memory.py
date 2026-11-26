"""What SleePO remembers (assist/remember.py; Sam, 28 Oct 2026): System › Memory lists, edits, keeps, deletes (with Undo)
and adds memories; Learn now reads what Sam said since the last run. Sam's edits are final."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import remember
from ..web import _nocache, con, json_only

router = APIRouter()


class MemoryIn(BaseModel):
    text: Optional[str] = None
    kind: Optional[str] = None
    scope: Optional[List[str]] = None
    people: Optional[List[int]] = None


@router.get("/api/memory")
def api_memory():
    c = con()
    try:
        out = remember.listing(c, include_deleted=True)
        out["learning"] = remember.learning()
        return _nocache(out)
    finally:
        c.close()


@router.post("/api/memory", dependencies=[Depends(json_only)])
def api_memory_add(body: MemoryIn):
    c = con()
    try:
        return {"id": remember.add(c, body.text or "", body.kind or "preference", body.people or (), body.scope or ("all",))}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/memory/learn")
def api_memory_learn():
    """Learn now from what Sam said since the last run, in the background (one tool-free run)."""
    from ..db import ASSIST
    return {"started": remember.spawn_learn(ASSIST)}


@router.post("/api/memory/{mid}", dependencies=[Depends(json_only)])
def api_memory_update(mid: int, body: MemoryIn):
    c = con()
    try:
        return {"changed": remember.update(c, mid, body.dict(exclude_none=True))}
    except KeyError:
        raise HTTPException(404, "No such memory.")
    finally:
        c.close()


@router.post("/api/memory/{mid}/{op}")
def api_memory_op(mid: int, op: str):
    if op not in ("keep", "delete", "restore"):
        raise HTTPException(404, "Unknown action.")
    c = con()
    try:
        getattr(remember, op)(c, mid)
        return {"ok": True}
    except KeyError:
        raise HTTPException(404, "No such memory.")
    finally:
        c.close()
