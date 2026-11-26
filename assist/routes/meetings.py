"""Meeting prep, meeting follow-ups and who was in each meeting (moved from api.py, 22 Oct 2026)."""
import subprocess
import threading
import time

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..web import ASSIST, PY, _mid, _nocache, con, json_only

router = APIRouter()


# ---------------------------------------------------------------- meeting prep
PREP_JOBS = {}   # event_id -> {"running", "started", "finished", "ok", "log"}


def _prep_worker(event_id, notes=""):
    job = PREP_JOBS[event_id]
    # tool-free (assist/prepgen.py): the context pack is built in code and the model only writes; Sam's notes go in as his steer
    cmd = [PY, "-m", "assist.cli", "prep-write", event_id] + (["--notes", notes] if notes else [])
    try:
        p = subprocess.run(cmd, cwd=str(ASSIST), capture_output=True, text=True, timeout=900)
        job["ok"] = p.returncode == 0
        job["log"] = (p.stdout or "")[-2000:] + (p.stderr or "")[-1000:]
    except Exception as e:  # pragma: no cover
        job["ok"], job["log"] = False, str(e)
    job["running"], job["finished"] = False, time.strftime("%Y-%m-%d %H:%M:%S")


@router.get("/api/prep")
def api_prep(days: int = 3):
    from .. import prep
    c = con()
    try:
        out = []
        for e in prep.upcoming(c, days):
            e = {k: v for k, v in e.items() if k != "attendee_addresses"}
            j = PREP_JOBS.get(e["event_id"], {})
            e["job"] = ({k: v for k, v in j.items() if k != "log"} | ({"error": (j.get("log") or "").strip()[-400:]} if j.get("ok") is False else {})) or None
            out.append(e)
        return _nocache(out)
    finally:
        c.close()


@router.get("/api/prep/{event_id}")
def api_prep_one(event_id: str):
    """The brief written for one meeting, upcoming or past (the panel folds a past meeting's brief under its follow-up)."""
    from .. import prep
    c = con()
    try:
        return _nocache({"brief": prep._briefs(c).get(event_id)})
    finally:
        c.close()


class PrepRun(BaseModel):
    notes: str = ""


@router.post("/api/prep/{event_id}")
def api_prep_run(event_id: str, body: Optional[PrepRun] = None):
    """Write (or rewrite) the brief for one meeting in the background with Claude Code and the /prep skill.
    Optional JSON {"notes": "..."}: Sam's extra context or steer for this brief."""
    if PREP_JOBS.get(event_id, {}).get("running"):
        return {"started": False, "running": True}
    if sum(1 for j in PREP_JOBS.values() if j.get("running")) >= 3:
        raise HTTPException(429, "three briefs are already being written; try again in a minute")
    notes = ((body.notes if body else "") or "").strip()[:3000]
    PREP_JOBS[event_id] = {"running": True, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "finished": None, "ok": None, "log": "", "notes": notes}
    threading.Thread(target=_prep_worker, args=(event_id, notes), daemon=True).start()
    return {"started": True}


# ---------------------------------------------------------------- meeting follow-ups (assist/followup.py)
FOLLOWUP_JOBS = {}   # meeting id -> {"running", "started", "finished", "ok", "log", "notes"}


def _followup_worker(mid, notes=""):
    job = FOLLOWUP_JOBS[mid]
    # tool-free like the briefs: the pack (transcript, the brief, open items, what was written since) is built in code
    cmd = [PY, "-m", "assist.cli", "followup-write", str(mid)] + (["--notes", notes] if notes else [])
    try:
        p = subprocess.run(cmd, cwd=str(ASSIST), capture_output=True, text=True, timeout=900)
        job["ok"] = p.returncode == 0
        job["log"] = (p.stdout or "")[-2000:] + (p.stderr or "")[-1000:]
    except Exception as e:  # pragma: no cover
        job["ok"], job["log"] = False, str(e)
    job["running"], job["finished"] = False, time.strftime("%Y-%m-%d %H:%M:%S")


def _followup_job(mid):
    j = FOLLOWUP_JOBS.get(mid, {})
    return ({k: v for k, v in j.items() if k != "log"} | ({"error": (j.get("log") or "").strip()[-400:]} if j.get("ok") is False else {})) or None


@router.get("/api/followups")
def api_followups(hours: int = 72):
    """Meetings page: the action count of every follow-up, the recent recorded meetings with none, and the ones being written."""
    from .. import followup
    c = con()
    try:
        out = followup.listing(c, hours)
        out["running"] = [f"m-{k}" for k, j in FOLLOWUP_JOBS.items() if j.get("running")]
        return _nocache(out)
    finally:
        c.close()


@router.get("/api/meetings/{mid}/followup")
def api_followup(mid: str):
    """After a meeting: the actions suggested from what was said, whether one can be written, and the job writing it."""
    from .. import followup
    n = _mid(mid)
    c = con()
    try:
        return _nocache(followup.status(c, n) | {"job": _followup_job(n)})
    finally:
        c.close()


@router.post("/api/meetings/{mid}/followup")
def api_followup_run(mid: str, body: Optional[PrepRun] = None):
    """Write (or rewrite) the follow-up for one recorded meeting in the background. Optional {"notes": "..."}: Sam's steer."""
    n = _mid(mid)
    if FOLLOWUP_JOBS.get(n, {}).get("running"):
        return {"started": False, "running": True}
    if sum(1 for j in FOLLOWUP_JOBS.values() if j.get("running")) >= 3:
        raise HTTPException(429, "three follow-ups are already being written; try again in a minute")
    notes = ((body.notes if body else "") or "").strip()[:3000]
    FOLLOWUP_JOBS[n] = {"running": True, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "finished": None, "ok": None, "log": "", "notes": notes}
    threading.Thread(target=_followup_worker, args=(n, notes), daemon=True).start()
    return {"started": True}


@router.get("/api/meetings/review")
def api_meetings_review():
    from .. import meeting_people
    c = con()
    try:
        return _nocache(meeting_people.review_queue(c))
    finally:
        c.close()


@router.get("/api/meetings/{mid}/people")
def api_meeting_people(mid: str):
    from .. import meeting_people
    c = con()
    try:
        return _nocache(meeting_people.listing(c, _mid(mid)))
    finally:
        c.close()


class PeopleDecision(BaseModel):
    key: Optional[str] = None     # a suggestion to tick or cross
    status: str = "confirmed"     # confirmed | rejected | suggested (undo)
    who: Optional[str] = None     # or a person to add: full name or email


@router.post("/api/meetings/{mid}/people")
def api_meeting_people_decide(mid: str, body: PeopleDecision):
    from .. import meeting_people
    c = con()
    try:
        meeting_people.decide(c, _mid(mid), body.key, body.status, (body.who or "").strip()[:160] or None)
        return _nocache(meeting_people.listing(c, _mid(mid)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


# ---------------------------------------------------------------- live call (assist/live_call.py, 26 Oct 2026)
@router.get("/api/live")
def api_live(event: Optional[str] = None, note: Optional[str] = None):
    """The meeting, the Granola note it follows and its transcript so far. Polled by the Live page; writes nothing."""
    from .. import live_call
    c = con()
    try:
        return _nocache(live_call.state(c, event, note))
    finally:
        c.close()


@router.get("/api/live/now")
def api_live_now():
    """The call Granola is recording now, if any (the top bar's Live pill polls it); writes nothing."""
    from .. import live_call
    c = con()
    try:
        return _nocache(live_call.recording(c) or {"note": None, "event": None})
    except Exception:
        return _nocache({"note": None, "event": None})
    finally:
        c.close()


class LiveAsk(BaseModel):
    question: str = ""
    note: str = ""
    event: Optional[str] = None
    history: list = []   # [{q, a}] asked earlier in this call


@router.post("/api/live/ask", dependencies=[Depends(json_only)])
def api_live_ask(body: LiveAsk):
    """A question about the call so far: a job to poll at /api/replies/jobs/{id} (its answer in `answer`)."""
    from .. import live_call
    c = con()
    try:
        return {"job": live_call.start_job(c, body.question, body.note, body.event, body.history)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:   # Granola did not give the transcript (a deleted note, no sign-in)
        raise HTTPException(502, f"Granola did not give the transcript: {str(e)[:200]}")
    finally:
        c.close()
