"""Knowledge › Product › Code base (assist/codebase.py; Sam, 20 Nov 2026): the company's source code from the git clones on
this Mac, for the assistant to read when the docs do not say how the product behaves. The GETs run git on the clones and
write nothing; Update fetches the default branch into each clone's remote-tracking ref; Add / Remove change one settings row."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import codebase
from ..web import _nocache, con

router = APIRouter()


@router.get("/api/code")
def api_code():
    c = con()
    try:
        return _nocache(codebase.overview(c) | {"running": codebase.running()})
    finally:
        c.close()


@router.get("/api/code/search")
def api_code_search(q: str, repo: Optional[str] = None, path: Optional[str] = None):
    c = con()
    try:
        return _nocache(codebase.search(q[:300], repo or None, (path or "")[:200] or None, con=c))
    finally:
        c.close()


@router.get("/api/code/file")
def api_code_file(repo: str, path: str, start: int = 1, end: Optional[int] = None):
    c = con()
    try:
        d = codebase.read(repo, path, start, end, con=c)
    finally:
        c.close()
    if d.get("error"):
        raise HTTPException(404, d["error"])
    return _nocache(d)


class UpdateRequest(BaseModel):
    repo: Optional[str] = None


@router.get("/api/code/update")
def api_code_update_state():
    return _nocache(codebase.state() | {"running": codebase.running()})


@router.post("/api/code/update")
def api_code_update(body: UpdateRequest):
    return _nocache(codebase.start(body.repo))


class ReposRequest(BaseModel):
    add: Optional[str] = None
    hide: Optional[str] = None
    show: Optional[str] = None


@router.post("/api/code/repos")
def api_code_repos(body: ReposRequest):
    c = con()
    try:
        try:
            codebase.save_settings(c, add=body.add, hide=body.hide, show=body.show)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _nocache(codebase.overview(c) | {"running": codebase.running()})
    finally:
        c.close()
