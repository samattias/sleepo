"""The Inbox: mail and its threads, attachments and images, Needs response, reply drafts, Outlook drafts, fill-in
questions, documents and briefings from an email (moved from api.py, 22 Oct 2026)."""
import json

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db
from .. import profile
from ..web import ASSIST, _nocache, con, json_only

router = APIRouter()


MAIL_LIST = ("SELECT i.id, i.source_id, i.ts, i.from_name, i.subject, i.text, i.noise, i.url, m.from_address, m.to_json, m.cc_json, m.preview, "
             "m.has_attachments, m.is_read, m.importance, m.conversation_id, m.web_link, (m.item_id IS NOT NULL) AS full "
             "FROM items i LEFT JOIN mail_messages m ON m.item_id=i.id WHERE i.source_id=? ORDER BY i.ts DESC LIMIT ?")


def _names(js):
    return [p.get("name") or p.get("address") for p in json.loads(js or "[]")]


@router.get("/api/mail")
def api_mail(folder: str = "inbox", limit: int = 5000):
    c = con()
    try:
        src = "outlook.sent" if folder in ("sent", "sentitems", "outlook.sent") else "outlook.inbox"
        out = []
        for r in c.execute(MAIL_LIST, (src, limit)):
            d = dict(r)
            d["to"] = _names(d.pop("to_json")) + _names(d.pop("cc_json"))
            d["web_link"] = d["web_link"] or d.pop("url")
            d.pop("url", None)
            out.append(d)
        try:   # the task each email belongs to (assist/task_links.py), for the list's task mark
            from .. import task_links
            tl = task_links.for_items(c, [d["id"] for d in out])
            for d in out:
                d["task"] = tl.get(d["id"])
        except Exception:
            pass
        try:   # a task proposed for the email in the background (assist/tasks.py preplan), when it is more than a reply
            proposed = {r[0] for r in c.execute("SELECT item_id FROM task_proposals WHERE status='ok' AND needs_task=1")}
            for d in out:
                d["task_proposed"] = d["id"] in proposed
        except Exception:
            pass
        return _nocache(out)
    finally:
        c.close()


@router.get("/api/mail/{item_id}/conversation")
def api_mail_conversation(item_id: int):
    """The thread quoted inside one email, as separate messages (oldest first), for reading before replying."""
    from .. import threadparse
    c = con()
    try:
        m = c.execute("SELECT from_name, from_address, received_at, sent_at, to_json, body_text FROM mail_messages WHERE item_id=?", (item_id,)).fetchone()
        if not m:
            raise HTTPException(404)
        to = ", ".join(_names(m["to_json"]))
        msgs = threadparse.split(m["body_text"], m["from_name"] or m["from_address"] or "", m["received_at"] or m["sent_at"] or "", to)
        for x in msgs:
            x["me"] = profile.mentions_me(x["from"] or "")
        return _nocache({"messages": msgs})
    finally:
        c.close()


@router.get("/api/mail/{item_id}")
def api_mail_one(item_id: int):
    from .. import replies
    c = con()
    try:
        i = c.execute("SELECT id, source_id, ts, from_name, subject, text, noise, url FROM items WHERE id=?", (item_id,)).fetchone()
        if not i:
            raise HTTPException(404)
        m = c.execute("SELECT * FROM mail_messages WHERE item_id=?", (item_id,)).fetchone()
        d = {"id": i["id"], "folder": i["source_id"], "ts": i["ts"], "note": i["text"], "noise": i["noise"], "subject": i["subject"],
             "from": {"name": i["from_name"] or "", "address": ""}, "to": [], "cc": [], "bcc": [], "body": None, "body_type": None,
             "web_link": i["url"], "attachments": [], "thread": [], "full": bool(m)}
        if m:
            d.update({"subject": m["subject"], "from": {"name": m["from_name"] or "", "address": m["from_address"] or ""},
                      "to": json.loads(m["to_json"] or "[]"), "cc": json.loads(m["cc_json"] or "[]"), "bcc": json.loads(m["bcc_json"] or "[]"),
                      "body": m["body"], "body_type": m["body_type"], "web_link": m["web_link"] or i["url"], "importance": m["importance"]})
            d["attachments"] = [dict(a) | {"available": bool(a["path"]), "has_text": bool(a["has_text"])} for a in c.execute(
                "SELECT id, name, content_type, size, is_inline, content_id, kind, path, (text IS NOT NULL) AS has_text FROM mail_attachments WHERE item_id=? ORDER BY is_inline, name", (item_id,))]
            for a in d["attachments"]:
                a.pop("path")
                a["on_disk"] = a["available"]   # the original file is stored; otherwise only its extracted text
                a["available"] = a["available"] or a["has_text"]
            d["thread"] = replies.thread(c, item_id)   # received and sent, across Apple Mail and Microsoft 365 ids
            if m["body_type"] != "html" and m["internet_message_id"]:
                d.update(_rich(m["internet_message_id"]))
        return _nocache(d)
    finally:
        c.close()


def _rich(imid):
    """The formatted original from Apple Mail, when it has one (assist/applemail.py: read per view, not stored)."""
    from .. import applemail
    try:
        html = applemail.html_body(imid)
    except Exception:   # no Full Disk Access, store moved, unreadable file: the stored text still shows
        return {}
    return {"body": html, "body_type": "html", "rich": "apple-mail"} if html else {}


INLINE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/bmp"}   # no SVG: it can carry script


@router.get("/api/mail/{item_id}/cid/{cid:path}")
def api_mail_inline(item_id: int, cid: str):
    """An image inside a message body (a cid: reference), read from Apple Mail per view. Only for messages held in full."""
    from fastapi.responses import Response
    from .. import applemail
    c = con()
    try:
        m = c.execute("SELECT internet_message_id FROM mail_messages WHERE item_id=?", (item_id,)).fetchone()
    finally:
        c.close()
    if not m or not m["internet_message_id"]:
        raise HTTPException(404)
    try:
        hit = applemail.inline_part(m["internet_message_id"], cid)
    except Exception:
        hit = None
    if not hit or hit[1].lower() not in INLINE_TYPES:
        raise HTTPException(404)
    return Response(hit[0], media_type=hit[1], headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.get("/api/mail/{item_id}/attachments/{att_id}")
def api_mail_attachment(item_id: int, att_id: int, download: int = 0):
    from .. import mailsync
    c = con()
    try:
        a = c.execute("SELECT name, content_type, path, text FROM mail_attachments WHERE id=? AND item_id=?", (att_id, item_id)).fetchone()
    finally:
        c.close()
    if a and not a["path"] and a["text"]:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(a["text"])
    if not a or not a["path"]:
        raise HTTPException(404)
    f = (mailsync.attachments_dir() / a["path"]).resolve()
    if mailsync.attachments_dir().resolve() not in f.parents or not f.exists():
        raise HTTPException(404)
    return FileResponse(str(f), media_type=a["content_type"] or "application/octet-stream", filename=a["name"],
                        content_disposition_type="attachment" if download else "inline")


@router.get("/api/replies/inbox")
def api_replies_inbox(days: int = 14):
    from .. import replies
    c = con()
    try:
        out = replies.inbox(c, days)
        if db.has_table(c, "reply_predrafts"):   # which emails already have a recommended reply waiting (assist/replies.py predraft)
            ready = {r[0]: r[1] for r in c.execute("SELECT item_id, mode FROM reply_predrafts WHERE status='ok'")}
            for m in out:
                m["drafted"] = m["id"] in ready
                if m["id"] in ready and ready[m["id"]] in ("replyall", "forward"):   # the response the draft chose
                    m["response"] = ready[m["id"]]
        return _nocache(out)
    finally:
        c.close()


class OutlookDraft(BaseModel):
    body: str
    mode: str = "reply"     # reply | replyall | followup | forward
    add: list = []          # addresses to Cc (or To on a forward)


@router.post("/api/replies/{item_id}/outlook", dependencies=[Depends(json_only)])
def api_replies_outlook(item_id: int, body: OutlookDraft, request: Request):
    """Save the draft into Sam's Outlook, in the email's own thread (assist/outlook_drafts.py), and return its link. On
    Sam's click only (Sam, 22 Oct 2026); never sends. 401 until he has signed in with `assist.cli outlook-login`."""
    from .. import outlook_drafts as od
    c = con()
    try:
        mode = body.mode if body.mode in ("reply", "replyall", "followup", "forward") else "reply"
        return od.save(c, item_id, body.body[:20000], mode, [str(x)[:200] for x in body.add[:20]])
    except od.NotSignedIn:
        raise HTTPException(401, "Sign in once so SleePO can save drafts to Outlook: run  ~/.assist/venv/bin/python -m assist.cli outlook-login  in Terminal.")
    except (ValueError, LookupError) as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    finally:
        c.close()


@router.get("/api/mail/{item_id}/outlook-link")
def api_mail_outlook_link(item_id: int):
    """The email's own Outlook link, to open its thread in Outlook (found by Message-ID; read only)."""
    from .. import outlook_drafts as od
    c = con()
    try:
        return {"web_link": od.link(c, item_id)}
    except od.NotSignedIn:
        raise HTTPException(401, "Sign in once to open emails in Outlook: run  ~/.assist/venv/bin/python -m assist.cli outlook-login  in Terminal.")
    except (ValueError, LookupError) as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    finally:
        c.close()


@router.get("/api/replies/{item_id}/predraft")
def api_replies_predraft(item_id: int):
    """The recommended reply written in the background for an email waiting on Sam, or null."""
    from .. import replies
    c = con()
    try:
        return _nocache({"predraft": replies.predraft_get(c, item_id)})
    finally:
        c.close()


class NeedsReply(BaseModel):
    needs: bool


@router.post("/api/replies/{item_id}/needs", dependencies=[Depends(json_only)])
def api_replies_needs(item_id: int, body: NeedsReply, request: Request):
    """Sam adds an email to Needs reply or removes it (loops.mark_reply): his call wins over the rule everywhere."""
    from .. import loops
    c = con()
    try:
        out = {"ok": True, "loop": loops.mark_reply(c, item_id, body.needs)}
        if body.needs:   # added to Needs reply: draft its recommended reply, and propose its task, now
            from .. import replies, tasks as _tasks
            replies.spawn_predraft(ASSIST)
            try:
                _tasks.spawn_preplan(ASSIST)
            except Exception:
                pass
        return out
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


class ReplyRequest(BaseModel):
    item_id: int
    instructions: str = ""
    mode: str = "reply"     # reply | replyall | forward | followup (on Sam's own sent email)
    add: list = []          # people added (forward recipients, or extra Cc on reply-all)
    length: Optional[int] = None   # 1 one line … 5 thorough (replies.LENGTHS); default 3
    current: str = ""       # the draft on screen: revise it with the instructions as feedback, not a new draft
    base: str = ""          # the last text SleePO wrote: what differs is Sam's own wording, kept (assist/revise.py)
    history: list = []      # his earlier requests for this draft, oldest first


class Compose(BaseModel):
    to: list = []
    cc: list = []
    subject: str = ""
    body: str = ""


@router.post("/api/outlook/compose", dependencies=[Depends(json_only)])
def api_outlook_compose(body: Compose):
    """A new message in Outlook for Mac, filled in (assist/outlook_desktop.py). Opens a window on Sam's Mac; sends nothing."""
    from .. import outlook_desktop
    try:
        outlook_desktop.compose(body.to[:30], body.cc[:30], body.subject, body.body)
        return {"ok": True}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Outlook did not open: {str(e)[:200]}")


@router.post("/api/replies/generate", dependencies=[Depends(json_only)])
def api_replies_generate(body: ReplyRequest, request: Request):
    from .. import replies
    c = con()
    try:
        mode = body.mode if body.mode in ("reply", "replyall", "forward", "followup") else "reply"
        return {"job": replies.start(c, body.item_id, body.instructions[:4000], ASSIST, mode, [str(x)[:120] for x in body.add[:20]],
                                   body.length if body.length in (1, 2, 3, 4, 5) else None, body.current[:12000] or None,
                                   body.base[:12000] or None, [str(x)[:600] for x in body.history[-5:]])}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


class DeliverablePlan(BaseModel):
    ask: str = ""
    format: Optional[str] = None   # pptx | docx | xlsx; None lets the plan choose


class DeliverableOpen(BaseModel):
    format: str = "docx"
    title: str = ""
    audience: str = ""
    outline: list = []
    prompt: str = ""
    covers: list = []
    gaps: list = []
    doc: Optional[str] = None


@router.post("/api/mail/{item_id}/deliverable/plan", dependencies=[Depends(json_only)])
def api_deliverable_plan(item_id: int, body: DeliverablePlan, request: Request):
    """Plan a deck, document or workbook that answers this email (assist/deliverables.py): a tool-free run over SleePO's
    context pack. Returns a job to poll."""
    from .. import deliverables
    c = con()
    try:
        return {"job": deliverables.start(c, item_id, body.ask[:4000], body.format)}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.get("/api/deliverables/jobs/{jid}")
def api_deliverable_job(jid: str):
    from .. import deliverables
    j = deliverables.job(jid)
    if not j:
        raise HTTPException(404, "This plan is no longer available. Plan it again.")
    return _nocache({k: v for k, v in j.items() if k != "known_docs"})


class DeliverableChat(DeliverableOpen):
    ask: str = ""


@router.post("/api/mail/{item_id}/deliverable/chat", dependencies=[Depends(json_only)])
def api_deliverable_chat(item_id: int, body: DeliverableChat, request: Request):
    """Refine a document plan in Ask SleePO: a conversation that starts from the plan, with its context pack in the
    conversation's folder (deliverables.to_chat). Only on Sam's click."""
    from .. import deliverables
    c = con()
    try:
        spec = body.model_dump()
        return {"thread": deliverables.to_chat(c, item_id, spec, spec.pop("ask", ""))}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.post("/api/mail/{item_id}/deliverable/open", dependencies=[Depends(json_only)])
def api_deliverable_open(item_id: int, body: DeliverableOpen, request: Request):
    """Open Claude Cowork on the plan Sam approved, with SleePO's context pack and working copies of the files. JSON only
    (forces a CORS preflight from other origins); nothing runs in Claude until Sam presses send there."""
    from .. import deliverables
    c = con()
    try:
        return deliverables.open_in_claude(c, item_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class BriefingAsk(BaseModel):
    ask: str = ""   # what Sam wants the briefing to focus on (optional)


@router.get("/api/mail/{item_id}/briefing")
def api_briefing(item_id: int):
    """The latest briefing on this email (assist/briefing.py, kept 7 days), or null."""
    from .. import briefing
    return _nocache({"briefing": briefing.latest(item_id)})


@router.post("/api/mail/{item_id}/briefing", dependencies=[Depends(json_only)])
def api_briefing_start(item_id: int, body: BriefingAsk, request: Request):
    """Brief Sam on the situation around this email: a tool-free run over the thread and everything around it. Returns a
    job to poll."""
    from .. import briefing
    c = con()
    try:
        return {"job": briefing.start(c, item_id, body.ask[:2000])}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.get("/api/briefings/jobs/{jid}")
def api_briefing_job(jid: str):
    from .. import briefing
    j = briefing.job(jid)
    if not j:
        raise HTTPException(404, "This briefing is no longer available. Create it again.")
    return _nocache(j)


@router.post("/api/mail/{item_id}/briefing/chat", dependencies=[Depends(json_only)])
def api_briefing_chat(item_id: int, request: Request):
    """Start (or reopen) the Ask SleePO conversation that continues from this email's briefing. Only on Sam's click."""
    from .. import briefing
    try:
        return briefing.to_chat(item_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


class AddedFile(BaseModel):
    name: str
    data: str   # base64


@router.post("/api/mail/{item_id}/files", dependencies=[Depends(json_only)])
def api_mail_add_file(item_id: int, body: AddedFile, request: Request):
    """Sam adds a file to an email (a linked document SleePO cannot open): its text is kept as the email's attachment
    (assist/links.py add_file), so the reply, the document plan and the briefing read it."""
    import base64
    from .. import links
    try:
        data = base64.b64decode(body.data, validate=True)
    except Exception:
        raise HTTPException(400, "The file could not be read.")
    c = con()
    try:
        return {"ok": True, "id": links.add_file(c, item_id, body.name, data)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.delete("/api/mail/{item_id}/files/{att_id}")
def api_mail_remove_file(item_id: int, att_id: int):
    from .. import links
    c = con()
    try:
        return {"ok": bool(links.remove_file(c, item_id, att_id))}
    finally:
        c.close()


class ReplyChat(BaseModel):
    body: str
    notes: str = ""
    ask: str = ""
    mode: str = "reply"
    length: Optional[int] = None


@router.post("/api/replies/{item_id}/chat", dependencies=[Depends(json_only)])
def api_replies_chat(item_id: int, body: ReplyChat, request: Request):
    """Continue a reply draft in Ask SleePO: a conversation that starts from the draft as Sam last edited it, with
    everything it was written from in the conversation's folder (replies.to_chat). Only on Sam's click."""
    from .. import replies
    c = con()
    try:
        return {"thread": replies.to_chat(c, item_id, body.body[:20000], body.notes[:1000], body.ask[:4000],
                                          body.mode if body.mode in replies.MODE_RULES else "reply", body.length)}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.get("/api/replies/{item_id}/attachments")
def api_replies_attachments(item_id: int):
    from .. import replies
    c = con()
    try:
        return _nocache(replies.attachments(c, item_id))
    finally:
        c.close()


@router.get("/api/replies/jobs/{jid}")
def api_replies_job(jid: str):
    from .. import replies
    j = replies.job(jid)
    if not j:
        raise HTTPException(404, "This draft is no longer available. Generate it again.")
    return _nocache(j)
class FillQuestionsRequest(BaseModel):
    kind: str = "email"            # email | chat
    draft: str = ""
    item_id: Optional[int] = None  # email: the email replied to
    ids: list = []                 # chat: the conversation's message ids
    app: Optional[str] = None      # chat: teams | slack
    ask: str = ""
    tid: Optional[str] = None      # the Ask SleePO conversation a chat card's draft was written in


class FillAnswersRequest(BaseModel):
    kind: str = "email"
    draft: str = ""
    app: Optional[str] = None
    answers: list = []             # [{question, fills: [...], answer: [...]}]


@router.post("/api/fill/questions", dependencies=[Depends(json_only)])
def api_fill_questions(body: FillQuestionsRequest, request: Request):
    """Questions for the blanks in a draft (assist/fill_in.py), as Claude asks a user: a job to poll at /api/replies/jobs/{id}."""
    from .. import fill_in
    if body.kind not in ("email", "chat") or (body.kind == "chat" and body.app not in ("teams", "slack")):
        raise HTTPException(400, "kind email, or chat with app teams or slack")
    c = con()
    try:
        return {"job": fill_in.start_questions(c, body.kind, body.draft[:20000], body.item_id,
                                               [int(x) for x in body.ids[:200] if str(x).isdigit()], body.app, body.ask[:4000],
                                               (body.tid or "")[:64] or None)}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


class RewritePartRequest(BaseModel):
    kind: str = "email"            # email | chat
    draft: str = ""
    start: int = 0                 # the selected part: draft[start:end]
    end: int = 0
    ask: str = ""
    item_id: Optional[int] = None  # email: the email replied to
    ids: list = []                 # chat: the conversation's message ids
    app: Optional[str] = None      # chat: teams | slack
    tid: Optional[str] = None      # an Ask SleePO conversation the draft was written in
    subject: str = ""


@router.post("/api/rewrite-part", dependencies=[Depends(json_only)])
def api_rewrite_part(body: RewritePartRequest, request: Request):
    """Write only the selected part of a draft again (assist/rewrite_part.py): a job to poll at /api/replies/jobs/{id}."""
    from .. import rewrite_part
    if body.kind not in ("email", "chat") or (body.kind == "chat" and body.app not in ("teams", "slack")):
        raise HTTPException(400, "kind email, or chat with app teams or slack")
    draft = body.draft[:20000]
    c = con()
    try:
        return {"job": rewrite_part.start_job(c, body.kind, draft, body.start, min(body.end, len(draft)), body.ask[:2000],
                                              body.item_id, [int(x) for x in body.ids[:200] if str(x).isdigit()],
                                              body.app, (body.tid or "")[:64] or None, body.subject[:300])}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/fill/answers", dependencies=[Depends(json_only)])
def api_fill_answers(body: FillAnswersRequest, request: Request):
    """Sam's answers fill the blanks in the draft as it stands (assist/fill_in.py): a job to poll at /api/replies/jobs/{id}."""
    from .. import fill_in
    if body.kind not in ("email", "chat"):
        raise HTTPException(400, "kind email or chat")
    answers = [a for a in body.answers[:8] if isinstance(a, dict)]
    try:
        return {"job": fill_in.start_answers(body.kind, body.draft[:20000], answers, body.app if body.app in ("teams", "slack") else None)}
    except ValueError as e:
        raise HTTPException(404, str(e))
