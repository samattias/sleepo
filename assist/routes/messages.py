"""The Messages page: Teams and Slack conversations and drafting a reply in one (moved from api.py, 22 Oct 2026)."""
import json

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..web import ASSIST, _nocache, con, json_only

router = APIRouter()


class ChatDraftRequest(BaseModel):
    ids: list = []
    app: str = "teams"
    person: Optional[str] = None
    instructions: str = ""
    length: Optional[int] = None


@router.post("/api/messages/draft", dependencies=[Depends(json_only)])
def api_messages_draft(body: ChatDraftRequest, request: Request):
    """Draft a Teams or Slack reply in Sam's chat voice (assist/chat_reply.py) from the conversation the Messages page shows.
    Returns a job to poll at /api/replies/jobs/{id}. Nothing is sent."""
    from .. import chat_reply
    ids = [int(x) for x in body.ids[:200] if str(x).isdigit()]
    if body.app not in chat_reply.APPS or not ids:
        raise HTTPException(400, "ids and app (teams or slack) are needed")
    c = con()
    try:
        return {"job": chat_reply.start(c, ids, body.app, body.instructions[:4000], ASSIST, body.person,
                                        body.length if body.length in (1, 2, 3, 4, 5) else None)}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.get("/api/messages/recent")
def api_messages_recent(days: int = 7):
    """The latest conversations Sam reads, each with its newest message in a line (Today's Messages widget,
    chatsync.latest). Reads only. Declared before /api/messages/{item_id}."""
    from .. import chatsync
    c = con()
    try:
        return _nocache({"conversations": chatsync.latest(c, max(1, min(days, 30)))})
    finally:
        c.close()


@router.get("/api/chat")
def api_chat(source: str = None, limit: int = 5000):
    """Full message text, links and attachment metadata for Teams/Slack items that have them (last 30 days by policy)."""
    c = con()
    try:
        where = "WHERE m.source_id=?" if source else ""
        rows = c.execute("SELECT m.item_id, m.body_text, m.links_json, m.conversation_name, m.conversation_kind, m.author, m.sent_at FROM chat_messages m "
                         f"{where} ORDER BY m.sent_at DESC LIMIT ?", ([source] if source else []) + [limit]).fetchall()
        from .. import links
        att, h = {}, links.held(c)
        for a in c.execute("SELECT id, item_id, name, content_type, size, url FROM chat_attachments"):
            att.setdefault(a["item_id"], []).append({"id": a["id"], "name": a["name"], "content_type": a["content_type"], "size": a["size"], "url": a["url"],
                                                     "read": links.is_held(h, a["url"])})   # SleePO holds its text
        from .. import file_review   # a file reviewed in its conversation shows folded there (components/InlineReview.tsx)
        done = file_review.summaries([a["id"] for xs in att.values() for a in xs])
        for xs in att.values():
            for a in xs:
                a["review"] = done.get(a["id"])
        return {str(r["item_id"]): {"body": r["body_text"], "links": json.loads(r["links_json"] or "[]"), "attachments": att.get(r["item_id"], []),
                                    "sent_at": r["sent_at"]} for r in rows}
    finally:
        c.close()


# ---- reviewing a file shared in a conversation (assist/file_review.py; Sam, 29 Oct 2026). Nothing is sent.
class ReviewStart(BaseModel):
    ask: str = ""


class ReviewDecide(BaseModel):
    decisions: dict = {}
    replace: dict = {}


class ReviewFile(BaseModel):
    name: str
    data: str   # base64


@router.get("/api/reviews/jobs/{jid}")
def api_review_job(jid: str):
    from .. import file_review
    j = file_review.job(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    return j


@router.get("/api/reviews/{att_id}")
def api_review(att_id: int):
    """The file, where SleePO has its copy, and the latest review (or none)."""
    from .. import file_review
    c = con()
    try:
        st = file_review.state(c, att_id)
    finally:
        c.close()
    if not st:
        raise HTTPException(404, "No such file.")
    return st


@router.post("/api/reviews/{att_id}", dependencies=[Depends(json_only)])
def api_review_start(att_id: int, body: ReviewStart):
    from .. import file_review
    c = con()
    try:
        return {"job": file_review.start(c, att_id, body.ask[:4000])}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.patch("/api/reviews/{att_id}", dependencies=[Depends(json_only)])
def api_review_decide(att_id: int, body: ReviewDecide):
    """Sam ticks the edits to make and can change their new text."""
    from .. import file_review
    try:
        return file_review.decide(att_id, body.decisions, body.replace)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/api/reviews/{att_id}/file", dependencies=[Depends(json_only)])
def api_review_file(att_id: int, body: ReviewFile):
    """The file itself, when it is not in Downloads: kept in the review's workspace folder (outside OneDrive)."""
    import base64
    from .. import file_review
    try:
        data = base64.b64decode(body.data, validate=True)
        file_review.add_copy(att_id, body.name, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/api/reviews/{att_id}/make")
def api_review_make(att_id: int):
    """Make the updated copy with the ticked edits."""
    from .. import file_review
    c = con()
    try:
        return file_review.make_file(c, att_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    finally:
        c.close()


@router.post("/api/reviews/{att_id}/open")
def api_review_open(att_id: int, reveal: int = 0):
    """Open the updated copy, or show it in Finder (only the file this review made)."""
    import subprocess
    from pathlib import Path
    from .. import file_review
    rec = file_review.latest(att_id)
    p = Path(((rec or {}).get("output") or {}).get("path") or "")
    if not rec or not p.name or not p.is_file():
        raise HTTPException(404, "Make the updated file first.")
    subprocess.run(["open", "-R", str(p)] if reveal else ["open", str(p)], check=False, timeout=15)
    return {"ok": True}


@router.get("/api/reviews/{att_id}/reply")
def api_review_reply(att_id: int):
    """What the Messages writer is told for the reply (the review's points, and the updated file when there is one)."""
    from .. import file_review
    rec = file_review.latest(att_id)
    if not rec or not rec.get("review"):
        raise HTTPException(409, "Review the file first.")
    return {"instructions": file_review.reply_brief(rec)}


@router.post("/api/reviews/{att_id}/chat")
def api_review_chat(att_id: int):
    """Review in Ask SleePO (Messages: Review on a file's chip): the file's conversation, whose first answer is the review
    card; the review starts when the file has none. Returns {thread, job, new}."""
    from .. import file_review
    c = con()
    try:
        return file_review.start_chat(c, att_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


class ReviewEdits(BaseModel):
    edits: list = []


@router.post("/api/reviews/{att_id}/edits", dependencies=[Depends(json_only)])
def api_review_edits(att_id: int, body: ReviewEdits):
    """Edits the chat proposed (```edits) that Sam keeps: they join the review as kept tracked changes."""
    from .. import file_review
    c = con()
    try:
        return {"ids": file_review.add_edits(c, att_id, [e for e in body.edits if isinstance(e, dict)])}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.post("/api/messages/{item_id}/chat")
def api_message_chat(item_id: int):
    """Open a message in Ask SleePO (Messages: Review beside its bubble; assist/message_chat.py): its conversation, whose first
    answer is the message card, waiting for Sam's instruction. Returns {thread, new}."""
    from .. import message_chat
    c = con()
    try:
        return message_chat.start(c, item_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.get("/api/messages/{item_id}")
def api_message(item_id: int):
    """One Teams or Slack message with its files, for the chat's message card. Reads only."""
    from .. import message_chat
    c = con()
    try:
        m = message_chat.card(c, item_id)
    finally:
        c.close()
    if not m:
        raise HTTPException(404, "No such message.")
    return m


@router.get("/api/messages/{item_id}/link")
def api_message_link(item_id: int):
    """Where a Teams or Slack message lives, for a reply drafted in the chat (Copy and open Teams)."""
    c = con()
    try:
        r = c.execute("SELECT source_id, web_link, conversation_name, author FROM chat_messages WHERE item_id=?", (item_id,)).fetchone()
    finally:
        c.close()
    if not r:
        raise HTTPException(404, "No such message.")
    return {"app": r["source_id"], "link": r["web_link"], "conversation": r["conversation_name"], "author": r["author"]}
