"""Graph memory (assist/graph_memory.py, assist/graph_refresh.py, DESIGN-GRAPH-MEMORY.md; Sam, 17 Nov 2026): what came in since
a record was written ("3 new since this status" on a bet's page and a topic page), whether SleePO has read it and what it
changed, and how many records have new material. Reads only."""
from fastapi import APIRouter, HTTPException

from .. import graph_memory
from ..web import _nocache, con

router = APIRouter()


@router.get("/api/graph-memory/changes/{kind}/{eid}")
def api_graph_changes(kind: str, eid: int):
    if kind not in graph_memory.SHOWN_KINDS:
        raise HTTPException(400, f"unknown kind {kind!r}")
    c = con()
    try:
        return _nocache(graph_memory.since_record(c, kind, eid))
    finally:
        c.close()


@router.get("/api/graph-memory/stale")
def api_graph_stale():
    c = con()
    try:
        from .. import graph_refresh
        return _nocache({**graph_memory.stale(c), "last_run": graph_refresh.state()})
    finally:
        c.close()
