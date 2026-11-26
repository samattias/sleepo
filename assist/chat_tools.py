"""Tools the in-app chat (assist/chat.py) runs through `assist.cli`, beyond search and SQL.

Reading (never stored, nothing changes):
- ask-read <ref>   one thing in full, not clipped: a mail or message (its item id, or an app link like #/inbox?open=123), a
                   meeting (m-45: notes, attendees and transcript), a document (sp-12, kb-12, lf-12, or a library id
                   such as pd/docs/….md for a product docs page, and the links search gives) or an open item (l-7).
- ask-file <path>  the text of a Word, Excel (every sheet, with its numbers), PowerPoint, PDF or text file on this Mac:
                   Downloads, Desktop, Documents/OneDrive and ~/SleePO Workspace. The HR investigation folder is refused.

Making files, only inside the conversation's own workspace folder (ASSIST_CHAT_WORKSPACE, set by chat.stream; it lives in
~/SleePO Workspace, outside OneDrive, and is deleted after RETENTION_DAYS):
- ask-copy <path>          a working copy of a file into the workspace, so the original is never edited
- ask-make <file> <format> a Word document from Markdown or HTML (macOS textutil), or an Excel workbook from CSV
"""
import csv
import io
import os
import shutil
import json
import re
import subprocess
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import db
from .retention import RETENTION_DAYS

HOME = Path.home()
MAX = 60000
FILE_ROOTS = [HOME / "Downloads", HOME / "Desktop", HOME / "Documents", HOME / "SleePO Workspace", HOME / "Library" / "CloudStorage"]
EXCLUDED = re.compile(r"investigation|enqu[eê]te", re.I)   # excluded by design (assistant soul: Privacy and retention)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _clip(s, n=MAX):
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n… cut at {n:,} of {len(s):,} characters"


# ---------------------------------------------------------------- ask-read

def ask_read(ref):
    """One thing in full by its reference or app link. A library document's id holds slashes (product docs pages are
    pd/docs/desktop-client/….md, knowledge base notes kb/…) and search links it as /explore/library/<id>; SharePoint, KB
    and local files come as doc:sp-12. Until 17 Nov 2026 only the last part of a path was looked up, so the chat found
    product docs pages by search but could not open one."""
    ref = (ref or "").strip().strip("\"'").lstrip("#")
    m = re.search(r"[?&](?:open|item)=([\w.-]+)", ref)
    lib = re.search(r"explore/library/([^?#]+)", ref)
    con = db.connect()
    try:
        if m:
            ref = m.group(1)
        elif lib:
            ref = urllib.parse.unquote(lib.group(1)).rstrip("/")
        else:
            ref = re.sub(r"^doc:", "", ref)
            if not con.execute("SELECT 1 FROM documents WHERE id=?", (ref,)).fetchone():
                ref = ref.rstrip("/").rsplit("/", 1)[-1]
        if re.fullmatch(r"m-\d+", ref):
            return _meeting(con, int(ref[2:]))
        if re.fullmatch(r"(sp|kb|lf)-\d+", ref):
            return _item(con, int(ref.split("-")[1]))
        if re.fullmatch(r"l-\d+", ref):
            return _loop(con, int(ref[2:]))
        if re.fullmatch(r"\d+", ref):
            return _item(con, int(ref))
        d = con.execute("SELECT title, path, body_md FROM documents WHERE id=?", (ref,)).fetchone()
        if d:
            return _clip(f"# {d['title']}\n{d['path'] or ''}\n\n{d['body_md'] or ''}")
        return (f"Nothing found for “{ref}”. Use an item id (123), m-45, sp-12, kb-12, lf-12, l-7, a document's id "
                "(pd/docs/….md), or the link search gave.")
    finally:
        con.close()


def _item(con, iid):
    it = con.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not it:
        return f"No item {iid}."
    head = [f"{it['kind']} · {it['source_id']} · {it['ts'] or ''}", f"Subject: {it['subject'] or ''}", f"From: {it['from_name'] or ''}"]
    body = it["text"] or ""
    mm = con.execute("SELECT * FROM mail_messages WHERE item_id=?", (iid,)).fetchone()
    if mm:
        to = ", ".join(a.get("name") or a.get("address", "") for a in json.loads(mm["to_json"] or "[]"))
        cc = ", ".join(a.get("name") or a.get("address", "") for a in json.loads(mm["cc_json"] or "[]"))
        head += [f"From address: {mm['from_address'] or ''}", f"To: {to}", f"Cc: {cc}", f"Folder: {mm['folder'] or ''}"]
        body = mm["body_text"] or mm["preview"] or body
        if not mm["body_text"]:
            head.append(f"(Only the preview is stored: full mail text is kept for {RETENTION_DAYS} days.)")
    cm = con.execute("SELECT * FROM chat_messages WHERE item_id=?", (iid,)).fetchone()
    if cm:
        head += [f"Conversation: {cm['conversation_name'] or ''} ({cm['conversation_kind'] or ''})", f"Author: {cm['author'] or ''}"]
        body = cm["body_text"] or body
    if it["url"]:
        head.append(f"Link: {it['url']}")
    return _clip("\n".join(head) + "\n\n" + body)


def _meeting(con, mid):
    m = con.execute("SELECT m.*, i.external_id, i.url, i.text AS note FROM meetings m JOIN items i ON i.id=m.note_item_id WHERE m.id=?", (mid,)).fetchone()
    if not m:
        return f"No meeting m-{mid}."
    if m["status"] == "personal":
        return "That is a personal meeting: out of scope by design."
    out = [f"# {m['title'] or ''}", f"{m['starts_at'] or ''} · attendees: {', '.join(json.loads(m['attendees'] or '[]'))}", f"Granola: {m['url'] or ''}", "",
           "## Notes", m["digest_md"] or m["note"] or "(no notes)"]
    from .views import GRANOLA
    short = (m["external_id"] or "")[-6:]
    t = next(iter((GRANOLA / "transcripts").glob(f"*[[]{short}].md")), None) if short and (GRANOLA / "transcripts").exists() else None
    if t:
        out += ["", f"## Transcript ({t.name})", t.read_text(errors="ignore")]
    return _clip("\n".join(out))


def _loop(con, lid):
    r = con.execute("SELECT l.*, p.name AS person FROM loops l LEFT JOIN people p ON p.id=l.person_id WHERE l.id=?", (lid,)).fetchone()
    if not r:
        return f"No open item {lid}."
    keep = ["kind", "title", "detail", "person", "counterpart", "due", "origin_at", "status", "suggestion", "suggestion_note", "closed_by", "close_reason", "links_json", "said_json"]
    return "\n".join(f"{k}: {r[k]}" for k in keep if r[k] not in (None, ""))


# ---------------------------------------------------------------- ask-file

def allowed_path(path, roots=None):
    """The resolved path when it is inside one of the roots and not excluded, else None."""
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    if EXCLUDED.search(str(p)):
        return None
    for root in roots or FILE_ROOTS:
        try:
            p.relative_to(root.resolve())
            return p
        except (ValueError, OSError):
            continue
    return None


def ask_file(path):
    p = allowed_path(path)
    if not p:
        return "That path is outside Downloads, Desktop, Documents/OneDrive and ~/SleePO Workspace, or is excluded."
    if p.is_dir():
        files = sorted((f for f in p.iterdir() if not f.name.startswith((".", "~$"))), key=lambda f: f.name.lower())[:200]
        return "\n".join(f"{'[dir] ' if f.is_dir() else ''}{f.name}" for f in files) or "(empty folder)"
    if not p.exists():
        return f"No such file: {p}"
    if p.name.startswith("~$"):
        return f"{p.name} is an Office lock file (the document is open in Word, Excel or PowerPoint); read {p.name[2:]} instead."
    ext = p.suffix.lower().lstrip(".")
    try:
        if ext == "xlsx" or ext == "xlsm":
            text = _xlsx(p)
        elif ext == "docx":
            text = _docx(p)
        elif ext == "pptx":
            text = _pptx(p)
        elif ext == "pdf":
            from pypdf import PdfReader
            text = "\n\n".join(f"--- page {i + 1} ---\n{pg.extract_text() or ''}" for i, pg in enumerate(PdfReader(str(p)).pages[:200]))
        elif ext in ("md", "txt", "csv", "tsv", "json", "html", "htm"):
            text = p.read_text(errors="ignore")
        elif ext in ("doc", "rtf", "odt", "pages", "wordml", "webarchive"):
            text = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", str(p)], capture_output=True, text=True, timeout=60).stdout
        else:
            return f"Cannot read .{ext} files from the chat. Word, Excel, PowerPoint, PDF and text files work."
    except Exception as e:
        return f"Could not read {p.name}: {e}"
    return _clip(f"{p}\n\n{text}")


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref or "A").group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _xlsx(p):
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        shared = [("".join(t.text or "" for t in si.iter(S + "t"))) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(S + "si")] \
            if "xl/sharedStrings.xml" in names else []
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        out = []
        for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(S + "sheet"):
            target = rels.get(sh.get(R + "id"), "")
            part = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if part not in names:
                continue
            rows = []
            for row in ET.fromstring(z.read(part)).iter(S + "row"):
                cells = {}
                for c in row.findall(S + "c"):
                    t, v = c.get("t"), c.find(S + "v")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(S + "t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    if val != "":
                        cells[_col(c.get("r"))] = val.replace("\t", " ").replace("\n", " ")
                if cells:
                    rows.append("\t".join(cells.get(i, "") for i in range(max(cells) + 1)))
            out.append(f"## Sheet: {sh.get('name')} ({len(rows)} rows; dates are Excel serial numbers)\n" + "\n".join(rows))
        return "\n\n".join(out)


def _docx(p):
    with zipfile.ZipFile(p) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    out = []
    for el in body:
        if el.tag == W + "p":
            text = "".join(t.text or "" for t in el.iter(W + "t"))
            style = el.find(f"{W}pPr/{W}pStyle")
            lvl = re.search(r"Heading(\d)", style.get(W + "val") or "") if style is not None else None
            out.append(("#" * int(lvl.group(1)) + " " if lvl else "") + text)
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                out.append("| " + " | ".join("".join(t.text or "" for t in tc.iter(W + "t")) for tc in tr.findall(W + "tc")) + " |")
    return "\n".join(out)


def _pptx(p):
    with zipfile.ZipFile(p) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
        out = []
        for i, n in enumerate(slides, 1):
            paras = ["".join(t.text or "" for t in para.iter(A + "t")) for para in ET.fromstring(z.read(n)).iter(A + "p")]
            out.append(f"--- slide {i} ---\n" + "\n".join(x for x in paras if x.strip()))
        return "\n\n".join(out)


# ---------------------------------------------------------------- making files (the conversation's workspace only)

def workspace():
    """The conversation's folder, and only if it really is one of SleePO's workspace folders."""
    from .claude_open import WORKSPACE
    ws = os.environ.get("ASSIST_CHAT_WORKSPACE")
    if not ws or not Path(ws).is_dir():
        return None
    p = Path(ws).resolve()
    try:
        p.relative_to(WORKSPACE.resolve())
    except ValueError:
        return None
    return p if p != WORKSPACE.resolve() else None


def ask_copy(path):
    ws = workspace()
    if not ws:
        return "This conversation has no workspace folder."
    src = allowed_path(path)
    if not src or not src.is_file():
        return "That file is outside Downloads, Desktop, Documents/OneDrive and ~/SleePO Workspace, is excluded, or does not exist."
    dst = ws / src.name
    if dst.resolve() == src:
        return f"{src.name} is already in the workspace."
    n = 2
    while dst.exists():
        dst = ws / f"{src.stem} ({n}){src.suffix}"
        n += 1
    shutil.copy2(src, dst)
    return f"Copied to {dst} (the original is untouched). Edit or rebuild the copy, never the original."


def ask_make(path, fmt):
    ws = workspace()
    if not ws:
        return "This conversation has no workspace folder."
    src = allowed_path(path if os.path.isabs(os.path.expanduser(path)) else ws / path, [ws])
    if not src or not src.is_file():
        return f"Make files from a file inside the workspace ({ws})."
    fmt = fmt.lower().lstrip(".")
    ext = src.suffix.lower().lstrip(".")
    out = src.with_suffix("." + fmt)
    if fmt in ("docx", "rtf", "odt"):
        if ext not in ("md", "markdown", "html", "htm", "txt"):
            return "Word documents are made from a .md, .html or .txt file."
        html = src
        if ext in ("md", "markdown", "txt"):
            html = src.with_suffix(".tmp.html")
            html.write_text(md_to_html(src.read_text(errors="ignore"), src.stem))
        r = subprocess.run(["/usr/bin/textutil", "-convert", fmt, "-output", str(out), str(html)], capture_output=True, text=True, timeout=60)
        if html != src:
            html.unlink(missing_ok=True)
        if r.returncode != 0:
            return f"Could not make {out.name}: {r.stderr.strip()[:300]}"
    elif fmt == "xlsx":
        if ext not in ("csv", "tsv"):
            return "Excel workbooks are made from a .csv or .tsv file (first row = headings)."
        rows = list(csv.reader(io.StringIO(src.read_text(errors="ignore")), delimiter="\t" if ext == "tsv" else ","))
        write_xlsx(out, rows, src.stem[:31])
    else:
        return "Formats: docx (from .md, .html or .txt), rtf, odt, xlsx (from .csv or .tsv)."
    return f"Made {out} ({out.stat().st_size:,} bytes)."


def _inline(s):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)


def md_to_html(md, title=""):
    """Enough Markdown for a document: headings, paragraphs, bullet and numbered lists, tables, bold, italics, links."""
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        h = re.match(r"(#{1,6})\s+(.*)", line)
        if h:
            out.append(f"<h{len(h.group(1))}>{_inline(h.group(2))}</h{len(h.group(1))}>")
            i += 1
        elif line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            body = "".join("<tr>" + "".join(f"<{'th' if r == 0 else 'td'}>{_inline(c)}</{'th' if r == 0 else 'td'}>" for c in row) + "</tr>"
                           for r, row in enumerate(rows))
            out.append(f'<table border="1" cellpadding="4" cellspacing="0">{body}</table>')
        elif re.match(r"\s*([-*+]|\d+[.)])\s+", line):
            tag = "ol" if re.match(r"\s*\d+[.)]", line) else "ul"
            items = []
            while i < len(lines) and re.match(r"\s*([-*+]|\d+[.)])\s+", lines[i]):
                items.append("<li>" + _inline(re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", lines[i])) + "</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,6}\s|\s*\||\s*([-*+]|\d+[.)])\s)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{_inline(title)}</title>'
            '<style>body{font-family:Calibri,Arial,sans-serif;font-size:11pt}</style></head><body>' + "\n".join(out) + "</body></html>")


def write_xlsx(path, rows, sheet="Sheet1"):
    """A plain workbook: one sheet, the first row bold, numbers as numbers."""
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def cell(r, c, v):
        ref = ""
        n = c + 1
        while n:
            n, rem = divmod(n - 1, 26)
            ref = chr(65 + rem) + ref
        ref += str(r + 1)
        style = ' s="1"' if r == 0 else ""
        if r > 0 and re.fullmatch(r"-?\d+(\.\d+)?", v.strip() or "x"):
            return f'<c r="{ref}"{style}><v>{v.strip()}</v></c>'
        return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{esc(v)}</t></is></c>'

    data = "".join(f'<row r="{r + 1}">' + "".join(cell(r, c, v) for c, v in enumerate(row)) + "</row>" for r, row in enumerate(rows))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8"?><workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{esc(sheet or "Sheet1")}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": f'<?xml version="1.0" encoding="UTF-8"?><styleSheet {ns}><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf/><xf fontId="1" applyFont="1"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>{data}</sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, xml in parts.items():
            z.writestr(name, xml)
