"""Things every page uses: the layouts Sam arranges (settings table, key ui:<name>) and dictation into any AI box (moved
from api.py, 22 Oct 2026)."""
import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from ..web import _nocache, con, json_only

router = APIRouter()


# ---------------------------------------------------------------- page layouts Sam arranges in the app (settings table, key ui:<name>)
UI_KEYS = {"today_layout"}   # the Today page's widgets: which ones, in which column and order


@router.get("/api/ui/{key}")
def api_ui_get(key: str):
    if key not in UI_KEYS:
        raise HTTPException(404)
    c = con()
    try:
        r = c.execute("SELECT value FROM settings WHERE key=?", (f"ui:{key}",)).fetchone()
        return _nocache({"value": json.loads(r["value"]) if r else None})
    finally:
        c.close()


@router.put("/api/ui/{key}", dependencies=[Depends(json_only)])
async def api_ui_put(key: str, request: Request):
    if key not in UI_KEYS:
        raise HTTPException(404)
    value = json.dumps((await request.json()).get("value"))
    if len(value) > 20000:
        raise HTTPException(413, "Layout too large")
    c = con()
    try:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"ui:{key}", value))
        c.commit()
        return {"ok": True}
    finally:
        c.close()
# ---------------------------------------------------------------- dictation with FluidVoice (assist/dictation.py)
@router.get("/api/dictate")
def api_dictate_status():
    """Whether the microphone buttons can start FluidVoice: installed, running, its shortcut, and Accessibility for this server."""
    from .. import dictation
    return _nocache({"app": os.path.exists(dictation.APP), "running": dictation.running(), "trusted": dictation.trusted(),
                     "shortcut": dictation.describe(dictation.shortcut())})


@router.post("/api/dictate", dependencies=[Depends(json_only)])
async def api_dictate(request: Request):
    """Press FluidVoice's shortcut once (start or stop dictating into the box the page just focused). Never types anything."""
    from .. import dictation
    return await asyncio.to_thread(dictation.press)
