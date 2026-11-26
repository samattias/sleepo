"""Knowledge: initiatives, strategy, the soul pages, the roadmap, pipeline and retention, documents and their previews
(moved from api.py, 22 Oct 2026)."""
import re
import subprocess

from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from ..web import _nocache, con, snapshot

router = APIRouter()


@router.get("/api/initiatives")
def api_initiatives():
    """Portfolio: every active initiative with health, update age, activity, open loops and key people."""
    from .. import initiatives
    c = con()
    try:
        return _nocache(initiatives.portfolio(c))
    finally:
        c.close()


@router.get("/api/initiatives/jobs/{jid}")
def api_initiative_job(jid: str):
    from .. import initiatives
    j = initiatives.JOBS.get(jid)
    if not j:
        raise HTTPException(404)
    return _nocache({k: v for k, v in j.items() if k != "log"} | {"log": (j.get("log") or [])[-20:]})


@router.post("/api/initiatives/tag")
def api_initiatives_tag(days: int = 7):
    """Claude files new mail, chat, meetings, commitments and decisions against initiatives (no tools; nothing sent)."""
    from .. import initiatives
    return {"job": initiatives.start("tag", days=days)["id"]}


@router.get("/api/topics")
def api_topics(initiative: Optional[int] = None):
    """Top of mind (assist/topics.py): the topics Sam discussed in the last days, ranked, with how fresh they are. Reads only."""
    from .. import topics
    c = con()
    try:
        return _nocache(topics.listing(c, initiative))
    finally:
        c.close()


@router.post("/api/topics/refresh")
def api_topics_refresh(auto: int = 0):
    """Name the topics again, in the background. auto=1 (the page, on an old set): only when meetings or mail came in since."""
    from .. import topics
    return {"started": topics.spawn(force=not auto)}


@router.post("/api/topics/{tid}/{action}")
def api_topic_action(tid: int, action: str):
    """dismiss (not top of mind; later runs leave it out unless it comes up again), restore (Undo), task (Make a task),
    pin / unpin (kept first, and past runs that no longer name it)."""
    from .. import topics
    if action not in ("dismiss", "restore", "task", "pin", "unpin"):
        raise HTTPException(404)
    c = con()
    try:
        if action == "task":
            task = topics.make_task(c, tid)
            c.commit()
            return {"task": task}
        if action in ("pin", "unpin"):
            if topics.set_pin(c, tid, action == "pin"):
                c.commit()
            return {"ok": True}
        if topics.set_status(c, tid, "dismissed" if action == "dismiss" else "current"):
            c.commit()
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get("/api/initiatives/{slug}")
def api_initiative(slug: str):
    from .. import initiative_work, initiatives
    c = con()
    try:
        d = initiatives.detail(c, slug)
        if not d:
            raise HTTPException(404)
        d["work"] = initiative_work.work(c, d["id"])   # what is in progress on it: drafts and decide steps (initiative_work.py)
        return _nocache(d)
    finally:
        c.close()


@router.post("/api/initiatives/{slug}/links")
async def api_initiative_link(slug: str, request: Request):
    """Sam's verdict on one link: confirmed | rejected | null (undo). Rejected links are never re-added."""
    from .. import initiatives
    b = await request.json()
    c = con()
    try:
        if not initiatives.set_verdict(c, slug, b["ref_type"], int(b["ref_id"]), b.get("verdict")):
            raise HTTPException(400)
        c.commit()
        return {"ok": True}
    finally:
        c.close()


@router.post("/api/initiatives/{slug}/update")
def api_initiative_draft(slug: str):
    from .. import initiatives
    return {"job": initiatives.start("update", slug=slug)["id"]}


@router.post("/api/initiatives/{slug}/update/{uid}")
async def api_initiative_approve(slug: str, uid: int, request: Request):
    """Approve (optionally edited) or discard a drafted update. Approval sets the initiative's health."""
    from .. import initiatives
    b = await request.json()
    c = con()
    try:
        if b.get("discard"):
            initiatives.discard_update(c, slug, uid)
        elif not initiatives.approve_update(c, slug, uid, b):
            raise HTTPException(404)
        c.commit()
        return {"ok": True}
    finally:
        c.close()


@router.post("/api/initiatives/{slug}/ask")
async def api_initiative_ask(slug: str, request: Request):
    from .. import initiatives
    q = ((await request.json()).get("q") or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    return {"job": initiatives.start("ask", slug=slug, q=q)["id"]}


@router.get("/api/documents")
def api_documents():
    """Every document Assist pulls in from outside, with its card, preview mode and folder (assist/documents.py)."""
    from .. import documents
    c = con()
    try:
        return _nocache(documents.listing(c))
    finally:
        c.close()


class DocFolder(BaseModel):
    initiatives: Optional[list] = None
    kind: Optional[str] = None


@router.post("/api/documents/{doc_id}/folder")
def api_document_folder(doc_id: str, body: DocFolder):
    """Sam moves a document to another folder (initiative, or none): his choice wins from now on."""
    from .. import documents
    if not re.fullmatch(r"(lf|sp|ma|ca)-\d+", doc_id):
        raise HTTPException(400, "not a document that can be filed")
    c = con()
    try:
        return {"ok": True, "initiatives": documents.move(c, doc_id, body.initiatives, body.kind)}
    finally:
        c.close()


@router.get("/api/documents/{doc_id}/card")
def api_document_card(doc_id: str):
    from .. import doccards, previews
    c = con()
    try:
        card = doccards.card(c, doc_id)
        url = None
        if doc_id.startswith("sp-") and doc_id[3:].isdigit():
            r = c.execute("SELECT url FROM items WHERE id=?", (int(doc_id[3:]),)).fetchone()
            url = r["url"] if r else None
        return _nocache({"card": card, "office_embed": previews.office_embed(url) if url else None})
    finally:
        c.close()


_PREVIEW_CSP = ("default-src 'none'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
                "script-src 'self' 'unsafe-inline'; frame-src 'self'; object-src 'self'; connect-src 'none'; base-uri 'self'")


# Files from other people that can carry script (an SVG, Quick Look's HTML) are sandboxed by the response itself, so even
# when opened in their own tab they run in an opaque origin and cannot post forms to this API as the app. Quick Look keeps
# its scripts (the app's frame already allows them); an SVG gets none. PDFs are left alone: Chrome's viewer refuses a
# sandboxed document.
_PREVIEW_CSP_SVG = _PREVIEW_CSP + "; sandbox"


_PREVIEW_CSP_QL = _PREVIEW_CSP + "; sandbox allow-scripts"


@router.get("/api/preview/{doc_id}/thumb.png")
def api_preview_thumb(doc_id: str, s: int = 480):
    from .. import previews
    c = con()
    try:
        f = previews.thumbnail(c, doc_id, max(120, min(s, 1200)))
    finally:
        c.close()
    if not f:
        raise HTTPException(404)
    return FileResponse(str(f), media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/preview/{doc_id}/file")
def api_preview_file(doc_id: str):
    """The original local file, inline, for PDFs and images only (the browser shows them itself)."""
    from .. import previews
    c = con()
    try:
        p = previews.local_path(c, doc_id)
        m = previews.mode(c, doc_id) if p else None
    finally:
        c.close()
    if not p or m not in ("pdf", "image"):
        raise HTTPException(404)
    import mimetypes
    csp = _PREVIEW_CSP_SVG if p.suffix.lower() == ".svg" else _PREVIEW_CSP
    return FileResponse(str(p), media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                        headers={"Content-Disposition": "inline", "Cache-Control": "private, max-age=300", "Content-Security-Policy": csp})


@router.get("/api/preview/{doc_id}/ql/{path:path}")
def api_preview_quicklook(doc_id: str, path: str = "Preview.html"):
    """macOS Quick Look's HTML rendering of a local Office file and its attachments. Sandboxed frame; no network."""
    from .. import previews
    c = con()
    try:
        d = previews.quicklook(c, doc_id)
    finally:
        c.close()
    if not d:
        raise HTTPException(404)
    f = (d / (path or "Preview.html")).resolve()
    if not f.is_relative_to(d.resolve()) or not f.is_file():
        raise HTTPException(404)
    import mimetypes
    if f.name == "Preview.html":   # Quick Look lays slides out at a fixed width: scale the page to fit the preview pane
        html = f.read_text(errors="replace") + ("<script>(function(){function fit(){var b=document.body;b.style.zoom=1;var w=Math.max(b.scrollWidth,"
                                                "document.documentElement.scrollWidth);if(w>innerWidth+4){b.style.zoom=(innerWidth-8)/w}}"
                                                "addEventListener('load',fit);addEventListener('resize',fit)})()</script>")
        return HTMLResponse(html, headers={"Cache-Control": "private, max-age=300", "Content-Security-Policy": _PREVIEW_CSP_QL})
    return FileResponse(str(f), media_type=mimetypes.guess_type(f.name)[0] or "application/octet-stream",
                        headers={"Cache-Control": "private, max-age=300", "Content-Security-Policy": _PREVIEW_CSP_QL})


@router.get("/api/documents/{doc_id}/text")
def api_document_text(doc_id: str):
    from fastapi.responses import PlainTextResponse
    m = re.match(r"^(kb|sp|lf)-(\d+)$", doc_id)
    if not m:
        raise HTTPException(404)
    c = con()
    try:
        r = c.execute("SELECT text FROM items WHERE id=? AND kind='doc'", (int(m.group(2)),)).fetchone()
        if (not r or not r["text"]) and m.group(1) == "lf":   # a local Markdown/text file whose text was not kept: read it for the viewer
            from .. import localfiles
            f = localfiles.path_of(c, int(m.group(2)))
            if f and f.suffix.lower() in (".md", ".markdown", ".txt") and f.stat().st_size < 2_000_000:
                return PlainTextResponse(f.read_text(errors="replace"))
    finally:
        c.close()
    if not r or not r["text"]:
        raise HTTPException(404)
    return PlainTextResponse(r["text"])


@router.post("/api/local/{item_id}/open")
def api_local_open(item_id: int, reveal: int = 0):
    """Open an indexed local file in its default app, or show it in Finder. Only paths Assist indexed can be opened."""
    from .. import localfiles
    c = con()
    try:
        p = localfiles.path_of(c, item_id)
    finally:
        c.close()
    if not p:
        raise HTTPException(404)
    subprocess.run(["open", "-R", str(p)] if reveal else ["open", str(p)], check=False, timeout=15)
    return {"ok": True}


@router.get("/api/docs")
def api_docs():
    return _nocache([{k: v for k, v in x.items() if k != "md"} for x in snapshot()["docs"]])


@router.get("/api/souls")
def api_souls():
    """The soul pages and which agents read which part of them (assist/soul.py)."""
    from .. import soul
    return _nocache(soul.uses())


@router.get("/api/docs/{doc_id:path}")
def api_doc(doc_id: str):
    x = next((d for d in snapshot()["docs"] if d["id"] == doc_id), None)
    if not x:
        raise HTTPException(404)
    return _nocache(x)


@router.get("/api/pipeline")
def api_pipeline():
    """Open Salesforce opportunities (company and deal data only) with approximate USD values and data-quality flags."""
    from .. import pipeline
    c = con()
    try:
        return _nocache(pipeline.listing(c))
    finally:
        c.close()


@router.get("/api/pipeline/closed")
def api_pipeline_closed():
    """Closed Won / Lost Salesforce deals since Q1 2026 (company and deal data only) for the Pipeline history tab."""
    from .. import pipeline
    c = con()
    try:
        return _nocache(pipeline.closed(c))
    finally:
        c.close()


@router.get("/api/retention")
def api_retention():
    """Revenue retention from Salesforce renewals: renewal-book and company GRR / NRR this year, and next year's outlook."""
    from .. import renewals
    c = con()
    try:
        return _nocache(renewals.summary(c))
    finally:
        c.close()


@router.get("/api/strategy")
def api_strategy():
    """The latest strategy memo (and earlier ones, newest first), with Sam's marks."""
    from .. import strategy
    c = con()
    try:
        return _nocache({"memos": strategy.latest(c, 8) or []})
    finally:
        c.close()


class StrategyMark(BaseModel):
    index: int
    mark: str = ""


@router.post("/api/strategy/{memo_id}/mark")
def api_strategy_mark(memo_id: int, body: StrategyMark):
    from .. import strategy
    c = con()
    try:
        return {"marks": strategy.mark(c, memo_id, body.index, body.mark)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get("/api/roadmap")
def api_roadmap():
    """The product roadmap (Rowan Lowell's Roadmap Workbook workbook): every initiative and the source it came from."""
    from .. import roadmap
    c = con()
    try:
        return _nocache(roadmap.listing(c))
    finally:
        c.close()


@router.get("/api/roadmap/refresh")
def api_roadmap_refresh_state():
    """Roadmap › Refresh: the last or current read of Rowan's workbook (assist/roadmap.py). Reads a job file only."""
    from .. import roadmap
    return _nocache(roadmap.state())


@router.post("/api/roadmap/refresh")
def api_roadmap_refresh():
    """Start reading the latest Initiatives sheet of Rowan's workbook in the background (a minute or two), or report the run going."""
    from .. import roadmap
    return _nocache(roadmap.start())
