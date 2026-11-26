"""The company emery yates and product docs, kept current (Sam, 17 Nov 2026: "Update the emery yates, the product docs,
and Salesforce too"; both were last read on 6 Oct 2026 by a hand-run session that retyped every page into a bundle, and
nothing repeated it).

The repositories come from the org pack (`kb.repos`: repo, source id, documents section, document id prefix) and are read
through its read-only knowledge-base connector (`kb.connector`): its listing gives every note's path, nothing tells what
changed, so a sync lists each repository and reads every note.
1. One short run calls the listing tool once per repository (the model sees the listing; it is small).
2. The notes to read are chosen in code (include fragments, a path part starting with "_", are left out) and read by a few
   runs side by side, each given its paths; the hook (assist/pull_hook.py) keeps every note and shows the model one line,
   so no run carries the notes in its context and the model retypes nothing.
3. The items and documents are built in code: title (frontmatter title, else the first heading, else the file name), the
   frontmatter, the text (description and body), the link the connector gives, the section (the KB's top folder; the
   product docs' first folder under docs/). A note whose text has not changed is not written again; a changed one is dated
   now (no tool gives a note's last change without one more call per note); a new one by its frontmatter date, else now.
   The first sync over notes another pull stored keeps their dates: their text was laid out differently, so nearly every
   one differs without having changed.
   A note no longer listed is removed, with its document, when its repository was listed and read to the end.
Only the listing and read tools are allowed: the connector also has tools that write, commit and delete, and they are
never given to the run. Runs weekly in the full refresh (`due()`, like Salesforce) and by hand (`assist.cli kb-sync`).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import db, org

PROMPT_VERSION = "kb-sync-2026-11-17"
AGENT = "assist:kb-sync"
EVERY_DAYS = 7
RUNS = 4              # reading runs side by side
OUTPUT_TOKENS = "200000"   # MAX_MCP_OUTPUT_TOKENS: a long note or listing is not saved to a file the run cannot read
FM = re.compile(r"^---\n(.*?)\n---\n?", re.S)
SCRATCH = Path("/tmp/assist-pull")


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repos():
    """The repositories to mirror: the org pack's kb.repos, else its one emery yates."""
    kb = org.section("kb", {})
    if kb.get("repos"):
        return [r for r in kb["repos"] if r.get("repo") and r.get("source")]
    if kb.get("folder") and kb.get("connector"):
        return [{"repo": kb["folder"], "source": kb["folder"], "section": "Emery Yates", "doc_prefix": "kb/"}]
    return []


def tool(name):
    """The connector's tool name: mcp__claude_ai_<connector, spaces as _>__<name>."""
    conn = re.sub(r"\W", "_", org.section("kb", {}).get("connector") or "")
    return f"mcp__claude_ai_{conn}__{name}" if conn else None


def due(con, days=EVERY_DAYS):
    """True when a repository has no complete sync in the last `days` days."""
    for r in repos():
        last = con.execute("SELECT MAX(finished_at) FROM pulls WHERE source_id=? AND complete=1", (r["source"],)).fetchone()[0]
        if not last:
            return True
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 86400
        except ValueError:
            return True
        if age >= days:
            return True
    return False


# ---- the runs

def list_prompt(names):
    return ("EMERY YATES listing, read only. Never write, edit, commit or delete anything. "
            f"Load {tool('igxkb_list')} with ToolSearch and call it once for each repo: {', '.join(names)} (no folder). "
            "Call no other tool. Then answer with one line: the repos and how many paths each has.")


def read_prompt(pairs):
    lines = "\n".join(json.dumps({"repo": r, "path": p}, ensure_ascii=False) for r, p in pairs)
    return ("EMERY YATES sync, read only. SleePO keeps every note these calls return and builds the records itself: do NOT copy, "
            "list or summarise notes, write files, run commands or use any other tool. Never write, edit, commit or delete anything.\n"
            f"Load {tool('igxkb_read_note')} with ToolSearch, then call it once for each repo and path below, with exactly that input. "
            "SleePO replaces each answer with one line naming the note it kept. Make up to 25 calls at once in one turn, until every "
            "line below is read. If a call fails, go on with the rest; if every call fails (sign-in, permission), say so and stop. "
            f"When done, answer with one line: notes read, notes failed.\n\n{lines}")


def _run(claude, model, prompt, allowed, env, cwd, on_result, timeout=1800):
    """One tools-only Claude run with the capture hook; returns the captured calls."""
    from . import connections, pull_hook
    SCRATCH.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="kb-sync-", dir=SCRATCH))
    try:
        cmd = [claude, "-p", prompt, "--model", model, "--permission-mode", "default", "--setting-sources", "user,project",
               "--settings", pull_hook.settings("|".join(allowed)), "--output-format", "stream-json", "--verbose",
               "--allowedTools", *allowed, "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "Task", "Agent"]
        p = subprocess.run(cmd, cwd=str(cwd or db.ASSIST), env=dict(env or os.environ, ASSIST_CAPTURE=str(folder), MAX_MCP_OUTPUT_TOKENS=OUTPUT_TOKENS),
                           capture_output=True, text=True, timeout=timeout)
        for line in (p.stdout or "").splitlines():
            connections.seen_init(line, "kb-sync")
            if on_result and '"type":"result"' in line.replace(" ", ""):
                try:
                    on_result(json.loads(line))
                except ValueError:
                    pass
        return pull_hook.load(folder)
    except subprocess.TimeoutExpired:
        return pull_hook.load(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)   # note text outside the database: never kept


# ---- building the records

def listed(calls):
    """{repo: [paths]} from the listing calls (a repo whose listing failed is absent)."""
    out = {}
    for c in calls:
        if c["tool"] == "igxkb_list":
            for o in c["objs"]:
                if isinstance(o.get("paths"), list) and o.get("repo"):
                    out[o["repo"]] = [p for p in o["paths"] if isinstance(p, str)]
    return out


def to_read(paths):
    """The notes worth reading: Markdown, no include fragments (a path part starting with "_")."""
    return [p for p in paths if p.lower().endswith((".md", ".mdx")) and not any(s.startswith("_") for s in p.split("/"))]


def parse(content):
    """(frontmatter dict, body) of a note."""
    m = FM.match(content or "")
    if not m:
        return {}, (content or "").strip()
    try:
        import yaml
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return json.loads(json.dumps({str(k): v for k, v in meta.items()}, default=str)), content[m.end():].strip()


def _section(path):
    parts = path.split("/")
    parts = parts[1:] if parts[0] == "docs" and len(parts) > 2 else parts
    if len(parts) < 2:
        return "(root)"
    s = parts[0]
    return s.replace("-", " ").title() if re.fullmatch(r"[a-z0-9-]+", s) else s


def record(repo_cfg, note, now):
    """(item, document) for one note read through the connector."""
    path, content = note["path"], note.get("content") or ""
    meta, body = parse(content)
    h1 = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), None)
    title = str(meta.get("title") or h1 or Path(path).stem)
    desc = str(meta.get("description") or "")
    date = str(meta.get("date") or "")
    ts = f"{date[:10]}T00:00:00Z" if re.match(r"\d{4}-\d\d-\d\d", date) else now
    item = {"source_id": repo_cfg["source"], "external_id": path, "kind": "doc", "ts": ts, "from_name": _section(path),
            "subject": title, "text": desc + ("\n\n" + body if body else ""), "thread": path, "url": note.get("url"),
            "noise": False, "retention": "general", "pull": 0, "payload": {"frontmatter": meta, "bytes": len(content)}}
    doc = {"id": repo_cfg.get("doc_prefix", "") + path, "section": repo_cfg.get("section") or "Emery Yates", "title": title,
           "body_md": body if body.startswith("# ") else f"# {title}\n\n{body}", "path": f"{repo_cfg['repo']}/{path}", "meta": meta}
    return item, doc


def build(cfgs, lists, calls, con, now):
    """Per repository: {items, documents, listed, read, failed, unchanged, gone}. con is read only."""
    notes = {}
    for c in calls:
        if c["tool"] == "igxkb_read_note":
            for o in c["objs"]:
                if isinstance(o.get("content"), str) and o.get("path"):
                    notes[(o.get("repo") or c["input"].get("repo"), o["path"])] = o
    out = {}
    for cfg in cfgs:
        repo = cfg["repo"]
        if repo not in lists:
            continue
        want = to_read(lists[repo])
        held = {r["external_id"]: (r["text"], r["ts"]) for r in con.execute("SELECT external_id, text, ts FROM items WHERE source_id=?", (cfg["source"],))}
        baseline = not con.execute("SELECT 1 FROM pulls WHERE source_id=? AND agent=?", (cfg["source"], AGENT)).fetchone()
        items, docs, unchanged, failed = [], [], 0, []
        for path in want:
            n = notes.get((repo, path))
            if not n:
                failed.append(path)
                continue
            item, doc = record(cfg, n, now)
            if path in held:
                if held[path][0] == item["text"]:
                    unchanged += 1
                    continue
                item["ts"] = held[path][1] if baseline else now   # changed since the last sync
            items.append(item)
            docs.append(doc)
        gone = sorted(set(held) - set(want)) if not failed else []
        out[repo] = {"cfg": cfg, "items": items, "documents": docs, "listed": len(want), "read": len(want) - len(failed),
                     "failed": failed, "unchanged": unchanged, "gone": gone}
    return out


def remove(con, source, paths, doc_prefix):
    """Notes no longer in their repository: the item, its links and its document go."""
    for p in paths:
        r = con.execute("SELECT id FROM items WHERE source_id=? AND external_id=?", (source, p)).fetchone()
        if r:
            con.execute("DELETE FROM mentions WHERE ref_type='item' AND ref_id=?", (r["id"],))
            con.execute("UPDATE fact_sources SET item_id=NULL WHERE item_id=?", (r["id"],))
            con.execute("DELETE FROM items WHERE id=?", (r["id"],))
        con.execute("DELETE FROM documents WHERE id=?", (doc_prefix + p,))


def note(b):
    return (f"{b['listed']} notes listed, {b['read']} read through the connector; {len(b['items'])} new or changed, {b['unchanged']} unchanged"
            + (f", {len(b['gone'])} no longer in the repository (removed)" if b["gone"] else "")
            + (f"; {len(b['failed'])} not read: {', '.join(b['failed'][:5])}" + (" …" if len(b["failed"]) > 5 else "") if b["failed"] else ""))


def how(con, cfg):
    """Sources' line on how this repository is read, kept in step with this module (written only when it differs)."""
    text = (f"The live '{cfg['repo']}' repository through the {org.section('kb', {}).get('connector') or 'knowledge-base'} connector, read "
            f"only: every week the full refresh lists it and reads every note (assist kb-sync); records are built in code and a note "
            f"no longer in the repository is removed.")
    r = con.execute("SELECT how FROM sources WHERE id=?", (cfg["source"],)).fetchone()
    if r and r["how"] != text:
        con.execute("UPDATE sources SET how=? WHERE id=?", (text, cfg["source"]))
        con.commit()


def run(claude=None, model=None, env=None, log=print, cwd=None, on_result=None, only=None):
    """One sync of every repository (or `only` one). Returns (ok, note)."""
    from . import ingest
    from .api import PULL_MODEL
    claude = claude or (os.path.expanduser("~/.local/bin/claude") if os.path.exists(os.path.expanduser("~/.local/bin/claude")) else "claude")
    model = model or PULL_MODEL
    cfgs = [r for r in repos() if not only or r["repo"] == only]
    if not cfgs or not tool("igxkb_list"):
        return False, "no knowledge-base repositories or connector in the org pack (kb.repos, kb.connector)"
    t0 = time.time()
    started = _iso(datetime.now(timezone.utc))
    lists = listed(_run(claude, model, list_prompt([c["repo"] for c in cfgs]), [tool("igxkb_list")], env, cwd, on_result, 600))
    missing = [c["repo"] for c in cfgs if c["repo"] not in lists]
    if missing:
        log(f"!! Emery Yates: the connector listed nothing for {', '.join(missing)}")
    pairs = [(c["repo"], p) for c in cfgs if c["repo"] in lists for p in to_read(lists[c["repo"]])]
    log(f"Emery Yates: {len(pairs)} notes in {', '.join(f'{r} ({len(to_read(lists[r]))})' for r in lists)}, read in {min(RUNS, len(pairs)) or 0} runs side by side")
    calls = []
    if pairs:
        groups = [pairs[i::RUNS] for i in range(min(RUNS, len(pairs)))]
        with ThreadPoolExecutor(len(groups)) as ex:
            calls = [c for got in ex.map(lambda g: _run(claude, model, read_prompt(g), [tool("igxkb_read_note")], env, cwd, on_result), groups) for c in got]
    finished = _iso(datetime.now(timezone.utc))
    con = db.connect()
    try:
        built = build(cfgs, lists, calls, con, finished)
        notes = []
        for repo, b in built.items():
            cfg = b["cfg"]
            complete = not b["failed"]
            text = note(b) + f" ({round(time.time() - t0)} s)"
            notes.append(f"{repo}: {text}")
            bundle = {"agent": AGENT, "prompt_version": PROMPT_VERSION, "model": model,
                      "pulls": [{"source_id": cfg["source"], "window_from": None, "window_to": started, "available": b["listed"],
                                 "pulled": b["read"], "noise": 0, "complete": complete, "note": text}],
                      "items": b["items"], "documents": b["documents"],
                      "source_health": [{"source_id": cfg["source"], "health": "ok" if complete else "partial", "last_pull_at": finished,
                                         "note": f"{b['listed']} notes in the live repository, read {finished[:10]} through the connector"
                                                 + ("" if complete else f"; {len(b['failed'])} not read")}]}
            if not complete:
                bundle["gaps"] = [f"{repo} sync of {finished[:16].replace('T', ' ')} UTC: {len(b['failed'])} notes not read"]
            path = db.ASSIST / "inbox" / "queue" / f"kb-sync-{repo}-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
            ingest.ingest_file(con, path)
            if b["gone"]:
                remove(con, cfg["source"], b["gone"], cfg.get("doc_prefix", ""))
                con.commit()
            how(con, cfg)
            log(f"Emery Yates, {repo}: {note(b)}")
        ok = bool(built) and not missing and all(not b["failed"] for b in built.values())
        return ok, "; ".join(notes) or "nothing listed"
    finally:
        con.close()
