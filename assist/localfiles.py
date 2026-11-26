"""Local files as a source: documents in ~/Downloads, ~/Desktop and ~/Documents (the OneDrive Documents folder).

  assist scan-local        index the folders; incremental and idempotent, removes files that are gone

What is kept, and why (minimum data):
- every matching file: name, folder, size, type, modified date (source 'local', kind 'doc');
- extracted text (max 20 000 characters) only for files modified in the last RETENTION_DAYS (assist/retention.py, the
  Acme rule for derived data); older files keep metadata only and their text is dropped on the next scan;
- OneDrive files that are only in the cloud are never downloaded to read them: metadata only.
Skipped: Assist itself (private notes), sources already pulled elsewhere (Granola Export, the KB vault, files the
SharePoint/OneDrive source already has), code and app folders, HR / investigation and obviously personal folders.
"""
import os
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import db
from . import org
from . import profile
from .retention import RETENTION_DAYS

import logging
logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings are noise for text extraction

HOME = Path.home()
ROOTS = [("Downloads", HOME / "Downloads"), ("Desktop", HOME / "Desktop"), ("Documents", HOME / "Documents")]
EXTS = {"pdf", "doc", "docx", "rtf", "odt", "pages", "ppt", "pptx", "key", "odp", "xls", "xlsx", "csv", "numbers", "ods", "md", "txt"}
SKIP_NAMES = {"node_modules", ".git", ".next", "venv", ".venv", "__pycache__", "dist", "build", ".cache", "Library", "$RECYCLE.BIN"}
SKIP_REL = {"Documents/Assist", "Documents/Granola Export", "Documents/" + (org.section("kb", {}).get("folder") or "kb")}
PRIVATE = profile.FieldPattern("private_files", prefix=r"investigation|enqu[eê]te|\bhr\b|personal|private|\bperso\b|medical|m[ée]dical|health|sant[ée]|passport|passeport|"
                     r"\btax\b|imp[oô]ts?|bank|banque|payslip|bulletins? de (paie|salaire)")   # + the user's own (the profile)
MAX_TEXT = 20000
SF_DATALESS = 0x40000000  # macOS: placeholder whose content lives only in the cloud


# ---------------------------------------------------------------- text
def _xml_text(z, names, tag):
    out = []
    for n in names:
        xml = z.read(n).decode("utf-8", "ignore")
        xml = re.sub(r"</(w:p|a:p|si|row)>", "\n", xml)
        out.append(" ".join(re.findall(rf"<{tag}[^>]*>([^<]*)</{tag}>", xml)).replace(" \n", "\n"))
    return "\n".join(out)


def html_text(html):
    """The readable text of an HTML page: no scripts, styles or tags; block elements end a line."""
    import html as _h
    t = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", html)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article|table|ul|ol)>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = _h.unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(x for x in (re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in t.splitlines()) if x)


def extract(path, ext):
    try:
        if ext in ("md", "txt", "csv"):
            return path.read_text(errors="ignore")[:MAX_TEXT]
        if ext in ("html", "htm"):
            return html_text(path.read_text(errors="ignore"))[:MAX_TEXT]
        if ext == "docx":
            with zipfile.ZipFile(path) as z:
                return _xml_text(z, ["word/document.xml"], "w:t")[:MAX_TEXT]
        if ext == "pptx":
            with zipfile.ZipFile(path) as z:
                slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
                return _xml_text(z, slides, "a:t")[:MAX_TEXT]
        if ext == "xlsx":
            with zipfile.ZipFile(path) as z:
                return _xml_text(z, [n for n in z.namelist() if n == "xl/sharedStrings.xml"], "t")[:MAX_TEXT]
        if ext == "pdf":
            from pypdf import PdfReader
            r = PdfReader(str(path))
            out = []
            for p in r.pages[:40]:
                out.append(p.extract_text() or "")
                if sum(map(len, out)) > MAX_TEXT:
                    break
            return "\n".join(out)[:MAX_TEXT]
        if ext in ("doc", "rtf", "odt"):
            r = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, text=True, timeout=60)
            return r.stdout[:MAX_TEXT]
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- scan
def _walk(label, root):
    base = root.resolve()
    for dirpath, dirnames, filenames in os.walk(base):
        d = Path(dirpath)
        rel_dir = (label + "/" + str(d.relative_to(base))).rstrip("/.").rstrip("/")
        dirnames[:] = [n for n in dirnames if not n.startswith(".") and n not in SKIP_NAMES and not n.endswith((".app", ".photoslibrary", ".bundle"))
                       and f"{rel_dir}/{n}" not in SKIP_REL and not PRIVATE.search(n)]
        for f in filenames:
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in EXTS and not f.startswith(("~$", ".")) and not PRIVATE.search(f):
                yield rel_dir, d / f, ext


def _onedrive_known(con):
    """Files the SharePoint/OneDrive source already has, as 'folder/name' relative to the OneDrive Documents root."""
    known = set()
    for r in con.execute("SELECT subject, thread FROM items WHERE source_id='sharepoint'"):
        m = re.match(r"^/personal/[^/]+/Documents/?(.*)$", r["thread"] or "")
        if m:
            known.add(("Documents/" + m.group(1)).rstrip("/") + "/" + (r["subject"] or ""))
    return known


def _source(con):
    db.upsert_source(con, {"id": "local", "system": "local", "name": "Local files", "vendor": "This Mac", "kind": "Documents in Downloads, Desktop and Documents",
                           "how": "assist scan-local walks ~/Downloads, ~/Desktop and ~/Documents (OneDrive) on every Refresh. Name, folder, size, type and date for "
                                  "every document; text only for files modified in the last 30 days. Skips Assist, Granola Export, the KB vault, files the "
                                  "SharePoint source already has, code folders, HR/investigation and personal folders, and cloud-only OneDrive files' contents.",
                           "auth": "none (local disk)", "connect": "always on", "color": "#3a3a3a", "mono": "LF", "logo": None, "sort": 80})


def scan(con, log=print):
    _source(con)
    days = RETENTION_DAYS
    window = time.time() - days * 86400 if days else 0
    known = _onedrive_known(con)
    pull = db.start_pull(con, "local", "assist scan-local", None, db.now(), "Downloads, Desktop, Documents")
    seen, n, with_text, skipped_dup, cloud_only = set(), 0, 0, 0, 0
    for label, root in ROOTS:
        if not root.exists():
            continue
        for rel_dir, p, ext in _walk(label, root):
            rel = f"{rel_dir}/{p.name}"
            if label == "Documents" and rel in known:
                skipped_dup += 1
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            dataless = bool(getattr(st, "st_flags", 0) & SF_DATALESS)
            cloud_only += dataless
            recent = st.st_mtime >= window
            ext_id = "file:" + str(p)
            seen.add(ext_id)
            row = con.execute("SELECT id, payload FROM items WHERE source_id='local' AND external_id=?", (ext_id,)).fetchone()
            unchanged = row and f'"mtime": {int(st.st_mtime)},' in (row["payload"] or "")
            text = None
            if recent and not dataless and not unchanged:
                text = extract(p, ext)
            ts = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            iid, _ = db.upsert_item(con, "local", ext_id, "doc", ts, pull_id=pull, from_name=label, subject=p.name, text=text,
                                    thread=rel_dir, payload={"mtime": int(st.st_mtime), "size": st.st_size, "ext": ext, "cloud_only": dataless})
            if not recent:  # outside the retention window: metadata only
                con.execute("UPDATE items SET text=NULL WHERE id=? AND text IS NOT NULL", (iid,))
            n += 1
            with_text += bool(text) or bool(unchanged and recent)
    gone = [r["id"] for r in con.execute("SELECT id, external_id FROM items WHERE source_id='local'") if r["external_id"] not in seen]
    for iid in gone:
        con.execute("DELETE FROM mentions WHERE ref_type='item' AND ref_id=?", (iid,))
        con.execute("UPDATE fact_sources SET item_id=NULL WHERE item_id=?", (iid,))
        con.execute("DELETE FROM items WHERE id=?", (iid,))
    db.finish_pull(con, pull, available=n + skipped_dup, pulled=n, noise=skipped_dup, complete=1)
    con.execute("UPDATE sources SET health='ok', note=? WHERE id='local'",
                (f"{n} files · {skipped_dup} already in SharePoint/OneDrive · {cloud_only} cloud-only (metadata) · text kept {days or 'unlimited'} days",))
    con.commit()
    log(f"local files: {n} indexed ({skipped_dup} skipped as already in SharePoint/OneDrive, {cloud_only} cloud-only), {len(gone)} removed")
    return n


def path_of(con, item_id):
    r = con.execute("SELECT external_id FROM items WHERE id=? AND source_id='local'", (item_id,)).fetchone()
    p = Path(r["external_id"][5:]) if r and r["external_id"].startswith("file:") else None
    return p if p and p.exists() else None
