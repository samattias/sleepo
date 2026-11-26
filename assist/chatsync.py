"""Full Teams and Slack messages (text, links, attachment metadata), kept for a limited time.

Pulled by Claude Code through the Microsoft 365 and Slack connectors and written in an ingest bundle under
"chat_messages" (see store_record). Attachments are recorded as name, type, size and link only; files are never
downloaded.

Retention follows the organisation's policy for personal data: full messages older than RETENTION_DAYS
(assist/retention.py) are purged after every ingest. Purging removes the full text, links and attachment rows; a message row
that only existed because of the full pull is deleted too, while a gist row the assistant wrote earlier stays.
"""
import html
import json
import re
import time
from datetime import datetime, timezone

from . import db
from . import profile

FULL = "chat-full"   # items.retention marker for rows created by this module


# Sam reads one-to-one DMs, not Slack channels, except the few he follows. Other Slack channels are background only:
# search, initiatives, person pages, prep and strategy use them; the brief and the open-items extraction do not.
FOLLOWED_CHANNELS = ()   # settings key followed_channels (JSON list) overrides


def followed_channels(con):
    row = con.execute("SELECT value FROM settings WHERE key='followed_channels'").fetchone()
    try:
        v = json.loads(row["value"]) if row else None
    except ValueError:
        v = None
    return [str(x) for x in v] if isinstance(v, list) else list(FOLLOWED_CHANNELS)


def read_filter(con, a):
    """SQL condition (and params) for chat messages Sam actually reads, with `a` the chat_messages alias: everything
    except Slack channels, plus followed channels, his own posts, messages naming him and threads he posted in."""
    ch = followed_channels(con)
    mine = f"SELECT thread_parent FROM chat_messages WHERE source_id='slack' AND {profile.sql_mentions('author')} AND thread_parent IS NOT NULL"
    sql = (f"({a}.conversation_kind != 'channel' OR {a}.source_id != 'slack'"
           + (f" OR {a}.conversation_name IN ({','.join('?' * len(ch))})" if ch else "")
           + f" OR {mentions_me(a)}"
           f" OR {a}.thread_parent IN ({mine}) OR {a}.external_id IN ({mine}))")
    return sql, ch


def cutoff(days):
    return datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# How the pulls name a direct message ("DM Rowan Lowell", "1:1 chat Noel Osborne", "Chat with Gray Selby (topic)"), and the
# names that say nothing about who is in a chat
DM_NAME = re.compile(r"^(?:dm\s*:?\s*(?:with\s+)?|1:1\s+chat\s+(?:with\s+)?|chat\s*:?\s*(?:with\s+)?|direct\s+message\s+(?:with\s+)?)", re.I)
GENERIC = re.compile(r"^(?:group chat|group dm|meeting chat|chat|dm|1:1 chat|)$", re.I)
CHAT_PREFIX = re.compile(r"^(?:group chat|meeting chat|group dm|chat with|chat)\b\s*:?\s*", re.I)
PAREN = re.compile(r"\s*\(([^)]*)\)\s*$")
PLAIN = re.compile(r"^(?:group(?: chat)?|meeting(?: chat)?|dm|[0-9a-f]{6,})$", re.I)


def mentions_me(a):
    """SQL: a chat message (alias a) by the user or naming them: their full name or address, or an @-mention of their first name."""
    first = profile.first_name().replace("'", "''")
    at = f" OR {a}.body_text LIKE '%@{first}%'" if first else ""
    return f"{profile.sql_mentions(a + '.author')} OR {profile.sql_mentions(a + '.body_text')}{at}"


def _sam(name):
    return profile.mentions_me(name or "")


def _chat_name(con, names):
    """A group chat's own name from the names the pulls gave its messages ("work trip (group)", "Meeting chat (NWT / ChatGPT
    Enterprise integration)"), the most used; None when they only list people ("Group chat Noel Osborne, Gray Selby")."""
    from . import relevance
    seen = {}
    for n in names:
        n = (n or "").strip()
        m = PAREN.search(n)
        rest = CHAT_PREFIX.sub("", PAREN.sub("", n)).strip()
        if m and m.group(1).strip() and not PLAIN.match(m.group(1).strip()):
            name = m.group(1).strip()
        elif rest and not CHAT_PREFIX.match(n) and "," not in rest and not relevance.resolve(con, rest):
            name = rest
        else:
            continue
        seen[name] = seen.get(name, 0) + 1
    return max(seen, key=seen.get) if seen else None


NAME_SPLIT = re.compile(r"\s*(?:[,/+&;:]|\band\b)\s*", re.I)
NAME_FILLER = {"group", "chat", "dm", "meeting", "teams", "slack", "channel", "with", "others", "other", "the", "you"}


def _people_only(text, known, cid=""):
    """True when a name a pull gave a chat only lists people (known: lowercased words of people's names), counts, ids or
    filler ("Gray Selby chat", "Rowan Lowell + 4", "Sam / Gray / Harper", "6db63e", a piece of the chat's id "MThlNjBk")."""
    cid = (cid or "").lower()
    for part in NAME_SPLIT.split(text):
        for w in re.findall(r"[\w'-]+", part.lower()):
            if w not in known and w not in NAME_FILLER and not w.isdigit() and not re.fullmatch(r"[0-9a-f]{6,}", w) \
                    and not (len(w) >= 6 and w in cid):
                return False
    return True


def _topic(name, known, cid=""):
    """The chat's own topic in a name a pull gave it ("Group chat: Copilot+ (Gray Selby, Ellis Ingram)" → "Copilot+", "Meeting chat:
    Claude learning session" → itself), or None when it only names people ("Group chat: Harper Brook", "Teams group chat
    6db63e", "Rowan Lowell + 4 (group chat)")."""
    n = re.sub(r"^teams\s+", "", (name or "").strip(), flags=re.I)
    n = CHAT_PREFIX.sub("", n).strip()
    m = PAREN.search(n)
    for cand in (PAREN.sub("", n).strip(), (m.group(1).strip() if m else "")):
        cand = re.sub(r"\s+(?:group\s+)?chat$", "", cand, flags=re.I).strip()
        if cand and not PLAIN.match(cand) and not _people_only(cand, known, cid):
            return cand
    return None


def _first_name(author):
    """An author's first name; "Butler, Tom" is Tom Butler."""
    a = (author or "").strip()
    if "," in a:
        last, first = a.split(",", 1)
        a = f"{first.strip()} {last.strip()}".strip()
    return a.split()[0] if a.split() else a


def chat_titles(con, ids):
    """One title per Teams or Slack group or meeting chat, by conversation id (Sam, 17 Nov 2026: "I can't see my latest Teams
    messages ... between Milo, Vale, Parker ... Rowan, Harper and Gray": each pull names a chat its own way, one chat had nine
    names, and the Messages page, grouping by name, split it into nine rows under names like "Teams group chat 6db63e"). The
    chat's topic when the newest name carries one ("Copilot+", "AI Initiatives report"), else the people who wrote in it, most active
    first, first names ("Gray, Harper, Rowan"); a meeting chat without a topic says so. Reads only."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    known = {w for (n,) in con.execute("SELECT name FROM people WHERE COALESCE(name, '') != ''") for w in re.findall(r"[\w'-]+", n.lower())}
    q = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT conversation_id, conversation_name, conversation_kind, author, sent_at FROM chat_messages "
                       f"WHERE conversation_id IN ({q}) ORDER BY sent_at DESC", ids).fetchall()
    by = {}
    for r in rows:
        by.setdefault(r["conversation_id"], []).append(r)
    out = {}
    for cid, msgs in by.items():
        authors = [m["author"] for m in msgs if m["author"]]
        known_here = known | {w for a in authors for w in re.findall(r"[\w'-]+", a.lower())}
        topic = _topic(msgs[0]["conversation_name"], known_here, cid)
        counts = {}
        for a in authors:
            if not _sam(a):
                counts[a] = counts.get(a, 0) + 1
        firsts = list(dict.fromkeys(_first_name(a) for a in sorted(counts, key=lambda a: -counts[a])))
        people = ", ".join(firsts[:4]) + (f" +{len(firsts) - 4}" if len(firsts) > 4 else "")
        meeting = cid.startswith("19:meeting_") or any(m["conversation_kind"] == "meeting" for m in msgs) \
            or (msgs[0]["conversation_name"] or "").lower().startswith("meeting")
        # one person so far reads like a direct message: say it is a group chat
        out[cid] = topic or (f"Meeting chat · {people}" if meeting and people else "Meeting chat" if meeting
                             else f"Group chat · {people}" if len(firsts) == 1 else people or "Group chat")
    return out


def latest(con, days=7, n=30):
    """The conversations Sam reads with a message in the last `days`, newest first, each with its newest message in a line
    (Today's Messages widget; Sam, 30 Oct 2026): direct messages, group and meeting chats, and of the channels only those he
    follows or posts naming him (read_filter; no noise). A direct message is one conversation per person across Teams and
    Slack, as on the Messages page; a group chat is named by its own name, else by who wrote in it. Reads only."""
    from . import relevance
    from .initiative_work import _plain, _unquote
    flt, ch = read_filter(con, "m")
    mention = mentions_me("m")
    rows = con.execute(
        "SELECT m.item_id, m.source_id, m.conversation_id, m.conversation_name, m.conversation_kind, m.author, m.sent_at, m.body_text, "
        "p.name AS person, (SELECT COUNT(*) FROM chat_attachments a WHERE a.item_id=m.item_id) AS files "
        "FROM chat_messages m JOIN items i ON i.id=m.item_id LEFT JOIN people p ON p.id=i.from_person_id "
        f"WHERE m.sent_at >= ? AND COALESCE(i.noise, 0)=0 AND {flt} AND (COALESCE(m.conversation_kind, '') != 'channel' "
        f"OR m.conversation_name IN ({','.join('?' * len(ch)) or 'NULL'}) OR {mention}) ORDER BY m.sent_at DESC, m.item_id DESC",
        [cutoff(days), *ch, *ch]).fetchall()
    raw = {}
    for r in rows:
        raw.setdefault((r["source_id"], r["conversation_id"] or r["conversation_name"] or ""), []).append(r)
    out = {}
    for (app, conv), msgs in raw.items():
        last = msgs[0]
        kind = last["conversation_kind"] if last["conversation_kind"] in ("dm", "group", "meeting", "channel") else "group"
        name = (last["conversation_name"] or "").strip()
        others = [m for m in msgs if not _sam(m["author"])]
        firsts = list(dict.fromkeys((m["person"] or m["author"] or "").split(" ")[0] for m in others if m["person"] or m["author"]))
        person, key = None, f"{app}|{conv}"
        if kind == "dm":
            person = (others[0]["person"] or others[0]["author"]) if others else None
            if not person:   # only Sam wrote in it lately: the name, or an older message, says who it is with
                said = PAREN.sub("", DM_NAME.sub("", name)).strip()
                p = relevance.resolve(con, said) if said and not GENERIC.match(said) else None
                person = p["name"] if p else (said if said and not GENERIC.match(said) else None)
            if not person and last["conversation_id"]:
                r = con.execute("SELECT author FROM chat_messages WHERE conversation_id=? AND source_id=? AND COALESCE(author, '') != '' "
                                f"AND NOT {profile.sql_mentions('author')} ORDER BY sent_at DESC LIMIT 1", (last["conversation_id"], app)).fetchone()
                person = r["author"] if r else None
            title = person or "Direct message"
            key = f"dm|{person.lower()}" if person else key
        elif kind == "channel":
            title = name or "Channel"
        else:
            title = _chat_name(con, [m["conversation_name"] for m in msgs]) or (", ".join(firsts[:3]) if len(firsts) > 1 else "") \
                or ("Meeting chat" if kind == "meeting" else "Group chat") + (f" with {firsts[0]}" if firsts else "")
        c = out.get(key)
        if not c:
            c = out[key] = {"key": key, "kind": kind, "title": title, "person": person, "apps": [], "count": 0, "item_id": last["item_id"],
                            "app": app, "sent_at": last["sent_at"], "author": last["author"], "mine": _sam(last["author"]),
                            "text": _plain(_unquote(last["body_text"] or ""), 160), "files": last["files"], "people": []}
        elif last["sent_at"] > c["sent_at"]:   # the same person on the other app, more recently
            c.update(item_id=last["item_id"], app=app, sent_at=last["sent_at"], author=last["author"], mine=_sam(last["author"]),
                     text=_plain(_unquote(last["body_text"] or ""), 160), files=last["files"])
        c["apps"] = sorted(set(c["apps"]) | {app})
        c["count"] += len(msgs)
        c["people"] = list(dict.fromkeys(c["people"] + [m["person"] or m["author"] for m in others if m["person"] or m["author"]]))[:6]
    return sorted(out.values(), key=lambda c: c["sent_at"], reverse=True)[:n]


def html_to_text(s):
    """Teams bodies are HTML. Keep links as markdown, paragraphs as newlines, drop the rest."""
    if not s:
        return ""
    s = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f"[{re.sub('<[^>]+>', '', m.group(2)) or m.group(1)}]({m.group(1)})", s, flags=re.S | re.I)
    s = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "• ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(l.rstrip() for l in s.splitlines())).strip()


SECRET_PATTERNS = [
    # a code span or block holding one long random token (a pasted key): no spaces, dots or slashes, letters and digits
    (re.compile(r"(`{1,3})\s*(?=[^`\s]*\d)(?=[^`\s]*[A-Za-z])[A-Za-z0-9_+=-]{20,}\s*\1"), lambda m: f"{m.group(1)}[redacted]{m.group(1)}"),
    (re.compile(r"(?i)\b(api[_ -]?key|apikey|secret|token|password|passwd|pwd|client[_ -]?secret|access[_ -]?key)\b(\s*[:=]\s*|\s+is\s+)([`'\"]?)([^\s`'\"]{8,})\3"),
     lambda m: f"{m.group(1)}{m.group(2)}[redacted]"),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|xox[abprs]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"), lambda m: "[redacted]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{16,}"), lambda m: f"{m.group(1)}[redacted]"),
    (re.compile(r"(?<![\w.@/\\-])(?=[A-Za-z0-9+/=-]*\d)(?=[A-Za-z0-9+/=-]*[a-z])(?=[A-Za-z0-9+/=-]*[A-Z])[A-Za-z0-9+/-]{24,}={0,2}(?![\w.@/\\-])"), lambda m: "[redacted]"),
]


def redact(text):
    """Credentials never go into the database: API keys, tokens, passwords and long random strings are masked."""
    if not text:
        return text
    # Links are left intact (a mangled link is useless); everything between them is checked.
    parts = re.split(r"(https?://[^\s)\]>]+|\[[^\]\n]{1,200}\]\()", text)   # links and markdown link titles
    for i in range(0, len(parts), 2):
        for rx, rep in SECRET_PATTERNS:
            parts[i] = rx.sub(rep, parts[i])
    return "".join(parts)


def _match_existing(con, r, body=None):
    """Reuse the item row for this message: same external id, the same message stored by another pull under another id
    (same source, author, second and text), or the gist row written for it earlier (same source, same author first name,
    within 90 seconds)."""
    row = con.execute("SELECT item_id AS id FROM chat_messages WHERE source_id=? AND external_id=? ORDER BY item_id LIMIT 1",
                      (r["source_id"], r["external_id"])).fetchone() \
        or con.execute("SELECT id FROM items WHERE source_id=? AND external_id=?", (r["source_id"], r["external_id"])).fetchone()
    if row:
        return row["id"]
    # pulls name one message differently ("slack:D0…:1791391047.389929", "D0…:1791391047.389929", "slack:dm-gray:20261007T163727")
    if body:
        row = con.execute("SELECT item_id AS id FROM chat_messages WHERE source_id=? AND author=? AND substr(sent_at, 1, 19)=substr(?, 1, 19) "
                          "AND body_text=? ORDER BY item_id LIMIT 1", (r["source_id"], r.get("author"), r["ts"], body)).fetchone()
        if row:
            return row["id"]
    first = (r.get("author") or "").split(" ")[0].lower()
    if not first:
        return None
    # Older gist rows were written in London time but labelled UTC, so they can sit exactly an hour off.
    t = datetime.strptime(r["ts"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    best, best_d = None, 181
    for c in con.execute("SELECT id, from_name, ts FROM items WHERE source_id=? AND ts BETWEEN strftime('%Y-%m-%dT%H:%M:%SZ', ?, '-65 minutes') "
                         "AND strftime('%Y-%m-%dT%H:%M:%SZ', ?, '+65 minutes') AND id NOT IN (SELECT item_id FROM chat_messages) "
                         "AND external_id NOT GLOB 'slack:[CDG][A-Z0-9]*:[0-9]*.[0-9]*' AND external_id NOT LIKE 'teams:%'",
                         (r["source_id"], r["ts"], r["ts"])):
        if (c["from_name"] or "").split(" ")[0].lower() != first:
            continue
        ct = datetime.strptime(c["ts"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        d = min(abs(ct - t), abs(ct - t - 3600), abs(ct - t + 3600))
        if d < best_d:
            best, best_d = c["id"], d
    return best
    return None


def store_record(con, r, pull_id=None):
    """One message. r = {source_id: teams|slack, external_id, conversation_id, conversation_name, conversation_kind: dm|group|channel,
    ts (ISO UTC), author, body_text (plain text; links as markdown) or body_html, links: [{url, title}],
    attachments: [{name, content_type, size, url}], thread_parent, web_link, noise}"""
    if r.get("conversation_kind") == "oneOnOne":   # Teams' name for a direct message: one kind, so every reader sees it as a DM
        r = dict(r, conversation_kind="dm")
    body = redact(r.get("body_text") or html_to_text(r.get("body_html")))
    links = r.get("links") or [{"url": u, "title": t} for t, u in re.findall(r"\[([^\]]*)\]\((https?://[^)]+)\)", body)]
    iid = _match_existing(con, r, body)
    if iid is None:
        iid, _ = db.upsert_item(con, r["source_id"], r["external_id"], "chat" if r.get("conversation_kind") != "channel" else "channel", r["ts"],
                                pull_id=pull_id, from_name=r.get("author"), subject=None, text=body[:300], thread=r.get("conversation_name"),
                                url=r.get("web_link"), noise=r.get("noise"), retention=FULL, from_person_id=db.resolve_person(con, r.get("author")))
    con.execute("INSERT INTO chat_messages (item_id, source_id, external_id, conversation_id, conversation_name, conversation_kind, author, sent_at, "
                "body_text, links_json, thread_parent, web_link, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(item_id) DO UPDATE SET body_text=excluded.body_text, links_json=excluded.links_json, fetched_at=excluded.fetched_at",
                (iid, r["source_id"], r["external_id"], r.get("conversation_id"), r.get("conversation_name"), r.get("conversation_kind"),
                 r.get("author"), r["ts"], body, json.dumps(links), r.get("thread_parent"), r.get("web_link"), db.now()))
    # Teams search returns no attachments: only reading the message does, so a later pull that read the message from search
    # alone leaves the attachments an earlier pull recorded (29 Oct 2026)
    if r.get("attachments"):
        con.execute("DELETE FROM chat_attachments WHERE item_id=?", (iid,))
        for a in r["attachments"]:
            con.execute("INSERT INTO chat_attachments (item_id, name, content_type, size, url) VALUES (?,?,?,?,?)",
                        (iid, a.get("name"), a.get("content_type"), a.get("size"), a.get("url")))
    con.execute("DELETE FROM chat_fts WHERE rowid=?", (iid,))
    con.execute("INSERT INTO chat_fts (rowid, body_text, author, conversation) VALUES (?,?,?,?)",
                (iid, body, r.get("author") or "", r.get("conversation_name") or ""))
    return iid


def purge(con, days, log=print):
    if not days:
        return 0
    cut = cutoff(days)
    old = [r["item_id"] for r in con.execute("SELECT item_id FROM chat_messages WHERE sent_at < ?", (cut,))]
    for iid in old:
        con.execute("DELETE FROM chat_attachments WHERE item_id=?", (iid,))
        con.execute("DELETE FROM chat_fts WHERE rowid=?", (iid,))
        con.execute("DELETE FROM chat_messages WHERE item_id=?", (iid,))
        row = con.execute("SELECT retention FROM items WHERE id=?", (iid,)).fetchone()
        if row and row["retention"] == FULL:
            if con.execute("SELECT 1 FROM fact_sources WHERE item_id=? UNION SELECT 1 FROM mentions WHERE ref_type='item' AND ref_id=?", (iid, iid)).fetchone():
                con.execute("UPDATE items SET text=NULL, subject='(message older than the retention period)' WHERE id=?", (iid,))
            else:
                con.execute("DELETE FROM items WHERE id=?", (iid,))
    if old:
        log(f"chat retention: purged {len(old)} full messages older than {days} days")
    return len(old)
