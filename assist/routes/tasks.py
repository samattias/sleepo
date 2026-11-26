"""Tasks (assist/tasks.py): the list, steps, actions, documents, suggestions and proposals; the reply Sam is working on;
mail and messages linked to tasks (assist/task_links.py); the task history (assist/task_history.py) (moved from api.py,
23 Oct 2026)."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..web import _mid, _nocache, con, json_only

router = APIRouter()


# ---------------------------------------------------------------- Tasks › History (assist/task_history.py, Sam, 23 Oct 2026):
# the tasks Sam would have had, rebuilt from what he did; his edits are kept and are the reference for measuring suggestions
class HistoryEdit(BaseModel):
    title: Optional[str] = None
    done_when: Optional[str] = None
    initiative: Optional[str] = None
    area: Optional[str] = None
    status: Optional[str] = None      # removed (not a task) | done (undo)


class HistoryMerge(BaseModel):
    into: int


class HistorySplit(BaseModel):
    title: Optional[str] = None


class HistoryMove(BaseModel):
    ref: str
    step_id: Optional[int] = None     # None: not part of any task


@router.get("/api/tasks/history")
def api_task_history(weeks: Optional[int] = None):
    from .. import task_history
    c = con()
    try:
        return _nocache(task_history.listing(c, weeks) | {"job": task_history.state()})
    finally:
        c.close()


@router.post("/api/tasks/history/build", dependencies=[Depends(json_only)])
def api_task_history_build(body: dict):
    """Build the weeks not built yet (redo: rebuild them all, keeping Sam's edited tasks). One tool-free run per week."""
    from .. import task_history
    return task_history.start(redo=bool(body.get("redo")))


@router.get("/api/tasks/history/eval")
def api_task_history_eval(days: int = 30):
    from .. import task_history
    c = con()
    try:
        return _nocache(task_history.evaluate(c, max(7, min(days, 120))))
    finally:
        c.close()


@router.patch("/api/tasks/history/{hid}", dependencies=[Depends(json_only)])
def api_task_history_edit(hid: int, body: HistoryEdit):
    from .. import task_history
    c = con()
    try:
        task_history.update(c, hid, body.model_dump(exclude_unset=True))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/tasks/history/{hid}/merge", dependencies=[Depends(json_only)])
def api_task_history_merge(hid: int, body: HistoryMerge):
    from .. import task_history
    c = con()
    try:
        task_history.merge(c, hid, body.into)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/tasks/history/steps/{sid}/split", dependencies=[Depends(json_only)])
def api_task_history_split(sid: int, body: HistorySplit):
    from .. import task_history
    c = con()
    try:
        return {"id": task_history.split(c, sid, body.title)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/tasks/history/actions/move", dependencies=[Depends(json_only)])
def api_task_history_move(body: HistoryMove):
    from .. import task_history
    c = con()
    try:
        task_history.move_action(c, body.ref, body.step_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


class TaskLink(BaseModel):
    task_id: int
    on: bool = True


@router.get("/api/items/{item_id}/tasks")
def api_item_tasks(item_id: int):
    """The tasks an email (its whole thread), message or meeting note is linked to (assist/task_links.py), and the open
    tasks to pick from."""
    from .. import task_links
    c = con()
    try:
        task_links.sync_threads(c, log=lambda *_: None)   # a task just made from this email links at once (milliseconds)
        return _nocache({"linked": task_links.for_item(c, item_id), "open": task_links.open_tasks(c)})
    finally:
        c.close()


@router.post("/api/items/{item_id}/tasks", dependencies=[Depends(json_only)])
def api_item_task_link(item_id: int, body: TaskLink, request: Request):
    """Sam links an email's thread to a task, or unlinks it (and it stays unlinked)."""
    from .. import task_links
    c = con()
    try:
        task_links.set_link(c, item_id, body.task_id, body.on)
        return {"ok": True, "linked": task_links.for_item(c, item_id)}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()


@router.get("/api/tasks/{tid}/linked")
def api_task_linked(tid: int):
    """Everything linked to a task, newest first, one row per email thread (assist/task_links.py for_task)."""
    from .. import task_links
    c = con()
    try:
        return _nocache(task_links.for_task(c, tid))
    finally:
        c.close()


@router.get("/api/replies/{item_id}/working")
def api_replies_working(item_id: int):
    """The reply Sam is working on for this email (assist/reply_working.py): loaded ahead of the recommended reply."""
    from .. import reply_working
    c = con()
    try:
        return _nocache({"working": reply_working.get(c, item_id)})
    finally:
        c.close()


@router.put("/api/replies/{item_id}/working", dependencies=[Depends(json_only)])
async def api_replies_working_put(item_id: int, request: Request):
    """Keep the composer's text for this email: {body, mode, source: chat | edit}. An empty body clears it."""
    from .. import reply_working
    b = await request.json()
    c = con()
    try:
        reply_working.put(c, item_id, str(b.get("body") or ""), b.get("mode"), b.get("source") or "edit")
        return {"ok": True}
    finally:
        c.close()


# ---------------------------------------------------------------- Tasks (assist/tasks.py): initiative → task → sub-task → action
class TaskAct(BaseModel):
    step: int
    prompt: Optional[str] = None


@router.get("/api/tasks")
def api_tasks():
    from .. import tasks
    c = con()
    try:
        return _nocache(tasks.listing(c))
    finally:
        c.close()


@router.post("/api/tasks", dependencies=[Depends(json_only)])
async def api_tasks_create(request: Request):
    """A task Sam makes (New task, or a proposal from an email or meeting he saved): {title, done_when, initiative_id, due,
    priority, owner, subtasks, sources, actions, parent_id, add_to, origin}. Stored as open: it is his."""
    from .. import tasks
    b = await request.json()
    c = con()
    try:
        origin = b.get("origin") if b.get("origin") in ("sam", "mail", "meeting") else "sam"
        b["guess_initiative"] = False   # Sam chose the initiative (or none) himself
        if b.get("subtasks") is not None or b.get("add_to"):
            tid = tasks.save_proposal(c, b, origin)
        else:
            tid = tasks.create(c, b, "open", origin)
            c.commit()
        return {"id": tid}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.patch("/api/tasks/{tid}", dependencies=[Depends(json_only)])
async def api_tasks_patch(tid: int, request: Request):
    """Edit fields (tasks.EDITABLE) and/or set status (open accepts or reopens; done, dropped, snoozed, dismissed)."""
    from .. import tasks
    b = await request.json()
    c = con()
    try:
        tasks.update(c, tid, {k: v for k, v in b.items() if k in tasks.EDITABLE})
        if b.get("status"):
            tasks.set_status(c, tid, b["status"], b.get("snooze_until"), b.get("note"))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/tasks/{tid}/log", dependencies=[Depends(json_only)])
async def api_tasks_log(tid: int, request: Request):
    """What Sam did with an action of a step (copied, opened, drafted)."""
    from .. import tasks
    b = await request.json()
    c = con()
    try:
        tasks.log_action(c, tid, b.get("step"), b.get("what") or "used", b.get("label"))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get("/api/tasks/{tid}/sources")
def api_tasks_sources(tid: int):
    """What a step is about, resolved like an Actions item's sources (its own first, then its task's)."""
    from .. import action_context, tasks
    c = con()
    try:
        return _nocache(action_context.sources(c, tasks.task_row(c, tid)))
    except ValueError:
        raise HTTPException(404)
    finally:
        c.close()


@router.post("/api/tasks/{tid}/act", dependencies=[Depends(json_only)])
def api_tasks_act(tid: int, body: TaskAct, request: Request):
    """Open a step's create / draft action in Claude with its context pack. Nothing runs until Sam presses send there."""
    from .. import tasks
    c = con()
    try:
        return tasks.act(c, tid, body.step, body.prompt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get("/api/tasks/{tid}/documents")
def api_tasks_documents(tid: int):
    """The documents a task is about: pinned by Sam, its own material, and documents on its topic, newest first."""
    from .. import tasks
    c = con()
    try:
        return _nocache(tasks.documents(c, tid))
    except ValueError:
        raise HTTPException(404)
    finally:
        c.close()


@router.post("/api/tasks/{tid}/documents", dependencies=[Depends(json_only)])
async def api_tasks_documents_set(tid: int, request: Request):
    """Sam's call on one document of a task: {doc, op: pin | unpin | hide | unhide}."""
    from .. import tasks
    b = await request.json()
    c = con()
    try:
        tasks.set_document(c, tid, str(b.get("doc") or ""), str(b.get("op") or ""))
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/tasks/{tid}/outlook", dependencies=[Depends(json_only)])
async def api_tasks_outlook(tid: int, request: Request):
    """A step's new email saved as a draft in Sam's Outlook, and its link (never sent; on his click only). Replies to an
    email go through /api/replies/{id}/outlook, into the email's own thread."""
    from .. import outlook_drafts as od, tasks
    b = await request.json()
    lst = lambda v: [str(x).strip()[:200] for x in (v if isinstance(v, list) else str(v or "").replace(";", ",").split(",")) if str(x).strip()][:20]
    c = con()
    try:
        return tasks.to_outlook(c, tid, int(b.get("step", -1)), lst(b.get("to")), lst(b.get("cc")), str(b.get("subject") or "")[:250], str(b.get("body") or "")[:20000])
    except od.NotSignedIn:
        raise HTTPException(401, "Sign in once so SleePO can save drafts to Outlook: run  ~/.assist/venv/bin/python -m assist.cli outlook-login  in Terminal.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    finally:
        c.close()


@router.get("/api/mail/{item_id}/task-proposal")
def api_mail_task_proposal(item_id: int):
    """The task proposed in the background for an email waiting on Sam (assist/tasks.py preplan), or the task he saved from it."""
    from .. import tasks
    c = con()
    try:
        return _nocache(tasks.proposal_get(c, item_id))
    finally:
        c.close()


@router.post("/api/mail/{item_id}/task-proposal/dismiss")
def api_mail_task_proposal_dismiss(item_id: int):
    """Sam: this email is not a task. The proposal is not shown again (Propose a task still works)."""
    from .. import tasks
    c = con()
    try:
        tasks.proposal_dismiss(c, item_id)
        return {"ok": True}
    finally:
        c.close()


@router.get("/api/meetings/{mid}/steps")
def api_meeting_steps(mid: str):
    """A recorded meeting's follow-ups as proposed steps (assist/tasks.py propose_from_meeting, run here too so a follow-up
    written before this existed is converted), and what became of them."""
    from .. import tasks
    n = _mid(mid)
    c = con()
    try:
        tasks.propose_from_meeting(c, n, log=lambda *_: None)
        return _nocache(tasks.steps_from(c, f"G{n}"))
    finally:
        c.close()


@router.get("/api/prep/{event_id}/steps")
def api_prep_steps(event_id: str):
    """An upcoming meeting's actions to prepare as proposed prep steps (assist/tasks.py propose_from_brief)."""
    from .. import tasks
    c = con()
    try:
        tasks.propose_from_brief(c, event_id, log=lambda *_: None)
        return _nocache(tasks.steps_from(c, f"K{event_id}"))
    finally:
        c.close()


@router.post("/api/tasks/suggest")
def api_tasks_suggest():
    from .. import tasks
    return {"started": tasks.start_suggest()}


class TaskPropose(BaseModel):
    mail: Optional[int] = None
    meeting: Optional[str] = None
    ask: str = ""


@router.post("/api/tasks/propose", dependencies=[Depends(json_only)])
def api_tasks_propose(body: TaskPropose, request: Request):
    """Propose a task from an email or a meeting (tool-free run). Returns a job to poll; nothing is stored until Sam saves."""
    from .. import tasks
    c = con()
    try:
        return {"job": tasks.start(c, body.mail, _mid(body.meeting) if body.meeting else None, body.ask[:4000])}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get("/api/tasks/jobs/{jid}")
def api_tasks_job(jid: str):
    from .. import tasks
    j = tasks.job(jid)
    if not j:
        raise HTTPException(404)
    return _nocache(j)
