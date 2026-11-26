"""Open a prompt in the Claude desktop app, optionally with a document attached, from an action in a meeting brief.

Uses the app's own URL scheme (no shell, no tools granted by us):
  claude://cowork/new?q=<prompt>&folder=<workspace>&file=<document>   Cowork task: create or edit documents
  claude://claude.ai/new?q=<prompt>                                   a plain chat
Documents are attached as real files. A file on this Mac is attached where it is; an email attachment we hold as an
original file is copied into the workspace (so the archive copy is never edited); anything we only hold as extracted
text is written to the workspace as Markdown with a note saying so. The workspace lives outside OneDrive
(~/SleePO Workspace/<date>/) and folders older than RETENTION_DAYS (assist/retention.py) are removed.
"""
import re
import shutil
import subprocess
import time
import urllib.parse
from datetime import date
from pathlib import Path

from . import localfiles, mailsync
from .retention import RETENTION_DAYS

WORKSPACE = Path.home() / "SleePO Workspace"
MAX_PROMPT = 14000   # the desktop app truncates q beyond ~14k characters


def _safe(name):
    return re.sub(r"[^\w.\- ()&+,]", "_", name or "document").strip()[:120] or "document"


def _prune():
    if not WORKSPACE.exists():
        return
    cutoff = time.time() - RETENTION_DAYS * 86400
    for d in WORKSPACE.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def workspace(label=""):
    d = WORKSPACE / (date.today().isoformat() + (f" {_safe(label)[:60]}" if label else ""))
    d.mkdir(parents=True, exist_ok=True)
    return d


def materialize(con, doc_id, ws):
    """A local file path for document doc_id, plus a short note on what it is."""
    m = re.fullmatch(r"(lf|ma|sp|kb|ca)-(\d+)", doc_id or "")
    if not m:
        return None, ""
    kind, n = m.group(1), int(m.group(2))
    if kind == "lf":
        p = localfiles.path_of(con, n)
        return (p, "the original file on this Mac") if p else (None, "")
    if kind == "ma":
        r = con.execute("SELECT a.name, a.path, a.text, m.subject, m.web_link FROM mail_attachments a JOIN mail_messages m ON m.item_id=a.item_id WHERE a.id=?", (n,)).fetchone()
        if not r:
            return None, ""
        if r["path"] and (mailsync.attachments_dir() / r["path"]).exists():
            dst = ws / _safe(r["name"])
            shutil.copy2(mailsync.attachments_dir() / r["path"], dst)
            return dst, "a copy of the original attachment"
        if r["text"]:
            dst = ws / (_safe(r["name"]) + ".md")
            dst.write_text(f"<!-- Extracted text of the email attachment “{r['name']}” on “{r['subject']}”. "
                           f"Formatting is lost; the original is in Outlook: {r['web_link'] or ''} -->\n\n{r['text']}")
            return dst, "the extracted text of the attachment (formatting lost; the original is in Outlook)"
        return None, ""
    if kind in ("sp", "kb"):
        r = con.execute("SELECT subject, url, text FROM items WHERE id=?", (n,)).fetchone()
        if r and r["text"]:
            dst = ws / (_safe(r["subject"]) + ("" if r["subject"].lower().endswith(".md") else ".md"))
            dst.write_text(f"<!-- Text Assist holds for “{r['subject']}”; the original: {r['url'] or ''} -->\n\n{r['text']}")
            return dst, "the text Assist holds for it (the original is linked inside)"
    return None, ""


def copy_into(con, doc_id, folder):
    """A working copy of document doc_id inside folder (never the original), or None."""
    folder.mkdir(parents=True, exist_ok=True)
    p, _ = materialize(con, doc_id, folder)
    if p and folder not in p.parents:   # a file on this Mac is materialized where it is: copy it
        dst = folder / _safe(p.name)
        shutil.copy2(p, dst)
        p = dst
    return p


def open_in_claude(con, prompt, app="cowork", doc=None, label="", ws=None, copy=False):
    """ws: the workspace folder to open (the Actions page writes its context pack there first); copy: attach a working
    copy of a local file instead of the original."""
    _prune()
    prompt = (prompt or "").strip()
    attached, note = None, ""
    ws = (ws or workspace(label)) if app == "cowork" else None
    if doc and ws and copy:
        attached, note = copy_into(con, doc, ws), "a working copy in this folder (the original is untouched)"
    elif doc and ws:
        attached, note = materialize(con, doc, ws)
        if attached:
            prompt += f"\n\n(The attached file is {note}.)"
    prompt = prompt[:MAX_PROMPT]
    if app == "cowork":
        params = [("q", prompt), ("folder", str(ws))] + ([("file", str(attached))] if attached else [])
        url = "claude://cowork/new?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    else:
        url = "claude://claude.ai/new?" + urllib.parse.urlencode([("q", prompt)], quote_via=urllib.parse.quote)
    subprocess.run(["/usr/bin/open", url], check=False, timeout=15)   # argument list: nothing reaches a shell
    return {"ok": True, "app": app, "attached": str(attached) if attached else None, "workspace": str(ws) if ws else None, "prompt_chars": len(prompt)}
