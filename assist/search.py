"""Unified search over everything Assist knows.

One FTS5 index (search_fts) holds one row per thing: people, initiatives, commitments, meetings (digest),
meeting transcripts, full emails (and gist-only mail), Teams/Slack messages, attachments, SharePoint / KB / local
documents, library documents and calendar events. A trigram index (search_tri) over titles and the start of each body
catches partial words, codes like DEV-59997 and small typos when the word index finds too little.

Ranking: BM25 with title weighted above body, then a boost by kind (a person or an initiative beats a chat line),
a recency boost, and an exact-title bonus. Queries understand "phrases", type:, from:, after:/before: and expand
acronyms from memory/glossary.md (PLT ↔ Agentic Platform).

The index is rebuilt from the database when it changes (a few seconds); nothing here is a source of truth.
"""
import json
import math
import re
import time
from datetime import datetime, timezone

from . import db
from . import profile

KINDS = {   # kind: (label, boost)
    "person": ("People", 2.2), "initiative": ("Initiatives", 2.0), "commitment": ("Commitments", 1.5),
    "meeting": ("Meetings", 1.4), "document": ("Documents", 1.15), "library": ("Library", 1.1), "email": ("Emails", 1.0),
    "attachment": ("Attachments", 1.0), "event": ("Calendar", 0.8), "chat": ("Chat", 0.8), "transcript": ("Transcripts", 0.75),
}
ALIASES = {"email": "email", "mail": "email", "emails": "email", "person": "person", "people": "person", "meeting": "meeting", "meetings": "meeting",
           "transcript": "transcript", "transcripts": "transcript", "doc": "document", "docs": "document", "document": "document", "documents": "document",
           "file": "document", "files": "document", "attachment": "attachment", "attachments": "attachment", "chat": "chat", "teams": "chat",
           "slack": "chat", "commitment": "commitment", "commitments": "commitment", "task": "commitment",
           "tasks": "commitment", "initiative": "initiative", "initiatives": "initiative", "bet": "initiative", "library": "library", "event": "event",
           "calendar": "event"}
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "about", "from", "by", "is", "at", "my", "me", "what", "who", "when"}
BODY_MAX, TRI_BODY = 60000, 1500



def _summary(d):
    from .relevance import digest_summary
    return digest_summary(d)

def _clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def ensure(con):
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(title, body, people, tags, kind UNINDEXED, ref UNINDEXED, "
                "ts UNINDEXED, url UNINDEXED, meta UNINDEXED, tokenize='porter unicode61 remove_diacritics 2', prefix='2 3 4')")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search_tri USING fts5(text, kind UNINDEXED, ref UNINDEXED, tokenize='trigram')")


# ---------------------------------------------------------------- build
def _rows(con):
    """Yield (kind, ref, title, body, people, tags, ts, url, meta) for everything searchable."""
    for p in con.execute("SELECT * FROM people"):
        if p["is_me"]:
            continue
        org = con.execute("SELECT name FROM orgs WHERE id=?", (p["org_id"],)).fetchone() if p["org_id"] else None
        yield ("person", f"p-{p['id']}", p["name"], _clean(p["profile_md"])[:BODY_MAX], p["name"],
               " ".join(filter(None, [p["title"], p["role"], p["department"], p["location"], p["affiliation"], org["name"] if org else ""])),
               p["updated_at"], f"/people/p-{p['id']}", {"sub": p["title"] or p["role"] or p["affiliation"] or ""})
    for i in con.execute("SELECT * FROM initiatives"):
        yield ("initiative", f"i-{i['id']}", i["name"], _clean(i["profile_md"])[:BODY_MAX], i["owner"] or "", f"{i['status'] or ''} {i['next_milestone'] or ''}",
               i["updated_at"], f"/explore/library/i-{i['id']}", {"sub": f"weight {i['weight']}" + (f" · {i['status']}" if i["status"] else "")})
    for c in con.execute("SELECT * FROM commitments"):
        yield ("commitment", f"t-{c['id']}", c["title"], _clean(c["context"]), c["counterparty"] or "", f"{c['kind']} {c['status']}",
               c["created_at"], "/commitments", {"sub": ("you owe" if c["kind"] == "owed_by_me" else "owed to you" if c["kind"] == "owed_to_me" else c["kind"])
                                                 + f" · {c['status']}" + (f" · due {c['due']}" if c["due"] else "")})
    from . import transcripts
    for m in con.execute("SELECT m.*, i.external_id FROM meetings m JOIN items i ON i.id=m.note_item_id WHERE m.status != 'personal'"):
        att = ", ".join(a for a in json.loads(m["attendees"] or "[]") if not profile.is_me(a))
        yield ("meeting", f"m-{m['id']}", m["title"] or "Untitled meeting", _clean(_summary(m["digest_md"]))[:BODY_MAX], att, "", m["starts_at"],
               f"/meetings/m-{m['id']}", {"sub": f"with {att}" if att else "meeting notes"})
        try:
            _, path = transcripts._file(con, f"m-{m['id']}")
        except Exception:
            path = None
        if path:
            text = path.read_text(errors="ignore")
            body = text.split("## Transcript", 1)[1] if "## Transcript" in text else ""
            body = re.sub(r"\*\*\[\d\d:\d\d:\d\d\] ([^:*]+):\*\*", r"\1:", body)
            yield ("transcript", f"m-{m['id']}", f"Transcript · {m['title'] or 'meeting'}", _clean(body)[:BODY_MAX], att, "", m["starts_at"],
                   f"/meetings/m-{m['id']}", {"sub": "what was said"})
        from . import granola_shots   # what was on the shared screen, by Granola's description; opens that moment
        start = granola_shots.first_clock(text) if path else None
        for sh in granola_shots.for_meeting(con, m["id"], start):
            yield ("screen", f"sh-{sh['id']}", f"Screen · {m['title'] or 'meeting'}", _clean(sh["description"])[:BODY_MAX], att, "", sh["captured_at"],
                   f"/meetings/m-{m['id']}" + (f"?t={sh['t']}" if sh["t"] is not None else ""), {"sub": "on the shared screen"})
    try:   # the product roadmap (assist/roadmap.py)
        for r in con.execute("SELECT * FROM roadmap_items"):
            yield ("roadmap", f"rm-{r['id']}", f"{r['id']} · {r['name_internal']}", _clean(" ".join(x or "" for x in (r["name_external"], r["value"], r["detail"], r["gap"], r["customers"], r["grp"], r["theme"])))[:BODY_MAX],
                   " ".join(json.loads(r["owners"] or "[]")), f"{r['status']} {r['horizon']}", r["updated_at"], f"/roadmap?item={r['id']}",
                   {"sub": f"{r['status']} · {r['start_q']}–{r['end_q']} · {r['grp']}"})
    except Exception:   # roadmap not imported yet
        pass
    have_mail = set()
    for r in con.execute("SELECT m.*, i.text AS note FROM mail_messages m JOIN items i ON i.id=m.item_id"):
        have_mail.add(r["item_id"])
        ppl = " ".join([r["from_name"] or "", r["from_address"] or ""] + [f"{x['name']} {x['address']}" for x in json.loads(r["to_json"] or "[]") + json.loads(r["cc_json"] or "[]")])
        sent = r["folder"] == "sentitems"
        yield ("email", f"e-{r['item_id']}", r["subject"] or "(no subject)", _clean((r["note"] or "") + " " + (r["body_text"] or ""))[:BODY_MAX], ppl,
               "sent" if sent else "inbox", r["received_at"] or r["sent_at"], f"/mail?open={r['item_id']}",
               {"sub": ("you → " + ", ".join(x["name"] or x["address"] for x in json.loads(r["to_json"] or "[]"))[:60]) if sent else (r["from_name"] or "")})
    for r in con.execute("SELECT * FROM items WHERE source_id LIKE 'outlook.%' AND kind IN ('mail','sent')"):
        if r["id"] not in have_mail:   # gist-only mail (older than the full archive)
            yield ("email", f"e-{r['id']}", r["subject"] or "(no subject)", _clean(r["text"]), r["from_name"] or "", "gist", r["ts"],
                   f"/mail?open={r['id']}", {"sub": (r["from_name"] or "") + " · summary only"})
    try:
        for r in con.execute("SELECT c.*, i.source_id FROM chat_messages c JOIN items i ON i.id=c.item_id"):
            yield ("chat", f"c-{r['item_id']}", f"{r['author'] or ''} in {r['conversation_name'] or r['source_id']}", _clean(r["body_text"])[:BODY_MAX],
                   r["author"] or "", r["source_id"], r["sent_at"], r["web_link"] or "/messages", {"sub": (r["source_id"] or "").split(".")[0].title()})
    except Exception:
        pass
    for r in con.execute("SELECT a.id, a.name, a.text, m.subject, m.from_name, COALESCE(m.received_at, m.sent_at) AS ts FROM mail_attachments a "
                         "JOIN mail_messages m ON m.item_id=a.item_id WHERE a.is_inline=0"):
        yield ("attachment", f"ma-{r['id']}", r["name"], _clean(r["text"])[:BODY_MAX], r["from_name"] or "", r["subject"] or "", r["ts"],
               f"doc:ma-{r['id']}", {"sub": f"attachment on “{r['subject']}”"})
    try:
        for r in con.execute("SELECT a.id, a.name, c.author, c.conversation_name, c.sent_at FROM chat_attachments a JOIN chat_messages c ON c.item_id=a.item_id"):
            yield ("attachment", f"ca-{r['id']}", r["name"], "", r["author"] or "", r["conversation_name"] or "", r["sent_at"], f"doc:ca-{r['id']}",
                   {"sub": f"shared in {r['conversation_name'] or 'a chat'}"})
    except Exception:
        pass
    pre = {"sharepoint": ("sp", "SharePoint"), "acme-kb": ("kb", "Emery Yates"), "local": ("lf", "This Mac")}
    for r in con.execute("SELECT * FROM items WHERE kind='doc' AND source_id IN ('sharepoint', 'acme-kb', 'local')"):
        p, label = pre[r["source_id"]]
        yield ("document", f"{p}-{r['id']}", r["subject"] or "(untitled)", _clean(r["text"])[:BODY_MAX], r["from_name"] or "", f"{label} {r['thread'] or ''}",
               r["ts"], f"doc:{p}-{r['id']}", {"sub": f"{label}" + (f" · {r['thread']}" if r["thread"] else "")})
    for d in con.execute("SELECT * FROM documents"):
        yield ("library", d["id"], d["title"], _clean(d["body_md"])[:BODY_MAX], "", d["section"], d["updated_at"], f"/explore/library/{d['id']}",
               {"sub": d["section"]})
    for r in con.execute("SELECT * FROM items WHERE kind='event'"):
        p = json.loads(r["payload"] or "{}")
        if p.get("isCancelled") or not (p.get("subject") or r["subject"]):
            continue
        att = " ".join(p.get("attendees") or [])
        yield ("event", f"ev-{r['id']}", p.get("subject") or r["subject"], _clean(p.get("summary") or ""), att, p.get("location") or "",
               r["ts"], "/meetings", {"sub": "calendar"})


SIG_SQL = ("SELECT (SELECT COUNT(*) || ':' || IFNULL(MAX(id),0) FROM items) || '|' || (SELECT COUNT(*) FROM mail_messages) || '|' || "
           "(SELECT COUNT(*) || ':' || IFNULL(MAX(status),'') FROM commitments) || '|' || '|' || "
           "(SELECT COUNT(*) || ':' || SUM(LENGTH(IFNULL(digest_md,''))) FROM meetings) || '|' || (SELECT IFNULL(MAX(updated_at),'') FROM documents) || '|' || "
           "(SELECT IFNULL(MAX(updated_at),'') FROM people) || '|' || (SELECT IFNULL(MAX(updated_at),'') FROM initiatives) || '|' || "
           "(SELECT COUNT(*) FROM mail_attachments) || '|' || (SELECT COUNT(*) FROM meeting_shots)")


def signature(con):
    sig = con.execute(SIG_SQL).fetchone()[0]
    try:
        sig += "|" + str(con.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0])
    except Exception:
        pass
    return sig


def ensure_fresh(con, min_age=20):
    """Rebuild when the content changed since the last build (checked cheaply on every search)."""
    ensure(con)
    sig = signature(con)
    row = con.execute("SELECT value FROM settings WHERE key='search_sig'").fetchone()
    at = con.execute("SELECT value FROM settings WHERE key='search_built_at'").fetchone()
    stale = not row or row[0] != sig or not con.execute("SELECT 1 FROM search_fts LIMIT 1").fetchone()
    if stale and (not at or (datetime.now(timezone.utc) - datetime.fromisoformat(at[0].replace("Z", "+00:00"))).total_seconds() > min_age or not row):
        build(con)


def build(con):
    t0 = time.time()
    ensure(con)
    con.execute("DELETE FROM search_fts")
    con.execute("DELETE FROM search_tri")
    n = 0
    for kind, ref, title, body, people, tags, ts, url, meta in _rows(con):
        con.execute("INSERT INTO search_fts (title, body, people, tags, kind, ref, ts, url, meta) VALUES (?,?,?,?,?,?,?,?,?)",
                    (title or "", body or "", people or "", tags or "", kind, ref, ts or "", url or "", json.dumps(meta or {}, ensure_ascii=False)))
        con.execute("INSERT INTO search_tri (text, kind, ref) VALUES (?,?,?)", (f"{title or ''} {people or ''} {(body or '')[:TRI_BODY]}", kind, ref))
        n += 1
    con.execute("INSERT INTO search_fts(search_fts) VALUES ('optimize')")
    con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('search_built_at', ?)", (db.now(),))
    con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('search_sig', ?)", (signature(con),))
    con.commit()
    return n, round(time.time() - t0, 1)


# ---------------------------------------------------------------- query
_GLOSS = {"at": 0, "map": {}}


def glossary():
    """acronym/term -> expansion, both directions, from memory/glossary.md (reloaded when the file changes)."""
    f = db.ASSIST / "memory" / "glossary.md"
    try:
        mt = f.stat().st_mtime
    except OSError:
        return {}
    if _GLOSS["at"] != mt:
        g = {}
        for line in f.read_text(errors="ignore").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or cells[0] in ("Term", "") or set(cells[0]) <= set("-:"):
                continue
            term = re.sub(r"[*`]", "", cells[0]).strip()
            exp = re.split(r"\s+[—–-]\s+|[;(]", re.sub(r"[*`]", "", cells[1]), maxsplit=1)[0].strip().rstrip(".")
            if term and exp and len(exp.split()) <= 6 and exp.lower() != term.lower():
                for t in re.split(r"\s*/\s*", term):
                    g.setdefault(t.lower(), set()).add(exp)
                    g.setdefault(exp.lower(), set()).add(t)
        _GLOSS.update(at=mt, map=g)
    return _GLOSS["map"]


def parse(q):
    """Split operators from text: type:, from:, after:, before:, and "quoted phrases"."""
    ops = {"types": set(), "from": [], "after": None, "before": None}
    phrases = re.findall(r'"([^"]+)"', q)
    q = re.sub(r'"[^"]+"', " ", q)
    words = []
    for w in q.split():
        m = re.match(r"^(type|in|is|from|by|with|after|since|before|until):(.+)$", w, re.I)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip(",")
            if k in ("type", "in", "is"):
                ops["types"] |= {ALIASES[x] for x in v.lower().split(",") if x in ALIASES}
            elif k in ("from", "by", "with"):
                ops["from"].append(v)
            elif k in ("after", "since"):
                ops["after"] = v
            else:
                ops["before"] = v
        else:
            words.append(w)
    return words, phrases, ops


def _fts_terms(words, phrases, prefix_last=True):
    terms = [f'"{p.replace(chr(34), "")}"' for p in phrases]
    toks = [t for w in words for t in re.findall(r"[\w][\w&+.-]*", w, re.UNICODE)]
    for i, t in enumerate(toks):
        t = t.strip(".-")
        if not t:
            continue
        q = '"%s"' % t.replace('"', "")
        terms.append(q + ("*" if prefix_last and i == len(toks) - 1 and len(t) >= 2 else ""))
    return terms


def _expansions(words, phrases):
    """Expand acronyms typed as acronyms (PLT, MCP, NOVA) and full glossary phrases, not ordinary words or names."""
    g, raw = glossary(), " ".join(words + phrases)
    text = raw.lower()
    out = []
    for key, exps in g.items():
        m = re.search(rf"(?<![\w]){re.escape(key)}(?![\w])", text)
        if not m:
            continue
        typed = raw[m.start():m.end()]
        acronym = (typed.isupper() and len(typed) <= 6) or bool(re.search(r"\d", typed))
        phrase = len(key.split()) >= 2
        if acronym or phrase:
            out += [e for e in exps if e.lower() not in text]
    return out[:4]


def search(con, q, limit=40, kinds=None):
    ensure(con)
    words, phrases, ops = parse(q)
    words = [w for w in words if w.lower() not in STOP or len(words) == 1]
    hinted = {ALIASES[w.lower()] for w in words if w.lower() in ALIASES and len(words) > 1}   # "meetings with Marlow"
    if hinted:
        words = [w for w in words if w.lower() not in ALIASES]
    if kinds:
        ops["types"] |= set(kinds)
    base = _fts_terms(words, phrases)
    if not base and not ops["from"]:
        return {"query": q, "results": [], "counts": {}, "expanded": [], "mode": "empty"}
    exp = _expansions(words, phrases)
    where, args = [], []
    if ops["types"]:
        where.append("kind IN (%s)" % ",".join("?" * len(ops["types"])))
        args += sorted(ops["types"])
    if ops["after"]:
        where.append("ts >= ?"); args.append(ops["after"])
    if ops["before"]:
        where.append("ts <= ?"); args.append(ops["before"])
    from_terms = ['people : "%s"*' % f.replace('"', "") for f in ops["from"]]

    def run(match, how):
        sql = ("SELECT rowid, kind, ref, title, ts, url, meta, bm25(search_fts, 8.0, 1.0, 3.0, 2.0) AS bm, "
               "snippet(search_fts, 1, '\u0002', '\u0003', ' … ', 16) AS snip, snippet(search_fts, 0, '\u0002', '\u0003', '', 30) AS tsnip "
               "FROM search_fts WHERE search_fts MATCH ?" + "".join(" AND " + w for w in where) + " ORDER BY bm LIMIT 400")
        try:
            return [dict(r, how=how) for r in con.execute(sql, [match] + args)]
        except Exception:
            return []

    def combine(terms, op):
        parts = []
        if terms:
            parts.append("(" + f" {op} ".join(terms) + ")")
        if exp:
            alt = " OR ".join('"%s"' % e.replace('"', "") for e in exp)
            parts = ["(" + " OR ".join(parts + [f"({alt})"]) + ")"] if parts else [f"({alt})"]
        return " AND ".join(parts + from_terms)

    rows = run(combine(base, "AND"), "all words")
    mode = "all words"
    if len(rows) < 8 and len(base) > 1:   # loosen: any word, ranked by how many match
        more = run(combine(base, "OR"), "some words")
        seen = {(r["kind"], r["ref"]) for r in rows}
        rows += [r for r in more if (r["kind"], r["ref"]) not in seen]
        mode = "some words" if more and not rows[:1] or len(rows) > len(more) else mode
    if len(rows) < 5:   # partial words, codes, small typos
        tri = [t for t in (re.sub(r'["*]', "", x) for x in base) if len(t) >= 3]
        if tri:
            seen = {(r["kind"], r["ref"]) for r in rows}
            for t in tri:
                for r in con.execute("SELECT kind, ref FROM search_tri WHERE search_tri MATCH ? LIMIT 60", (f'"{t}"',)):
                    if (r["kind"], r["ref"]) in seen or (ops["types"] and r["kind"] not in ops["types"]):
                        continue
                    seen.add((r["kind"], r["ref"]))
                    full = con.execute("SELECT rowid, kind, ref, title, ts, url, meta, substr(body, 1, 200) AS snip, title AS tsnip FROM search_fts "
                                       "WHERE kind=? AND ref=? LIMIT 1", (r["kind"], r["ref"])).fetchone()
                    if full:
                        rows.append(dict(full, bm=-1.0, how="partial match"))
            mode = "partial match" if rows and all(r["how"] == "partial match" for r in rows) else mode
    # by meaning (assist/embed.py, 28 Oct 2026): rows that say the same in other words, ranked below word matches; a word
    # match that is also close in meaning is lifted. Nothing happens until fastembed and its model are installed.
    sem_q = " ".join(words + phrases).strip()
    if len(sem_q) >= 6 and not ops["from"]:
        from . import embed
        seen = {(r["kind"], r["ref"]): r for r in rows}
        for kind, ref, sim in embed.query(sem_q, k=25, kinds=ops["types"] or None, after=ops["after"], before=ops["before"]):
            if kind == "memory":
                continue
            if (kind, ref) in seen:
                seen[(kind, ref)]["sim"] = sim
                continue
            full = con.execute("SELECT rowid, kind, ref, title, ts, url, meta, substr(body, 1, 200) AS snip, title AS tsnip FROM search_fts "
                               "WHERE kind=? AND ref=? LIMIT 1", (kind, ref)).fetchone()
            if full:
                rows.append(dict(full, bm=-sim * 10, how="by meaning", sim=sim))
        if rows and all(r["how"] == "by meaning" for r in rows):
            mode = "by meaning"

    now = datetime.now(timezone.utc)
    qtext = " ".join(words + phrases).lower().strip()
    last = (words[-1].lower() if words else "").strip('"')
    last = last if len(last) >= 3 else ""
    out = []
    for r in rows:
        score = -r["bm"] * KINDS.get(r["kind"], ("", 1.0))[1]
        if r["how"] == "some words":
            score *= 0.6
        if r["kind"] in hinted:
            score *= 2.5
        if r.get("sim") and r["how"] != "by meaning":
            score *= 1 + r["sim"]
        try:
            age = (now - datetime.fromisoformat((r["ts"] or "")[:19].replace("Z", "")).replace(tzinfo=timezone.utc)).days
            score *= 1 + 0.6 * math.exp(-max(age, 0) / 21)
        except ValueError:
            pass
        title = (r["title"] or "").lower()
        if last and re.search(rf"(?<![\w]){re.escape(last)}", title):   # the word being typed starts a word in the title
            score *= 2.0
        if qtext and (title == qtext or title.startswith(qtext)):
            score *= 2.5
        elif qtext and qtext in title:
            score *= 1.5
        meta = json.loads(r["meta"] or "{}")
        out.append({"kind": r["kind"], "ref": r["ref"], "title": r["title"], "ts": r["ts"], "url": r["url"], "sub": meta.get("sub", ""),
                    "snippet": (r["snip"] or "").strip(), "title_hl": r["tsnip"] or r["title"], "score": round(score, 3), "how": r["how"]})
    # one transcript and one meeting per meeting are fine; collapse exact duplicates
    out.sort(key=lambda x: -x["score"])
    norm = lambda t: re.sub(r"^((re|fw|fwd|aw|tr|wg)\s*:\s*)+", "", (t or "").lower()).strip()
    kept, firsts = [], {}
    for x in out:
        if x["kind"] in ("email", "document", "attachment"):
            # one result per email thread, and one per file however many places it was shared
            k = ("email:" + norm(x["title"])) if x["kind"] == "email" else ("file:" + re.sub(r"\s+", " ", (x["title"] or "").lower()).strip())
            if k in firsts:
                firsts[k]["more"] = firsts[k].get("more", 0) + 1
                continue
            firsts[k] = x
        kept.append(x)
    out = kept
    counts = {}
    for x in out:
        counts[x["kind"]] = counts.get(x["kind"], 0) + 1
    return {"query": q, "results": out[:limit], "counts": counts, "total": len(out), "expanded": exp, "mode": mode,
            "hinted": sorted(hinted), "filters": {"types": sorted(ops["types"]), "from": ops["from"], "after": ops["after"], "before": ops["before"]}}


def suggest(con, q, limit=8):
    """Typeahead: the best few across kinds, favouring titles."""
    r = search(con, q, limit=40)
    best, per = [], {}
    for x in r["results"]:
        if per.get(x["kind"], 0) >= 3:
            continue
        per[x["kind"]] = per.get(x["kind"], 0) + 1
        best.append(x)
        if len(best) >= limit:
            break
    return {"query": q, "results": best, "total": r["total"]}
