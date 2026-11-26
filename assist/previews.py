"""Document previews inside the app, like Finder's Quick Look.

- Local PDFs and images: the file itself (the browser's own viewer).
- Local Office files (docx, pptx, xlsx, keynote…): macOS Quick Look renders an HTML preview bundle (qlmanage -p); it is
  served from a cache folder and shown in a sandboxed frame with no network access.
- Thumbnails for the list: qlmanage -t, cached.
- SharePoint / OneDrive Office files: Office for the web's embed view (best effort; needs the browser signed in to M365).
- Everything else falls back to the extracted text.

Only files Assist indexed can be previewed (ids resolve through the database, never a path from the request). Cloud-only
OneDrive files are not previewed (that would download them). The cache keeps derived copies, so entries older than
RETENTION_DAYS (assist/retention.py) are removed whenever a new one is made.
"""
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

from .retention import RETENTION_DAYS

CACHE = Path.home() / "Library" / "Caches" / "Assist" / "previews"
IMAGE = {"png", "jpg", "jpeg", "gif", "webp", "svg", "heic"}
QUICKLOOK = {"doc", "docx", "rtf", "ppt", "pptx", "xls", "xlsx", "csv", "key", "pages", "numbers", "odt", "odp", "ods", "txt", "md"}
OFFICE_WEB = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}


def _ext(name):
    return (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""


def local_path(con, doc_id):
    if not doc_id.startswith("lf-") or not doc_id[3:].isdigit():
        return None
    from . import localfiles
    r = con.execute("SELECT payload FROM items WHERE id=? AND source_id='local'", (int(doc_id[3:]),)).fetchone()
    if r and '"cloud_only": true' in (r["payload"] or ""):
        return None
    return localfiles.path_of(con, int(doc_id[3:]))


def mode(con, doc_id, name=None, url=None):
    """How the app can preview this document: pdf | image | quicklook | office-web | text."""
    p = local_path(con, doc_id) if doc_id.startswith("lf-") else None
    ext = _ext(p.name if p else name)
    if p:
        if ext == "pdf":
            return "pdf"
        if ext in IMAGE:
            return "image"
        if ext in QUICKLOOK:
            return "quicklook"
    if doc_id.startswith("sp-") and ext in OFFICE_WEB and url:
        return "office-web"
    return "text"


def office_embed(url):
    """Office for the web embed URL for a SharePoint/OneDrive file path."""
    u = urllib.parse.urlsplit(url)
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 3 or parts[0] not in ("sites", "personal"):
        return None
    site = f"/{parts[0]}/{parts[1]}"
    src = urllib.parse.quote(urllib.parse.unquote(u.path))
    return f"{u.scheme}://{u.netloc}{site}/_layouts/15/WopiFrame.aspx?sourcedoc={src}&action=embedview"


def _prune():
    cutoff = time.time() - RETENTION_DAYS * 86400
    if CACHE.exists():
        for d in CACHE.iterdir():
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink()
            except OSError:
                pass


def _slot(doc_id, p, kind):
    """Cache folder for one file version (re-rendered when the file changes)."""
    return CACHE / f"{doc_id}-{int(p.stat().st_mtime)}-{kind}"


def thumbnail(con, doc_id, size=480):
    p = local_path(con, doc_id)
    if not p:
        return None
    d = _slot(doc_id, p, f"t{size}")
    hit = list(d.glob("*.png")) if d.exists() else []
    if hit:
        return hit[0]
    d.mkdir(parents=True, exist_ok=True)
    _prune()
    subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", str(d), str(p)], capture_output=True, timeout=30)
    hit = list(d.glob("*.png"))
    return hit[0] if hit else None


def quicklook(con, doc_id):
    """The Quick Look HTML preview bundle folder for a local Office file (contains Preview.html)."""
    p = local_path(con, doc_id)
    if not p:
        return None
    d = _slot(doc_id, p, "ql")
    hit = list(d.glob("*.qlpreview"))
    if hit and (hit[0] / "Preview.html").exists():
        return hit[0]
    d.mkdir(parents=True, exist_ok=True)
    _prune()
    subprocess.run(["qlmanage", "-p", "-o", str(d), str(p)], capture_output=True, timeout=60)
    hit = list(d.glob("*.qlpreview"))
    return hit[0] if hit and (hit[0] / "Preview.html").exists() else None
