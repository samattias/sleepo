"""Inbox › Drafts (assist/new_mail.py, Sam 26 Oct 2026): Outlook's drafts as Apple Mail holds them, new emails written in
SleePO, replies in progress and the new emails SleePO recommends (task steps). Nothing is ever sent from here."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..web import ASSIST, _nocache, con, json_only

router = APIRouter()


class DraftIn(BaseModel):
    to: list = []
    cc: list = []
    subject: str = ""
    body: str = ""
    ask: str = ""


class DraftEdit(BaseModel):
    to: Optional[list] = None
    cc: Optional[list] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    ask: Optional[str] = None         # what Sam is asking the writer for, kept as he types
    status: Optional[str] = None      # draft (undo a discard) | discarded


class WriteRequest(BaseModel):
    ask: str = ""
    length: Optional[int] = None
    fresh: bool = False               # write a new one, leaving the text there
    base: str = ""                    # the last text SleePO wrote (assist/revise.py: the rest is Sam's own wording)
    history: list = []                # his earlier requests for this email, oldest first


class ChatRequest(BaseModel):
    to: list = []
    cc: list = []
    subject: str = ""
    body: str = ""
    notes: str = ""
    ask: str = ""
    draft: Optional[int] = None       # the SleePO draft it is (one from an initiative's page carries its context)


@router.get("/api/drafts")
def api_drafts():
    from .. import new_mail
    c = con()
    try:
        return _nocache(new_mail.listing(c))
    finally:
        c.close()


@router.post("/api/drafts", dependencies=[Depends(json_only)])
def api_drafts_new(body: DraftIn):
    """A new SleePO draft (New email). Written by the model only when Sam asks (/write)."""
    from .. import new_mail
    c = con()
    try:
        did = new_mail.create(c, body.to, body.cc, body.subject, body.body, body.ask)
        return new_mail.row(c, did)
    finally:
        c.close()


@router.patch("/api/drafts/{did}", dependencies=[Depends(json_only)])
def api_drafts_edit(did: int, body: DraftEdit):
    from .. import new_mail
    c = con()
    try:
        return new_mail.update(c, did, {k: v for k, v in body.model_dump().items() if v is not None})
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/drafts/{did}/write", dependencies=[Depends(json_only)])
def api_drafts_write(did: int, body: WriteRequest):
    """Write the email (or revise the one there with Sam's words as feedback) in the background: a job to poll."""
    from .. import new_mail
    c = con()
    try:
        return {"job": new_mail.start(c, ASSIST, draft=did, ask=body.ask[:4000], length=body.length, fresh=body.fresh,
                                          base=body.base[:12000] or None, history=[str(h)[:600] for h in body.history[-5:]])}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/drafts/step/{step_id}/{index}/write", dependencies=[Depends(json_only)])
def api_drafts_write_step(step_id: int, index: int, body: WriteRequest):
    """Revise a recommended email (an email action on a task step); the result is kept on the step."""
    from .. import new_mail
    c = con()
    try:
        return {"job": new_mail.start(c, ASSIST, step=(step_id, index), ask=body.ask[:4000], length=body.length, fresh=body.fresh,
                                          base=body.base[:12000] or None, history=[str(h)[:600] for h in body.history[-5:]])}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class ExcludeRequest(BaseModel):
    undo: bool = False


@router.post("/api/drafts/step/{step_id}/{index}/exclude", dependencies=[Depends(json_only)])
def api_drafts_exclude(step_id: int, index: int, body: ExcludeRequest):
    """Take a recommended email out of Drafts (undo puts it back); a suggestion with nothing else left is dismissed."""
    from .. import new_mail
    c = con()
    try:
        new_mail.exclude(c, step_id, index, undo=body.undo)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get("/api/drafts/jobs/{jid}")
def api_drafts_job(jid: str):
    from .. import new_mail
    j = new_mail.job(jid)
    if not j:
        raise HTTPException(404, "This writing run is no longer available. Try again.")
    return _nocache(j)


@router.post("/api/drafts/{did}/outlook", dependencies=[Depends(json_only)])
def api_drafts_outlook(did: int):
    """Save the draft into Sam's Outlook Drafts and return its link; on his click only, never sent. 401 until IT approves
    SleePO's Outlook access (the app then opens Outlook on the web's compose page, filled in)."""
    from .. import new_mail, outlook_drafts as od
    c = con()
    try:
        return new_mail.to_outlook(c, did)
    except od.NotSignedIn:
        raise HTTPException(401, "Sign in once so SleePO can save drafts to Outlook: run  ~/.assist/venv/bin/python -m assist.cli outlook-login  in Terminal.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    finally:
        c.close()


@router.post("/api/drafts/chat", dependencies=[Depends(json_only)])
def api_drafts_chat(body: ChatRequest):
    """Continue a new email in Ask SleePO; returns the conversation id."""
    from .. import new_mail
    c = con()
    try:
        return {"thread": new_mail.to_chat(c, body.to, body.cc, body.subject[:250], body.body[:20000], body.notes[:1000], body.ask[:4000], body.draft)}
    finally:
        c.close()


@router.post("/api/drafts/from-outlook/{key}", dependencies=[Depends(json_only)])
def api_drafts_from_outlook(key: str):
    """Take an Outlook draft into SleePO to improve it: {"item_id"} for a reply (its email's composer has it now), else
    {"draft"} (a SleePO copy)."""
    from .. import new_mail
    c = con()
    try:
        return new_mail.from_mail(c, key)
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.post("/api/drafts/resolve", dependencies=[Depends(json_only)])
def api_drafts_resolve(body: dict):
    """Names typed in To or Cc -> addresses ("Gray" -> gray.selby@acme.example); names SleePO cannot place come back in unknown."""
    from .. import new_mail
    names = [str(x)[:200] for x in (body.get("names") or [])][:20]
    c = con()
    try:
        out = new_mail.addresses(c, names)
        return {"addresses": out, "unknown": [x for x in out if not new_mail.ADDR.match(x)]}
    finally:
        c.close()


@router.post("/api/drafts/suggest", dependencies=[Depends(json_only)])
def api_drafts_suggest():
    """Look for new emails Sam should send (one tool-free run, a minute or two); they arrive as task suggestions."""
    from .. import new_mail
    return {"started": new_mail.start_recommend()}
