"""Working on an initiative or a top-of-mind topic from its page (assist/initiative_work.py; Sam, 29 Oct 2026): read what is
behind it in place, and act on it in Ask SleePO: every button (an email, a document, a decision, a question) starts a
conversation with the subject's context; a decision taken there is recorded by its card. Nothing is sent from here.
An initiative's actions are under /api/initiatives/{slug}/…, a topic's under /api/topics/{tid}/work/… (its page data is
GET /api/topics/{tid}); both run the same code with the subject as a slug or "topic:<id>"."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..web import _nocache, con, json_only

router = APIRouter()


class Focus(BaseModel):
    focus: list = []                  # "item:123", "meeting:45", "attachment:9": what Sam picked on the page


class ChatIn(Focus):
    intent: str = ""                  # the button Sam pressed: email | document | decide; empty: Ask in chat


class RecordIn(BaseModel):
    question: str
    choice: str = ""                  # the option Sam took
    note: str = ""                    # his call in his words
    task_id: Optional[int] = None     # one of his tasks on the initiative; else a new "Decide: …" task
    decided: bool = True              # False: keep it as an open decide step, to decide later
    refs: dict = {}                   # the sources it rests on, {S3: {label, url}}


def _run(fn, *a, code=400):
    c = con()
    try:
        return fn(c, *a)
    except ValueError as e:
        raise HTTPException(code, str(e))
    finally:
        c.close()


def _read(ref_type, ref_id):
    from .. import initiative_work
    r = _run(initiative_work.read, ref_type, ref_id)
    if not r:
        raise HTTPException(404, "Not available: it may be older than the 30-day window, or private.")
    return _nocache(r)


def _record(subj, body):
    from .. import initiative_work
    return _run(initiative_work.record, subj, body.question, body.choice, body.note, body.task_id, body.decided, body.refs)


def _chat(subj, body):
    from .. import initiative_work
    return _run(initiative_work.to_chat, subj, body.focus, body.intent, code=404)


# ------------------------------------------------------------------------------------------------ an initiative
@router.get("/api/initiatives/{slug}/read/{ref_type}/{ref_id}")
def api_ini_read(slug: str, ref_type: str, ref_id: int):
    """One linked item in full, to read on the page. Reads only."""
    return _read(ref_type, ref_id)


@router.post("/api/initiatives/{slug}/decide/record", dependencies=[Depends(json_only)])
def api_ini_decide_record(slug: str, body: RecordIn):
    """Sam's call as a decide step under the initiative (Tasks), from the chat's decide card: closed with his note, or open
    to decide later."""
    return _record(slug, body)


@router.post("/api/initiatives/{slug}/chat", dependencies=[Depends(json_only)])
def api_ini_chat(slug: str, body: ChatIn):
    """An Ask SleePO conversation that starts from the initiative's status, with its pack in the conversation's folder and the
    instruction of the button Sam pressed; returns {thread, prompt} (prompt: the first question, which the app sends)."""
    return _chat(slug, body)


# ------------------------------------------------------------------------------------------------ a top-of-mind topic
@router.get("/api/topics/{tid}")
def api_topic(tid: int):
    """One topic for its page: the topic, its sources with what each points at and what it said and shared (the latest first),
    the files shared in them, its initiative's status, its task, and what is in progress on it (drafts, decide steps). Reads
    only."""
    from .. import initiative_work, initiatives, topics
    c = con()
    try:
        t = topics.one(c, tid)
        if not t:
            raise HTTPException(404, "This topic is no longer top of mind: a later run did not name it.")
        t["sources"] = initiative_work.topic_refs(t)
        t["files"] = initiative_work.topic_latest(c, t["sources"])   # what each source said and shared; the files, newest first
        t["work"] = initiative_work.topic_work(c, tid, t["task_id"])
        ini = initiatives.by_slug(c, t["initiative_slug"]) if t["initiative_slug"] else None
        if ini:
            u = initiatives.detail(c, t["initiative_slug"])["last_update"]
            t["initiative_status"] = {"health": u["health"], "status": u["status"]} if u else None
        task = c.execute("SELECT id, title, status FROM tasks WHERE id=?", (t["task_id"],)).fetchone() if t["task_id"] else None
        t["task"] = dict(task) if task else None
        return _nocache(t)
    finally:
        c.close()


@router.get("/api/topics/{tid}/work/read/{ref_type}/{ref_id}")
def api_topic_read(tid: int, ref_type: str, ref_id: int):
    return _read(ref_type, ref_id)


@router.post("/api/topics/{tid}/work/decide/record", dependencies=[Depends(json_only)])
def api_topic_decide_record(tid: int, body: RecordIn):
    return _record(f"topic:{tid}", body)


@router.post("/api/topics/{tid}/work/chat", dependencies=[Depends(json_only)])
def api_topic_chat(tid: int, body: ChatIn):
    return _chat(f"topic:{tid}", body)
