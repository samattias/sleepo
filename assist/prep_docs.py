"""Documents in play for a meeting: attachments on recent mail and chat with the attendees, plus SharePoint, KB and
local files that match the meeting's topic. Each carries the id the app uses (doc:<id>) so the brief can link it as a chip."""
import json
import re

from . import profile
from .promptkit import USER   # the user in prompt text (assist/profile.py)

GENERIC = {"with", "sync", "meeting", "call", "review", "weekly", "update", "check", "catch", "chat", "discussion", "session",
           "fixed", "teams", "online", "monthly", "daily", "quick", "follow", "intro", "kick", "planning"}
PER_DOC, TOTAL, MAX_DOCS = 3500, 18000, 14
SOURCE = {"sharepoint": ("sp", "SharePoint/OneDrive"), "acme-kb": ("kb", "knowledge base"), "local": ("lf", "this Mac")}


def _clip(t, n):
    t = (t or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def find(con, subject, addrs, first, mentions):
    docs, seen = [], set()

    def add(did, name, source, where, when, link, text):
        key = (name or "").lower()
        if name and key not in seen:
            seen.add(key)
            docs.append({"id": did, "name": name, "source": source, "where": where, "when": (when or "")[:10], "link": link or "", "text": text or ""})

    if addrs:
        for r in con.execute("SELECT a.id, a.name, a.text, m.subject, m.from_name, m.folder, m.from_address, m.to_json, m.cc_json, "
                             "COALESCE(m.received_at, m.sent_at) AS ts, m.web_link FROM mail_attachments a JOIN mail_messages m ON m.item_id=a.item_id "
                             "WHERE a.is_inline=0 ORDER BY ts DESC"):
            who = {(r["from_address"] or "").lower()} | {x["address"].lower() for x in json.loads(r["to_json"] or "[]") + json.loads(r["cc_json"] or "[]")}
            if who & addrs:
                add(f"ma-{r['id']}", r["name"], "email attachment", f"on “{r['subject']}” from {'you' if r['folder'] == 'sentitems' else r['from_name']}",
                    r["ts"], r["web_link"], r["text"])
    try:
        for r in con.execute("SELECT a.id, a.name, a.url, c.conversation_name, c.author, c.sent_at FROM chat_attachments a "
                             "JOIN chat_messages c ON c.item_id=a.item_id ORDER BY c.sent_at DESC LIMIT 2000"):
            if (r["author"] and r["author"].split()[0].lower() in first) or mentions(r["conversation_name"] or ""):
                add(f"ca-{r['id']}", r["name"], "chat file", f"shared by {r['author']} in {r['conversation_name'] or 'a chat'}", r["sent_at"], r["url"], "")
    except Exception:  # chat tables not there yet
        pass
    people_docs = docs[:MAX_DOCS - 5]   # leave room for files that match the topic
    docs[:] = people_docs
    seen.clear(); seen.update(d["name"].lower() for d in docs)
    mine = {w for n in profile.names() for w in n.split()}   # the user's own name is not a topic
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9&-]{2,}", subject) if w.lower() not in GENERIC and w.lower() not in mine and w.split("-")[0].lower() not in first]
    if words:
        q = " OR ".join('"%s"' % w.replace('"', "") for w in words[:8])
        try:
            rows = con.execute("SELECT i.id, i.source_id, i.subject, i.thread, i.from_name, i.ts, i.url, i.text FROM items_fts f JOIN items i ON i.id=f.rowid "
                               "WHERE items_fts MATCH ? AND i.kind='doc' AND i.source_id IN ('sharepoint', 'acme-kb', 'local') ORDER BY rank LIMIT 6", (q,)).fetchall()
        except Exception:
            rows = []
        for r in rows:
            pre, src = SOURCE[r["source_id"]]
            add(f"{pre}-{r['id']}", r["subject"], src, r["thread"] or r["from_name"] or "", r["ts"], r["url"], r["text"])
    try:
        from . import doccards
        for d in docs:
            if doccards.card(con, d["id"]):
                d["card"] = doccards.text_for_context(con, d["id"], d["text"])
    except Exception:  # cards are an improvement, never a dependency
        pass
    return docs[:MAX_DOCS]


SHARE = re.compile(r"https://[\w.-]*(sharepoint\.com|1drv\.ms|onedrive\.live\.com|docs\.google\.com|teams\.microsoft\.com/l/file)[^\s)>\]\"']*", re.I)


def shared_links(con, addrs, first, mentions, days=30, limit=12):
    """Files and folders people shared as links (SharePoint, OneDrive, Teams files) in chat and mail with these people:
    the original, which the brief should link directly instead of a text copy."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, seen = [], set()
    try:
        for r in con.execute("SELECT author, conversation_name, sent_at, links_json, web_link FROM chat_messages WHERE sent_at >= ? AND links_json LIKE '%http%' "
                             "ORDER BY sent_at DESC LIMIT 3000", (since,)):
            if not ((r["author"] and r["author"].split()[0].lower() in first) or mentions(r["conversation_name"] or "")):
                continue
            for l in json.loads(r["links_json"] or "[]"):
                u = (l.get("url") or "").strip()
                key = re.sub(r"[?&]e=\w+", "", u)
                if SHARE.match(u) and key not in seen:
                    seen.add(key)
                    out.append({"title": l.get("title") or u.split("/")[-1].split("?")[0], "url": u, "who": r["author"], "where": r["conversation_name"] or "chat",
                                "when": (r["sent_at"] or "")[:10]})
    except Exception:
        pass
    if addrs:
        for r in con.execute("SELECT from_name, from_address, to_json, subject, body_text, COALESCE(received_at, sent_at) AS ts FROM mail_messages "
                             "WHERE COALESCE(received_at, sent_at) >= ? AND body_text LIKE '%http%' ORDER BY ts DESC LIMIT 600", (since,)):
            who = {(r["from_address"] or "").lower()} | {x.get("address", "").lower() for x in json.loads(r["to_json"] or "[]")}
            if not who & addrs:
                continue
            for u in SHARE.findall(r["body_text"] or "") and [m.group(0) for m in SHARE.finditer(r["body_text"] or "")]:
                key = re.sub(r"[?&]e=\w+", "", u)
                if key not in seen:
                    seen.add(key)
                    out.append({"title": re.sub(r"%20", " ", u.split("/")[-1].split("?")[0]) or "shared file", "url": u, "who": r["from_name"],
                                "where": f"email “{r['subject']}”", "when": (r["ts"] or "")[:10]})
    # a shared folder: put the files Assist knows inside it first (direct links open the deck itself)
    files = []
    for l in [x for x in out if ":f:" in x["url"]]:
        for r in con.execute("SELECT subject, url, ts FROM items WHERE source_id='sharepoint' AND kind='doc' AND thread LIKE ? ORDER BY ts DESC LIMIT 6",
                             ("%/" + l["title"],)):
            if r["url"] and r["url"] not in {f["url"] for f in files}:
                files.append({"title": r["subject"], "url": r["url"], "who": l["who"], "where": f"{l['where']} (in the shared folder {l['title']})",
                              "when": (r["ts"] or "")[:10]})
    return (files + out)[:limit]


KIND = {":f:": "shared folder", ":p:": "PowerPoint", ":w:": "Word document", ":x:": "Excel workbook", ":b:": "PDF", ":u:": "file"}


def _title(t, u):
    if t and not t.startswith("http"):
        return t
    name = re.sub(r"%20", " ", u.split("?")[0].rstrip("/").split("/")[-1])
    if "." in name[-6:]:
        return name
    return next((v for k, v in KIND.items() if k in u), "shared file")


def links_section(links):
    out = [f"## Files shared as links ({len(links)})",
           f"The originals people shared. When the brief mentions one of these, link it directly as [Title](url) so {USER.first} opens the real deck "
           "or folder, not a text copy. Prefer the file (e.g. the .pptx) over the folder it sits in."]
    out += [f"- [{_title(l['title'], l['url'])}]({l['url']}) · shared by {l['who']} in {l['where']} · {l['when']}" for l in links] or ["- none"]
    out.append("")
    return out


def section(docs):
    fence = "~~~"
    out = [f"## Documents in play ({len(docs)})",
           "Reference a document in the brief as [Name](doc:<id>) so it renders as a clickable chip that opens the original file (its "
           "SharePoint/OneDrive/Teams copy, or the email it came with). If the same file also appears under 'Files shared as links', "
           "prefer that direct link. The text below is what Assist extracted "
           "(capped); when it is missing, say you could not read the document rather than guess its content."]
    budget = TOTAL
    for d in docs:
        out.append(f"### {d['name']} · doc:{d['id']}")
        out.append(f"{d['source']} · {d['where']} · {d['when']}" + (f" · [open]({d['link']})" if d["link"] else ""))
        if d.get("card"):   # Claude's document card (assist/doccards.py): short, structured, version-aware; preferred over raw text
            out += [fence + "card", d["card"].replace(fence, "~ ~ ~"), fence]
        elif d["text"] and budget > 0:
            t = _clip(d["text"], min(PER_DOC, budget))
            budget -= len(t)
            out += [fence + "text", t.replace(fence, "~ ~ ~"), fence]
        else:
            out.append("_no text available_" if not d["text"] else "_text omitted (length budget)_")
    if not docs:
        out.append("- none found")
    out.append("")
    return out
