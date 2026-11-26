#!/usr/bin/env python3
"""Bundle the Assist folder into one self-contained HTML page: Assist.html

Everything the assistant has pulled or written (briefs, tasks, decisions, inbox digests,
live-pull snapshots, drafts, memory) is embedded as data and rendered client-side.
Open the file by double-clicking; no server, no network needed except the markdown
renderer from cdnjs (falls back to plain text when offline).

Usage: python3 scripts/build_ui.py      (sync.sh and the skills call this automatically)
"""
import json
import re
from datetime import datetime
from pathlib import Path

ASSIST = Path(__file__).resolve().parent.parent
OUT = ASSIST / "Assist.html"
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/London")
except Exception:
    TZ = None

FM = re.compile(r"^---\n(.*?)\n---\n", re.S)


def read(path):
    text = path.read_text(errors="replace")
    meta = {}
    m = FM.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        text = text[m.end():]
    return text, meta


def title_of(path, text, meta):
    if meta.get("title"):
        return meta["title"]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def doc(path, section, label=None):
    text, meta = read(path)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, TZ)
    return {
        "id": str(path.relative_to(ASSIST)),
        "section": section,
        "title": label or title_of(path, text, meta),
        "path": str(path.relative_to(ASSIST)),
        "mtime": mtime.strftime("%Y-%m-%d %H:%M"),
        "meta": meta,
        "md": text,
        "words": len(text.split()),
    }


def meetings_index():
    """One table row per Granola note: date, title, attendees, links to the local transcript and the Granola page."""
    raw = ASSIST.parent / "Granola Export" / "raw-json"
    tdir = ASSIST.parent / "Granola Export" / "transcripts"
    import urllib.parse
    rows, notes = [], []
    for p in raw.glob("*.json"):
        try:
            notes.append(json.loads(p.read_text()))
        except Exception:
            continue
    state_path = ASSIST / "inbox" / "granola" / ".state.json"
    digested = set(json.loads(state_path.read_text()).get("digested", [])) if state_path.exists() else set()
    by_id = {}
    for t in tdir.glob("*.md"):
        m = re.search(r"\[([A-Za-z0-9]{6})\]\.md$", t.name)
        if m:
            by_id[m.group(1)] = t
    personal = re.compile(r"Robin|Terry", re.I)
    for n in sorted(notes, key=lambda n: n.get("created_at", ""), reverse=True):
        created = n.get("created_at", "")[:10]
        title = (n.get("title") or "Untitled").replace("|", "/")
        names = [a.get("name") for a in (n.get("attendees") or []) if a.get("name") and a.get("name") != "Sam Doe"]
        t = by_id.get(n["id"][-6:])
        local = f"[transcript](../Granola%20Export/transcripts/{urllib.parse.quote(t.name)})" if t else ""
        status = "personal, skipped" if personal.search(title) else ("analysed" if n["id"] in digested else "not yet")
        segs = len(n.get("transcript") or [])
        rows.append(f"| {created} | {title} | {', '.join(names) or '—'} | {segs} | {status} | {local} [Granola]({n.get('web_url','')}) |")
    months = {}
    for n in notes:
        months[n.get("created_at", "")[:7]] = months.get(n.get("created_at", "")[:7], 0) + 1
    month_line = " · ".join(f"{k}: {v}" for k, v in sorted(months.items()))
    md = (f"# All meetings · {len(notes)} Granola notes\n\n{month_line}. *Segments* = transcript length. "
          f"*Status* = whether the meeting has been digested and analysed into tasks, decisions and memory.\n\n"
          "| Date | Meeting | With | Segments | Status | Links |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    return {"id": "meetings/index", "section": "Meeting digests", "title": f"All meetings ({len(notes)})", "path": "Granola Export/raw-json",
            "mtime": "", "meta": {}, "words": 0, "md": md}


def md_files(folder, exclude=("README.md", "latest.md")):
    if not folder.exists():
        return []
    return sorted([p for p in folder.glob("*.md") if p.name not in exclude], reverse=True)


def main():
    docs = []
    briefs = [p for p in md_files(ASSIST / "briefs") if not p.name.endswith("-review.md")]
    reviews = [p for p in md_files(ASSIST / "briefs") if p.name.endswith("-review.md")]
    for p in briefs:
        docs.append(doc(p, "Briefs"))
    for p in reviews:
        docs.append(doc(p, "Weekly reviews"))
    docs.append(doc(ASSIST / "TASKS.md", "Tasks", "Tasks"))
    docs.append(doc(ASSIST / "memory" / "decisions.md", "Decisions", "Decision log"))
    for p in md_files(ASSIST / "inbox" / "live"):
        docs.append(doc(p, "Live pulls"))
    for p in md_files(ASSIST / "inbox" / "granola"):
        docs.append(doc(p, "Meeting digests"))
    for p in md_files(ASSIST / "inbox" / "processed"):
        docs.append(doc(p, "Processed digests"))
    for p in sorted((ASSIST / "inbox" / "backfill").glob("*.md"), reverse=True) if (ASSIST / "inbox" / "backfill").exists() else []:
        docs.append(doc(p, "Analyses"))
    docs.append(meetings_index())
    for p in md_files(ASSIST / "drafts"):
        docs.append(doc(p, "Drafts"))
    docs.append(doc(ASSIST / "CLAUDE.md", "Memory", "Working memory (CLAUDE.md)"))
    for name, label in [("glossary.md", "Glossary"), ("context/strategy.md", "Strategy frame"),
                        ("context/preferences.md", "Writing preferences"),
                        ("context/v2mom-2026-final.md", "V2MOM 2026 (final)")]:
        p = ASSIST / "memory" / name
        if p.exists():
            docs.append(doc(p, "Memory", label))
    for p in md_files(ASSIST / "memory" / "people"):
        docs.append(doc(p, "People"))
    for p in md_files(ASSIST / "memory" / "projects"):
        docs.append(doc(p, "Initiatives"))
    docs.append(doc(ASSIST / "DESIGN.md", "System", "Design"))
    docs.append(doc(ASSIST / "README.md", "System", "How to use"))

    state_path = ASSIST / "inbox" / "granola" / ".state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    log_path = ASSIST / "inbox" / "sync.log"
    log_tail = "\n".join(log_path.read_text().splitlines()[-30:]) if log_path.exists() else "(no sync yet)"
    docs.append({"id": "system/status", "section": "System", "title": "Sync status", "path": "inbox/sync.log",
                 "mtime": "", "meta": {}, "words": 0,
                 "md": f"# Sync status\n\n- Meetings digested: **{len(state.get('digested', []))}**\n"
                       f"- Last digest run: {state.get('last_run', '—')}\n\n## sync.log (tail)\n\n```\n{log_tail}\n```\n"})

    cov_path = ASSIST / "inbox" / "coverage.json"
    if cov_path.exists():
        cov = json.loads(cov_path.read_text())
        rows = "\n".join(f"| {c['source']} | {c['available']} | {c['digested']} | {c['analysed']} | {c['note']} |" for c in cov["sources"])
        from collections import Counter
        sec_counts = Counter(d["section"] for d in docs)
        inpage = ", ".join(f"{k} {v}" for k, v in sec_counts.items())
        docs.insert(0, {"id": "system/coverage", "section": "Coverage", "title": "What has been pulled and analysed", "path": "inbox/coverage.json",
                        "mtime": cov.get("updated", ""), "meta": {}, "words": 0,
                        "md": f"# Coverage · updated {cov.get('updated','')}\n\n*Available* = what the source holds in the window · *Digested* = copied into inbox/ as metadata or summary · *Analysed* = read and turned into tasks, decisions or memory.\n\n| Source | Available | Digested | Analysed | Note |\n|---|---|---|---|---|\n{rows}\n\n## What this page contains\n\n{inpage}, plus this coverage view. Every item above is searchable from the box at the top.\n"})

    # Task counts for the header
    tasks_md = (ASSIST / "TASKS.md").read_text()
    def count(section):
        total = 0
        for m in re.finditer(rf"## {section}[^\n]*\n(.*?)(?=\n## |\Z)", tasks_md, re.S):
            total += len(re.findall(r"^- \[ \]", m.group(1), re.M))
        return total
    stats = {"active": count("Active"), "waiting": count("Waiting On"),
             "pending_decisions": len(re.findall(r"\| pending", (ASSIST / "memory" / "decisions.md").read_text())),
             "generated": datetime.now(TZ).strftime("%a %d %b %Y, %H:%M %Z") if TZ else datetime.now().strftime("%a %d %b %Y, %H:%M")}

    html = TEMPLATE.replace("__DATA__", json.dumps({"docs": docs, "stats": stats}, ensure_ascii=False)
                            .replace("</", "<\\/"))
    OUT.write_text(html)
    print(f"Wrote {OUT.name}: {len(docs)} documents, {OUT.stat().st_size // 1024} KB")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Assist</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<style>
:root{--bg:#f7f7f4;--panel:#ffffff;--ink:#23221f;--ink2:#6b6a63;--ink3:#a3a29a;--line:#e3e2dc;--accent:#b85c38;--accent-bg:#f7eae3;--hl:#fff3b0;--mono:ui-monospace,SFMono-Regular,Menlo,monospace;--sans:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17171a;--panel:#1f1f23;--ink:#e8e6df;--ink2:#a7a59c;--ink3:#6f6e67;--line:#2e2e33;--accent:#e08860;--accent-bg:#2c211b;--hl:#4a4320}}
:root[data-theme="dark"]{--bg:#17171a;--panel:#1f1f23;--ink:#e8e6df;--ink2:#a7a59c;--ink3:#6f6e67;--line:#2e2e33;--accent:#e08860;--accent-bg:#2c211b;--hl:#4a4320}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:15px/1.55 var(--sans);display:grid;grid-template-rows:auto 1fr;height:100vh}
header{display:flex;gap:16px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:17px;margin:0;font-weight:600;letter-spacing:.2px}
header .stats{display:flex;gap:14px;color:var(--ink2);font-size:13px;flex-wrap:wrap}
header .stats b{color:var(--ink)}
header input{margin-left:auto;width:min(360px,40vw);padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
header button{border:1px solid var(--line);background:var(--bg);color:var(--ink2);border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit}
main{display:grid;grid-template-columns:280px 1fr;min-height:0}
nav{border-right:1px solid var(--line);overflow:auto;padding:10px 0 30px;background:var(--panel)}
nav h2{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--ink3);margin:16px 16px 6px;font-weight:600}
nav a{display:block;padding:6px 16px 6px 20px;color:var(--ink);text-decoration:none;font-size:14px;border-left:3px solid transparent;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
nav a small{display:block;color:var(--ink3);font-size:11.5px}
nav a:hover{background:var(--bg)}
nav a.active{border-left-color:var(--accent);background:var(--accent-bg)}
nav .empty{padding:4px 20px;color:var(--ink3);font-size:13px}
article{overflow:auto;padding:28px clamp(16px,4vw,56px) 80px;max-width:980px}
.crumbs{color:var(--ink3);font-size:12.5px;margin-bottom:6px;font-family:var(--mono)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px}
.chips span{font-size:12px;background:var(--accent-bg);color:var(--ink2);border-radius:999px;padding:2px 9px}
.md h1{font-size:26px;margin:.2em 0 .6em;font-weight:650;line-height:1.2}
.md h2{font-size:18px;margin:1.6em 0 .5em;padding-bottom:4px;border-bottom:1px solid var(--line);font-weight:600}
.md h3{font-size:15.5px;margin:1.3em 0 .4em;font-weight:600}
.md p,.md li{color:var(--ink)}
.md a{color:var(--accent);text-decoration:none}
.md a:hover{text-decoration:underline}
.md table{border-collapse:collapse;width:100%;font-size:13.5px;margin:10px 0 16px;display:block;overflow:auto}
.md th,.md td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
.md th{background:var(--bg);font-weight:600}
.md code{font-family:var(--mono);font-size:12.5px;background:var(--bg);padding:1px 5px;border-radius:4px}
.md pre{background:var(--bg);border:1px solid var(--line);padding:12px;border-radius:8px;overflow:auto;font-size:12.5px}
.md pre code{background:none;padding:0}
.md blockquote{border-left:3px solid var(--line);margin:0;padding:2px 14px;color:var(--ink2)}
.md input[type=checkbox]{margin-right:6px;accent-color:var(--accent)}
.md li:has(> input:checked){color:var(--ink3);text-decoration:line-through}
.md hr{border:0;border-top:1px solid var(--line);margin:24px 0}
.md ul{padding-left:22px}
.md li{margin:3px 0}
mark{background:var(--hl);color:inherit;padding:0 1px;border-radius:2px}
.results{list-style:none;padding:0;margin:0}
.results li{padding:12px 0;border-bottom:1px solid var(--line)}
.results a{color:var(--ink);font-weight:600;text-decoration:none}
.results small{color:var(--ink3);margin-left:8px;font-family:var(--mono);font-size:11.5px}
.results p{margin:4px 0 0;color:var(--ink2);font-size:13.5px}
.toggle{display:none}
@media (max-width:760px){main{grid-template-columns:1fr}nav{display:none}nav.open{display:block;position:fixed;inset:49px 0 0 0;z-index:5}.toggle{display:inline-block}header input{width:100%}header{flex-wrap:wrap}}
</style>
</head>
<body>
<header>
  <button class="toggle" onclick="document.querySelector('nav').classList.toggle('open')">☰</button>
  <h1>Assist</h1>
  <div class="stats" id="stats"></div>
  <input id="q" type="search" placeholder="Search everything…" autocomplete="off">
  <button id="theme" title="Toggle theme">◐</button>
</header>
<main>
  <nav id="nav"></nav>
  <article id="view"></article>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const ORDER = ["Coverage","Briefs","Weekly reviews","Tasks","Decisions","Analyses","Live pulls","Meeting digests","Processed digests","Drafts","Memory","People","Initiatives","System"];
const byId = Object.fromEntries(DATA.docs.map(d => [d.id, d]));
const $ = s => document.querySelector(s);

function render(md){
  if (window.marked) { marked.setOptions({gfm:true, breaks:false}); return marked.parse(md); }
  const esc = md.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  return '<pre style="white-space:pre-wrap">' + esc + '</pre>';
}

function stats(){
  const s = DATA.stats;
  $('#stats').innerHTML = `<span><b>${s.active}</b> active</span><span><b>${s.waiting}</b> waiting on others</span><span><b>${s.pending_decisions}</b> decisions pending</span><span>built ${s.generated}</span>`;
}

function nav(filter){
  const nav = $('#nav'); nav.innerHTML = '';
  for (const sec of ORDER){
    const docs = DATA.docs.filter(d => d.section === sec && (!filter || filter.has(d.id)));
    if (!docs.length && filter) continue;
    const h = document.createElement('h2'); h.textContent = sec + (docs.length ? ' · ' + docs.length : ''); nav.appendChild(h);
    if (!docs.length){ const e = document.createElement('div'); e.className='empty'; e.textContent='nothing yet'; nav.appendChild(e); continue; }
    for (const d of docs){
      const a = document.createElement('a'); a.href = '#' + encodeURIComponent(d.id); a.dataset.id = d.id;
      a.innerHTML = `${d.title}<small>${d.mtime}${d.words ? ' · ' + d.words + ' words' : ''}</small>`;
      nav.appendChild(a);
    }
  }
}

function show(id, term){
  const d = byId[id]; if (!d) return;
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.dataset.id === id));
  const chips = Object.entries(d.meta).map(([k,v]) => `<span>${k}: ${v}</span>`).join('');
  let html = render(d.md);
  if (term) html = highlight(html, term);
  $('#view').innerHTML = `<div class="crumbs">${d.section} / ${d.path}</div>${chips ? '<div class="chips">'+chips+'</div>' : ''}<div class="md">${html}</div>`;
  $('#view').querySelectorAll('a[href^="http"]').forEach(a => { a.target = '_blank'; a.rel = 'noopener'; });
  $('#view').scrollTop = 0;
  document.querySelector('nav').classList.remove('open');
  document.title = d.title + ' · Assist';
}

function highlight(html, term){
  const re = new RegExp('(' + term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
  const tpl = document.createElement('template'); tpl.innerHTML = html;
  const walker = document.createTreeWalker(tpl.content, NodeFilter.SHOW_TEXT);
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes){
    if (!re.test(n.nodeValue)) continue;
    const span = document.createElement('span');
    span.innerHTML = n.nodeValue.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])).replace(re, '<mark>$1</mark>');
    n.replaceWith(...span.childNodes);
  }
  return tpl.innerHTML;
}

function search(term){
  term = term.trim();
  if (!term){ nav(); route(); return; }
  const re = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  const hits = DATA.docs.filter(d => re.test(d.md) || re.test(d.title));
  nav(new Set(hits.map(h => h.id)));
  const items = hits.map(d => {
    const i = d.md.search(re); const snip = i >= 0 ? d.md.slice(Math.max(0, i-90), i+140).replace(/\n+/g,' ') : '';
    return `<li><a href="#${encodeURIComponent(d.id)}">${d.title}</a><small>${d.section}</small><p>…${highlight(snip.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])), term)}…</p></li>`;
  }).join('');
  $('#view').innerHTML = `<div class="md"><h1>${hits.length} result${hits.length===1?'':'s'} for “${term}”</h1></div><ul class="results">${items || '<li>No matches.</li>'}</ul>`;
}

function route(){
  const id = decodeURIComponent(location.hash.slice(1));
  const term = $('#q').value.trim();
  if (id && byId[id]) show(id, term);
  else { const first = DATA.docs.find(d => d.section === 'Briefs') || DATA.docs[0]; if (first) show(first.id); }
}

$('#q').addEventListener('input', e => search(e.target.value));
$('#theme').addEventListener('click', () => {
  const r = document.documentElement; const cur = r.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  r.dataset.theme = cur === 'dark' ? 'light' : 'dark'; try { localStorage.setItem('assist-theme', r.dataset.theme); } catch(e){}
});
try { const t = localStorage.getItem('assist-theme'); if (t) document.documentElement.dataset.theme = t; } catch(e){}
window.addEventListener('hashchange', route);
stats(); nav(); route();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
