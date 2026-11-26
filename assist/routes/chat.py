"""Ask SleePO, the in-app chat (assist/chat.py), and opening work in Claude Desktop or Cowork (moved from api.py, 22 Oct
2026)."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..web import _nocache, con, json_only

router = APIRouter()


class ClaudeOpen(BaseModel):
    prompt: str
    app: str = "cowork"          # cowork | chat
    doc: Optional[str] = None    # a document id from /api/documents (lf-, ma-, sp-, kb-, ca-)
    label: str = ""              # workspace folder label, e.g. the meeting


# ---------------------------------------------------------------- Ask SleePO (in-app chat, read-only; assist/chat.py)
class ChatRequest(BaseModel):
    message: str
    thread: Optional[str] = None      # saved conversation to continue (its Claude Code session is resumed)
    page: Optional[dict] = None       # {path, title, context?: {kind, ref}}: what the user is looking at; context = the chip a new chat starts with


@router.post("/api/chat", dependencies=[Depends(json_only)])
def api_chat(body: ChatRequest, request: Request):
    """Ask one question: {thread, job} at once; the answer runs on its own (chat.start) and the page follows it with
    GET /api/chat/live/{job}. 429 while that conversation is still answering, or when MAX_LIVE answers already run."""
    if not body.message.strip():
        raise HTTPException(400, "empty message")
    from .. import chat
    try:
        return _nocache(chat.start(body.message.strip()[:8000], body.thread, body.page))
    except ValueError as e:
        raise HTTPException(429, str(e))


# Polled every few hundred milliseconds while an answer is on screen: async and in memory, so following answers takes no
# request thread and holds no connection open (chat.py: answers that run on their own).
@router.get("/api/chat/live")
async def api_chat_live():
    from .. import chat
    return _nocache({"jobs": chat.live_jobs()})


@router.get("/api/chat/live/{job}")
async def api_chat_live_events(job: str, after: int = 0):
    from .. import chat
    d = chat.live_events(job, after)
    if d is None:
        raise HTTPException(404, "That answer is no longer running.")
    return _nocache(d)


@router.post("/api/chat/live/{job}/stop")
def api_chat_live_stop(job: str):
    from .. import chat
    return {"stopped": chat.stop_job(job)}


@router.get("/api/chat/page-context")
def api_chat_page_context(path: str = ""):
    """What the user is looking at (assist/page_context.py): the chip a new chat starts with, or null. Reads only."""
    from .. import page_context
    c = con()
    try:
        return _nocache({"context": page_context.resolve(c, path)})
    finally:
        c.close()


@router.get("/api/chat/context")
def api_chat_context(kind: str = "", ref: str = ""):
    """The chip for one thing a page names by kind and id (page_context.chip): what an assistant pill passes to a new chat
    (components/AssistContext.tsx), or null when SleePO holds no such thing. Reads only."""
    from .. import page_context
    c = con()
    try:
        return _nocache({"context": page_context.chip(c, kind, ref)})
    finally:
        c.close()


@router.get("/api/chat/context/preview")
def api_chat_context_preview(kind: str = "", ref: str = ""):
    """What hovering a chip shows: the thing as it is now, in a few lines (assist/chip_preview.py), or null when SleePO no
    longer holds it. Reads only."""
    from .. import chip_preview
    c = con()
    try:
        return _nocache({"preview": chip_preview.preview(c, kind, ref)})
    finally:
        c.close()


@router.get("/api/chat/threads")
def api_chat_threads():
    from .. import chat
    return _nocache(chat.threads())


@router.get("/api/chat/suggestions")
def api_chat_suggestions():
    """Suggested questions for the chat's welcome screen, with live counts (assist/suggest.py)."""
    from .. import suggest
    c = con()
    try:
        return _nocache(suggest.build(c))
    finally:
        c.close()


@router.get("/api/chat/threads/{tid}")
def api_chat_thread(tid: str):
    from .. import chat
    t = chat.thread(tid)
    if not t:
        raise HTTPException(404)
    return _nocache(t)


@router.delete("/api/chat/threads/{tid}")
def api_chat_delete(tid: str):
    from .. import chat
    return {"deleted": chat.delete(tid)}


class ChatHandoff(BaseModel):
    ask: str = ""       # what Sam wants Claude Desktop to do with the conversation (optional)


@router.post("/api/chat/threads/{tid}/handoff", dependencies=[Depends(json_only)])
def api_chat_handoff(tid: str, body: ChatHandoff, request: Request):
    """Continue a conversation in Claude Desktop (Cowork) with the transcript and the cited sources as files. Only on Sam's click."""
    from .. import chat
    try:
        return chat.handoff(tid, body.ask[:4000])
    except ValueError as e:
        raise HTTPException(404, str(e))


class ChatDraft(BaseModel):
    key: str                          # "<turn>:<n>": the answer's place in the conversation, the email's place in the answer
    mail: Optional[int] = None        # the email it replies to, for a reply
    to: str = ""
    cc: str = ""
    subject: str = ""
    body: str = ""
    kind: Optional[str] = None        # "teams" or "slack": a chat reply (```teams <item id>), not an email
    item: Optional[int] = None        # the Teams or Slack message it answers


@router.post("/api/chat/threads/{tid}/drafts", dependencies=[Depends(json_only)])
def api_chat_draft(tid: str, body: ChatDraft):
    """Sam's version of an email the chat wrote, kept with the conversation as he edits it (assist/chat.py save_draft)."""
    from .. import chat
    try:
        return chat.save_draft(tid, body.key, body.dict())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))


class ChatDraftOutlook(BaseModel):
    key: str
    to: list = []
    cc: list = []
    subject: str = ""
    body: str = ""


@router.post("/api/chat/threads/{tid}/drafts/outlook", dependencies=[Depends(json_only)])
def api_chat_draft_outlook(tid: str, body: ChatDraftOutlook):
    """A new email from the chat as a draft in Sam's Outlook Drafts (outlook_drafts.save_new); saving again updates the same
    draft. On Sam's click only; never sends. 401 until he has signed in with `assist.cli outlook-login`."""
    from .. import chat, outlook_drafts as od
    if not chat.DRAFT_KEY.fullmatch(body.key or ""):
        raise HTTPException(400, "Which email is this?")
    prev = chat.drafts(tid).get(body.key, {})
    c = con()
    try:
        r = od.save_new(c, [str(x)[:200] for x in body.to[:30]], [str(x)[:200] for x in body.cc[:30]], body.subject[:300], body.body[:20000],
                        draft_id=prev.get("outlook_id"))
    except od.NotSignedIn:
        raise HTTPException(401, "Sign in once so SleePO can save drafts to Outlook: run  ~/.assist/venv/bin/python -m assist.cli outlook-login  in Terminal.")
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    finally:
        c.close()
    chat.save_draft(tid, body.key, {"outlook_id": r.get("id"), "outlook_link": r.get("web_link"), "edited": False})
    return r


class ChatFileOpen(BaseModel):
    name: str
    reveal: bool = False


@router.post("/api/chat/threads/{tid}/files/open", dependencies=[Depends(json_only)])
def api_chat_file_open(tid: str, body: ChatFileOpen, request: Request):
    """Open a file the chat made in its conversation folder, or show it in Finder. Only on Sam's click."""
    from .. import chat
    try:
        return chat.open_file(tid, body.name, body.reveal)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- steps on the Mac the chat asked to do (assist/desktop.py)
class DesktopDecide(BaseModel):
    approve: bool
    steps: Optional[List[int]] = None   # the steps left ticked (all when absent)


class DesktopShow(BaseModel):
    step: int
    n: int = 0


@router.get("/api/chat/threads/{tid}/desktop")
def api_chat_desktop(tid: str):
    """A conversation's ask-do requests: their steps, the user's answer and each step's outcome. Reads only."""
    from .. import desktop
    return _nocache({"requests": desktop.for_thread(tid)})


@router.post("/api/chat/desktop/{rid}/decide", dependencies=[Depends(json_only)])
def api_chat_desktop_decide(rid: str, body: DesktopDecide):
    """The user's answer from the card: allow the steps left ticked, or decline. Only the app calls this (the chat cannot
    make a request to the server); the waiting command carries the steps out."""
    from .. import desktop
    try:
        return desktop.decide(rid, body.approve, body.steps)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/api/chat/desktop/{rid}/show", dependencies=[Depends(json_only)])
def api_chat_desktop_show(rid: str, body: DesktopShow):
    """Show a step's result in Finder, on the user's click (changes nothing)."""
    from .. import desktop
    try:
        return desktop.show(rid, body.step, body.n)
    except (LookupError, ValueError) as e:
        raise HTTPException(404, str(e))


@router.post("/api/chat/stop/{run_id}")
def api_chat_stop(run_id: str):
    from .. import chat
    return {"stopped": chat.stop(run_id)}


@router.post("/api/claude/open", dependencies=[Depends(json_only)])
def api_claude_open(body: ClaudeOpen, request: Request):
    """Open a brief's action in the Claude desktop app. JSON only (forces a CORS preflight from other origins)."""
    if body.app not in ("cowork", "chat") or not body.prompt.strip():
        raise HTTPException(400)
    from .. import claude_open
    c = con()
    try:
        return claude_open.open_in_claude(c, body.prompt, body.app, body.doc, body.label)
    finally:
        c.close()
