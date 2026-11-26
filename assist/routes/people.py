"""People and what links to them: the people list and person page, organisations, entity timelines, link review, the
graph and the open-items register (moved from api.py, 22 Oct 2026)."""
import json
import re

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import db, graph
from ..web import _nocache, con, json_only, snapshot

router = APIRouter()


@router.get("/api/people")
def api_people():
    return _nocache([{k: v for k, v in p.items() if k != "profile"} for p in snapshot()["people"]])


@router.get("/api/people/{pid}")
def api_person(pid: str):
    p = next((x for x in snapshot()["people"] if x["id"] == pid), None)
    if not p:
        raise HTTPException(404)
    return _nocache(p)


@router.get("/api/people/{pid}/page")
def api_person_page(pid: str):
    """Everything about one person for their page: coming up, open between you, contact rhythm, their own words, documents,
    initiatives, roadmap items and who they work with (assist/person_page.py). The timeline stays on /api/entities/person/{id}."""
    from .. import person_page
    m = re.fullmatch(r"(?:p-)?(\d+)", pid)
    if not m:
        raise HTTPException(404)
    c = con()
    try:
        d = person_page.build(c, int(m.group(1)))
        if not d:
            raise HTTPException(404)
        return _nocache(d)
    finally:
        c.close()



def _pid(pid):
    m = re.fullmatch(r"(?:p-)?(\d+)", pid)
    if not m:
        raise HTTPException(404)
    return int(m.group(1))


@router.get("/api/people/{pid}/summary")
def api_person_summary(pid: str):
    """Where things stand with them (assist/person_summary.py): the latest summary, whether something came in with them
    since, and whether one is being written. Reads only."""
    from .. import person_summary
    c = con()
    try:
        return _nocache(person_summary.state(c, _pid(pid)))
    finally:
        c.close()


@router.post("/api/people/{pid}/summary", dependencies=[Depends(json_only)])
def api_person_summary_start(pid: str):
    """Write where things stand with them now (one tool-free run, about 10 s); poll the GET until it is done."""
    from .. import person_summary
    c = con()
    try:
        return {"job": person_summary.start(c, _pid(pid))}
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        c.close()

@router.get("/api/graph")
def api_graph():
    return _nocache(graph.build(snapshot()))


# ---------------------------------------------------------------- open loops (assist/loops.py) and entity timelines (assist/entities.py)
@router.get("/api/loops")
def api_loops(closed_days: int = 7):
    from .. import loops
    c = con()
    try:
        rows = loops.listing(c, include_closed_days=max(0, min(closed_days, 60)))
        last = c.execute("SELECT MAX(finished_at) FROM runs WHERE agent='assist:loops-review'").fetchone()[0]
        return _nocache({"items": rows, "reviewed_at": last})
    finally:
        c.close()


class LoopPatch(BaseModel):
    status: str
    snooze_until: Optional[str] = None
    note: Optional[str] = None


@router.patch("/api/loops/{lid}")
def api_loops_patch(lid: int, body: LoopPatch):
    from .. import loops
    c = con()
    try:
        loops.set_status(c, lid, body.status, body.snooze_until, body.note)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/loops/{lid}/distinct")
def api_loops_distinct(lid: int):
    """Sam says an item flagged as a possible duplicate is a different thing: the flag does not come back."""
    from .. import loops
    c = con()
    try:
        return {"ok": loops.mark_distinct(c, lid)}
    finally:
        c.close()


@router.get("/api/entities/{etype}/{eid}")
def api_entity(etype: str, eid: int, limit: int = 60, days: Optional[int] = None):
    """One person, organisation or initiative: who/what it is, open items with it, and its timeline across sources.
    days: everything from the last N days (up to 1,000 items) instead of the newest `limit`."""
    from datetime import datetime, timedelta, timezone
    from .. import entities, loops
    if etype not in ("person", "org", "initiative", "doc", "product", "roadmap", "ticket"):
        raise HTTPException(404)
    c = con()
    try:
        if etype == "org":
            head = entities.org_summary(c, eid)
        elif etype == "person":
            r = c.execute("SELECT id, name, title, role FROM people WHERE id=?", (eid,)).fetchone()
            head = dict(r) if r else None
        elif etype == "initiative":
            r = c.execute("SELECT id, name, weight, status FROM initiatives WHERE id=?", (eid,)).fetchone()
            head = dict(r) if r else None
        elif etype == "doc":   # a document: where it was shared or named (assist/entities.py), and who it is linked to
            r = c.execute("SELECT id, subject AS name, url, from_name, source_id FROM items WHERE id=? AND kind='doc'", (eid,)).fetchone()
            head = dict(r, kind="document", links=[x for x in entities.entities_of(c, eid) if x["confidence"] >= 0.6 or x["verdict"] == "confirmed"]) if r else None
        else:   # product, roadmap item or Jira issue (assist/refs.py)
            from .. import refs
            head = refs.get(c, eid)
            if head and head["type"] == "ticket":
                head["name"] = head["key"] + (f" · {head['name']}" if head.get("name") else "")
        if not head:
            raise HTTPException(404)
        col = {"person": "person_id", "org": "org_id"}.get(etype)
        open_items = [] if etype not in ("person", "org", "initiative") else \
            [loops._row(c, r) for r in c.execute(f"SELECT * FROM loops WHERE status='open' AND {col}=? ORDER BY origin_at", (eid,))] if col else \
            [loops._row(c, r) for r in c.execute("SELECT l.* FROM loops l JOIN mentions m ON m.ref_type='loop' AND m.ref_id=l.id AND m.entity_type='initiative' "
                                                 "WHERE l.status='open' AND m.entity_id=? ORDER BY l.origin_at", (eid,))]
        spoke = []
        if etype == "person":   # meetings where they spoke, with their main points (assist/speakers.py)
            from .. import speakers
            spoke = speakers.for_person(c, eid, limit=12)
        return _nocache({"entity": head, "type": etype, "open": open_items, "spoke": spoke, "timeline": entities.timeline(c, etype, eid, limit=1000 if days else max(1, min(limit, 200)),
                                                       since=(datetime.now(timezone.utc) - timedelta(days=min(max(days, 1), 365))).strftime("%Y-%m-%dT%H:%M:%SZ") if days else None),
                         "last_activity": entities.last_activity(c, etype, eid)})
    finally:
        c.close()


@router.post("/api/links")
async def api_link_verdict(request: Request):
    """Sam's tick or cross on one link between an item and a person, organisation or initiative (verdict null undoes it).
    A tick on a link that does not exist adds it. The linker never overrides these (assist/entities.py set_verdict)."""
    from .. import entities
    b = await request.json()
    if b.get("entity_type") not in ("person", "org", "initiative", "doc", "product", "roadmap", "ticket"):
        raise HTTPException(400)
    c = con()
    try:
        ok = entities.set_verdict(c, b.get("ref_type") or "item", int(b["ref_id"]), b["entity_type"], int(b["entity_id"]), b.get("verdict"), b.get("role"))
        c.commit()
        return {"ok": ok}
    except ValueError:
        raise HTTPException(400)
    finally:
        c.close()


@router.get("/api/links/review")
def api_links_review(n: int = 20):
    """A sample of unreviewed links to tick or cross (Check links page), spread across roles."""
    from .. import entities, evals
    c = con()
    try:
        hist = [dict(created_at=r["created_at"], **json.loads(r["metrics"] or "{}")) for r in
                c.execute("SELECT created_at, metrics FROM evals WHERE kind='links' ORDER BY created_at DESC LIMIT 30")]
        return _nocache({"sample": entities.review_sample(c, max(1, min(n, 60))), "quality": evals.eval_links(c, log=lambda *_: None, record=False),
                         "history": [{"at": h["created_at"], "precision": (h.get("precision") or {}).get("all", {}).get("precision"),
                                      "recall": (h.get("recall") or {}).get("recall")} for h in hist]})
    finally:
        c.close()


@router.get("/api/orgs")
def api_orgs():
    """Organisations with linked activity, most active first (accounts from Salesforce, partners, external domains)."""
    c = con()
    try:
        rows = c.execute("SELECT o.id, o.name, o.kind, COUNT(DISTINCT m.ref_id) AS n, MAX(i.ts) AS last FROM orgs o "
                         "JOIN mentions m ON m.entity_type='org' AND m.entity_id=o.id AND m.ref_type='item' JOIN items i ON i.id=m.ref_id "
                         "WHERE i.ts <= ? GROUP BY o.id ORDER BY last DESC", (db.now(),)).fetchall()
        return _nocache([dict(r) for r in rows])
    finally:
        c.close()
