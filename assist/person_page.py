"""Everything about one person for the person page (People › person), in one read: what is coming up with them, what is open
between them and Sam, how often they talk, the last time on each channel, their own recent words (chat, email, meetings),
the documents they shared, were sent or are named in, the initiatives and roadmap items they are part of, and who they
work with most. Read only; built from the links assist/entities.py made (the same "shown" rule as the timeline: Sam's tick,
or unreviewed with confidence >= 0.6, never a cross). The day-by-day activity stays on /api/entities/person/{id}."""
import json
import re
from datetime import datetime, timedelta, timezone
from statistics import median

from . import loops, speakers
from . import org
from .entities import DM_KINDS, ME, item_link

# taking part in an item, as opposed to being named in it (mentioned, keyword, actor, domain, account)
INVOLVED = ("from", "author", "speaker", "dm", "organizer", "to", "attendee", "cc", "invitee", "member", "owner", "shared")
CONTACT_KINDS = ("mail", "sent", "chat", "note", "event")   # channels are broadcast: they say nothing about contact with Sam
DOC_PREFIX = {"sharepoint": "sp", "acme-kb": "kb", "local": "lf"}
HOW_RANK = {"theirs": 5, "sent": 4, "shared_with": 3, "discussed": 2, "named": 1}
NOT_A_DOC = re.compile(r"\.(png|jpe?g|gif|bmp|heic|webp|ics|vcf|skill)$|^image\d*\.", re.I)   # pasted images, signatures, invites


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _shown(a):
    return f"(COALESCE({a}.verdict, '') = 'confirmed' OR ({a}.verdict IS NULL AND {a}.confidence >= 0.6))"


def _clean(s, n=320):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _doc_key(name):
    """One key for copies of a file: "Plan (2).docx", "plan.pdf" and "Plan" are the same document."""
    k = re.sub(r"\.[a-z0-9]{2,5}$", "", name.strip().lower())
    k = re.sub(r"\s*\(\d+\)$|[_\s-]+(final|v\d+)$", "", k)
    return re.sub(r"[\s_\-]+", " ", k).strip()


def _in(xs):
    return ",".join("?" * len(xs))


def build(con, pid):
    p = con.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()
    if not p:
        return None
    now = datetime.now(timezone.utc)
    since90, since30 = _iso(now - timedelta(days=90)), _iso(now - timedelta(days=30))
    name, first = p["name"], p["name"].split(" ")[0]
    out = {"id": pid, "name": name}

    # ---- how to reach them
    addrs = [a for (a,) in con.execute("SELECT alias FROM people_aliases WHERE person_id=? AND alias LIKE '%@%'", (pid,))]
    used = {a: n for a, n in con.execute(f"SELECT LOWER(from_address), COUNT(*) FROM mail_messages WHERE LOWER(from_address) IN ({_in(addrs) or 'NULL'}) "
                                          f"GROUP BY 1", addrs)} if addrs else {}
    # the address they write from most; partners often also have an Acme guest address they never use
    email = max(addrs, key=lambda a: (used.get(a.lower(), 0), org.is_primary_address(a))) if addrs else ""
    out["email"] = email
    out["teams"] = f"https://teams.microsoft.com/l/chat/0/0?users={email}" if org.is_primary_address(email) else ""

    out["upcoming"] = upcoming(con, pid, now)

    # ---- open between them and Sam (the register), and what closed in the last 30 days
    out["open"] = [loops._row(con, r) for r in con.execute(
        "SELECT * FROM loops WHERE person_id=? AND status IN ('open','snoozed') ORDER BY origin_at", (pid,))]
    out["closed"] = [loops._row(con, r) for r in con.execute(
        "SELECT * FROM loops WHERE person_id=? AND status IN ('done','dropped') AND closed_at >= ? ORDER BY closed_at DESC LIMIT 12", (pid, since30))]

    # ---- contact: last time on each channel, contact days per week (12 weeks), usual gap between contacts
    rows = con.execute(f"SELECT i.id, i.kind, i.ts, i.subject, i.text, i.url, m.role, mt.id AS meeting_id, cm.conversation_kind, cm.conversation_name, cm.author, mm.folder "
                       f"FROM mentions m JOIN items i ON i.id=m.ref_id LEFT JOIN meetings mt ON mt.note_item_id=i.id "
                       f"LEFT JOIN chat_messages cm ON cm.item_id=i.id LEFT JOIN mail_messages mm ON mm.item_id=i.id "
                       f"WHERE m.ref_type='item' AND m.entity_type='person' AND m.entity_id=? AND i.noise=0 AND i.kind IN ({_in(CONTACT_KINDS)}) "
                       f"AND m.role IN ({_in(INVOLVED)}) AND {_shown('m')} AND i.ts >= ? AND i.ts <= ? ORDER BY i.ts DESC",
                       (pid, *CONTACT_KINDS, *INVOLVED, _iso(now - timedelta(days=84)), _iso(now))).fetchall()
    last = {}
    for r in rows:
        ch = "email" if r["kind"] in ("mail", "sent") else "chat" if r["kind"] == "chat" else "meeting" if r["kind"] in ("note", "event") else None
        if ch == "meeting" and r["kind"] == "event" and "meeting" in last:
            continue
        if ch and ch not in last:
            mine = r["folder"] == "sentitems" or r["kind"] == "sent" or bool(ME.search(r["author"] or ""))
            last[ch] = {"ts": r["ts"], "title": _clean(r["subject"] or r["text"], 140), "url": item_link(dict(r)), "mine": mine,
                        "where": ("DM" if r["conversation_kind"] in DM_KINDS else r["conversation_name"]) if ch == "chat" else None}
    out["last"] = last
    days = sorted({r["ts"][:10] for r in rows}, reverse=True)
    weeks = [0] * 12
    for d in days:
        k = (now.date() - datetime.fromisoformat(d).date()).days // 7
        if 0 <= k < 12:
            weeks[11 - k] += 1
    gaps = [(datetime.fromisoformat(a) - datetime.fromisoformat(b)).days for a, b in zip(days, days[1:])]
    out["contact"] = {"weeks": weeks, "days_84": len(days), "usual_gap": round(median(gaps)) if len(gaps) >= 3 else None,
                      "since_last": (now.date() - datetime.fromisoformat(days[0]).date()).days if days else None}
    out["counts_30"] = {
        "email": sum(1 for r in rows if r["kind"] in ("mail", "sent") and r["ts"] >= since30),
        "messages": sum(1 for r in rows if r["kind"] == "chat" and r["ts"] >= since30),
        "meetings": len({r["id"] for r in rows if r["kind"] == "note" and r["ts"] >= since30})}

    # ---- in their own words: chat messages and emails they wrote, and their main points in meetings (newest first)
    said = []
    for r in con.execute(f"SELECT i.id, i.kind, i.ts, i.url, cm.body_text, cm.conversation_name, cm.conversation_kind, cm.web_link FROM mentions m "
                         f"JOIN items i ON i.id=m.ref_id JOIN chat_messages cm ON cm.item_id=i.id WHERE m.ref_type='item' AND m.entity_type='person' "
                         f"AND m.entity_id=? AND m.role IN ('author','from') AND {_shown('m')} AND i.noise=0 AND i.ts >= ? ORDER BY i.ts DESC LIMIT 400",
                         (pid, since90)):
        t = _clean(r["body_text"], 420)
        if len(t) < 30:   # "ok", "thanks", emoji: not worth a line
            continue
        said.append({"kind": "chat", "ts": r["ts"], "text": t, "dm": r["conversation_kind"] in DM_KINDS, "channel": r["kind"] == "channel",
                     "where": "DM" if r["conversation_kind"] in DM_KINDS else r["conversation_name"] or "", "url": r["web_link"] or r["url"] or f"#/messages?open={r['id']}"})
    for r in con.execute(f"SELECT i.id, i.kind, i.ts, i.subject, i.text, i.url, mm.preview FROM mentions m JOIN items i ON i.id=m.ref_id "
                         f"LEFT JOIN mail_messages mm ON mm.item_id=i.id WHERE m.ref_type='item' AND m.entity_type='person' AND m.entity_id=? "
                         f"AND m.role='from' AND i.kind='mail' AND {_shown('m')} AND i.noise=0 AND i.ts >= ? ORDER BY i.ts DESC LIMIT 60", (pid, since90)):
        said.append({"kind": "email", "ts": r["ts"], "subject": r["subject"] or "", "text": _clean(r["preview"] or r["text"], 320), "url": item_link(dict(r))})
    for m in speakers.for_person(con, pid, limit=12):
        ts = m["starts_at"] if m["starts_at"].endswith("Z") else m["starts_at"] + "Z"
        said.append({"kind": "meeting", "ts": ts, "meeting_id": m["meeting_id"], "title": m["title"], "share": m["share"], "points": m["points"],
                     "url": f"#/meetings/m-{m['meeting_id']}"})
    # each kind keeps its own share, so a chatty week does not push their meeting points off the page
    cap = {"chat": 40, "channel": 15, "email": 20, "meeting": 12}
    kept, seen_k = [], {}
    for x in sorted(said, key=lambda x: x["ts"], reverse=True):
        k = "channel" if x.get("channel") else x["kind"]
        seen_k[k] = seen_k.get(k, 0) + 1
        if seen_k[k] <= cap[k]:
            kept.append(x)
    out["said"] = kept

    # ---- documents: theirs (owner / shared / sent as attachments), shared with them, discussed in meetings with them, naming them
    docs, key_of = {}, {}   # one entry per document: copies match by id (file name vs card title) or by name

    def add(doc_id, name, ts, how, where="", url=""):
        if not doc_id or not name or NOT_A_DOC.search(name):
            return
        k = key_of.get(doc_id) or _doc_key(name)
        d = docs.get(k)
        if not d:
            docs[k] = {"id": doc_id, "ids": [doc_id], "name": name.strip(), "ts": ts, "how": how, "where": where, "url": url, "copies": 1}
            key_of[doc_id] = k
            return
        key_of[doc_id] = k
        if doc_id not in d["ids"]:
            d["copies"] += 1
            d["ids"].append(doc_id)
        if HOW_RANK[how] > HOW_RANK[d["how"]]:
            d.update(how=how, where=where or d["where"])
        if (ts or "") > (d["ts"] or ""):
            d.update(ts=ts, id=doc_id, url=url or d["url"])

    for r in con.execute(f"SELECT i.id, i.source_id, i.subject, i.ts, i.url, i.thread, m.role FROM mentions m JOIN items i ON i.id=m.ref_id "
                         f"WHERE m.ref_type='item' AND m.entity_type='person' AND m.entity_id=? AND i.kind='doc' AND {_shown('m')}", (pid,)):
        pre = DOC_PREFIX.get(r["source_id"])
        if pre:
            add(f"{pre}-{r['id']}", r["subject"], r["ts"], "theirs" if r["role"] in ("from", "owner", "shared") else "named", r["thread"] or "", r["url"] or "")
    # shared in a message: by them (they wrote it) or to them (they were on it)
    for r in con.execute(f"SELECT d.id, d.source_id, d.subject, d.url, i.ts, i.kind, mp.role, COALESCE(cm.conversation_name, i.subject) AS where_ FROM mentions md "
                         f"JOIN items d ON d.id=md.entity_id JOIN items i ON i.id=md.ref_id JOIN mentions mp ON mp.ref_type='item' AND mp.ref_id=md.ref_id "
                         f"AND mp.entity_type='person' AND mp.entity_id=? LEFT JOIN chat_messages cm ON cm.item_id=i.id "
                         f"WHERE md.ref_type='item' AND md.entity_type='doc' AND md.role IN ('shared','discussed') AND {_shown('mp')} "
                         f"AND COALESCE(md.verdict, '') != 'rejected' AND mp.role IN ({_in(INVOLVED)})", (pid, *INVOLVED)):
        pre = DOC_PREFIX.get(r["source_id"])
        if not pre:
            continue
        how = "discussed" if r["kind"] == "note" else "theirs" if r["role"] in ("from", "author") else "shared_with"
        add(f"{pre}-{r['id']}", r["subject"], r["ts"], how, r["where_"] or "", r["url"] or "")
    # email attachments: sent by them, sent by Sam to them, or by someone else to a list they were on
    for r in con.execute(f"SELECT a.id, a.name, mm.subject, mm.from_name, COALESCE(mm.received_at, mm.sent_at) AS ts, mm.folder, m.role FROM mentions m "
                         f"JOIN mail_attachments a ON a.item_id=m.ref_id AND a.is_inline=0 JOIN mail_messages mm ON mm.item_id=a.item_id "
                         f"WHERE m.ref_type='item' AND m.entity_type='person' AND m.entity_id=? AND m.role IN ('from','to','cc') AND {_shown('m')}", (pid,)):
        if r["role"] == "from":
            add(f"ma-{r['id']}", r["name"], r["ts"], "theirs", r["subject"] or "")
        elif r["folder"] == "sentitems":
            add(f"ma-{r['id']}", r["name"], r["ts"], "sent", r["subject"] or "")
        else:
            add(f"ma-{r['id']}", r["name"], r["ts"], "shared_with", f"{r['from_name'] or 'Email'} · {r['subject'] or ''}")
    try:
        for r in con.execute(f"SELECT a.id, a.name, a.url, cm.sent_at, cm.conversation_name FROM mentions m JOIN chat_attachments a ON a.item_id=m.ref_id "
                             f"JOIN chat_messages cm ON cm.item_id=a.item_id WHERE m.ref_type='item' AND m.entity_type='person' AND m.entity_id=? "
                             f"AND m.role IN ('author','from') AND {_shown('m')}", (pid,)):
            add(f"ca-{r['id']}", r["name"], r["sent_at"], "theirs", r["conversation_name"] or "", r["url"] or "")
    except Exception:   # chat attachments not pulled yet
        pass
    # documents whose card names them (full name, or a first name no one else in People has)
    firsts = [n.split(" ")[0] for (n,) in con.execute("SELECT name FROM people")]
    names = {name} | ({first} if firsts.count(first) == 1 else set())
    for r in con.execute("SELECT doc_id, title, people, doc_date, created_at FROM doc_cards WHERE COALESCE(is_current, 1)=1 AND people LIKE ?", (f"%{first}%",)):
        if names & set(json.loads(r["people"] or "[]")):
            add(r["doc_id"], r["title"], r["doc_date"] or r["created_at"], "named")
    every = sorted({i for d in docs.values() for i in d["ids"]})
    cards = {r["doc_id"]: r for r in con.execute(f"SELECT doc_id, title, kind, summary, sensitivity FROM doc_cards WHERE doc_id IN ({_in(every) or 'NULL'})", every)}
    filed = {r["doc_id"]: r["sensitivity"] for r in con.execute(f"SELECT doc_id, sensitivity FROM doc_folders WHERE doc_id IN ({_in(every) or 'NULL'})", every)} \
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='doc_folders'").fetchone() else {}
    for d in docs.values():
        c = cards.get(d["id"]) or next((cards[i] for i in d["ids"] if i in cards), None)   # any copy's card describes the document
        d["kind"] = c["kind"] if c else ""
        d["summary"] = _clean(c["summary"], 220) if c else ""
        d["title"] = c["title"] if c and c["title"] else ""
        # kept off screen until Sam opens them (screen sharing): any copy marked HR/legal or personal
        d["sensitive"] = any((cards[i]["sensitivity"] if i in cards else filed.get(i)) in ("hr-legal", "personal") for i in d["ids"])
        d.pop("ids")
        d["ext"] = (d["name"].rsplit(".", 1)[-1].lower() if "." in d["name"][-6:] else "")
    out["documents"] = sorted(docs.values(), key=lambda d: d["ts"] or "", reverse=True)[:60]

    # ---- initiatives: where they are a key person, and how much of their last 90 days touches each
    n_by = {r["id"]: r["n"] for r in con.execute(
        f"SELECT mi.entity_id AS id, COUNT(DISTINCT mp.ref_id) AS n FROM mentions mp JOIN items i ON i.id=mp.ref_id "
        f"JOIN mentions mi ON mi.ref_type='item' AND mi.ref_id=mp.ref_id AND mi.entity_type='initiative' "
        f"WHERE mp.ref_type='item' AND mp.entity_type='person' AND mp.entity_id=? AND {_shown('mp')} AND {_shown('mi')} AND i.ts >= ? AND i.noise=0 "
        f"GROUP BY mi.entity_id", (pid, since90))}
    inis = []
    for r in con.execute("SELECT id, slug, name, weight, key_people, owner FROM initiatives WHERE COALESCE(active, 1)=1 AND merged_into IS NULL"):
        key = name in json.loads(r["key_people"] or "[]")
        if key or n_by.get(r["id"], 0) >= 3:
            inis.append({"slug": r["slug"], "name": r["name"], "weight": r["weight"], "key": key, "n": n_by.get(r["id"], 0)})
    out["initiatives"] = sorted(inis, key=lambda x: (not x["key"], -(x["weight"] or 0), -x["n"]))

    # ---- roadmap items they own (Rowan's Roadmap Workbook snapshot, assist/roadmap.py)
    order = {"inflight": 0, "planned": 1, "shipped": 2}
    out["roadmap"] = sorted([{"id": r["id"], "name": r["name_internal"] or r["name_external"], "status": r["status"] or "", "horizon": r["horizon"] or ""}
                             for r in con.execute("SELECT id, name_internal, name_external, status, horizon, owners FROM roadmap_items WHERE owners LIKE ?", (f"%{name}%",))
                             if name in json.loads(r["owners"] or "[]")], key=lambda x: (order.get(x["status"], 3), x["id"]))

    # ---- who they work with: other people on the same meetings, emails and group chats (90 days, Sam left out)
    out["with"] = [dict(r) for r in con.execute(
        f"SELECT p.id, p.name, COALESCE(p.title, p.role, '') AS title, p.avatar, COUNT(DISTINCT m1.ref_id) AS n FROM mentions m1 JOIN items i ON i.id=m1.ref_id "
        f"JOIN mentions m2 ON m2.ref_type='item' AND m2.ref_id=m1.ref_id AND m2.entity_type='person' AND m2.entity_id != m1.entity_id "
        f"JOIN people p ON p.id=m2.entity_id WHERE m1.ref_type='item' AND m1.entity_type='person' AND m1.entity_id=? AND i.ts >= ? AND i.noise=0 "
        f"AND i.kind IN ('mail','sent','chat','note','event') AND m1.role IN ({_in(INVOLVED)}) AND m2.role IN ({_in(INVOLVED)}) "
        f"AND {_shown('m1')} AND {_shown('m2')} AND COALESCE(p.is_me, 0)=0 GROUP BY p.id ORDER BY n DESC LIMIT 8",
        (pid, since90, *INVOLVED, *INVOLVED))]
    out["topics"] = on_the_table(con, pid, name)
    out["profile_updated"] = (p["updated_at"] or "")[:10]
    return out



def upcoming(con, pid, now=None, limit=6):
    """Meetings with them in the next 14 days (cancelled, past, personal and repeated ones left out), soonest first, with
    the prep brief when there is one."""
    now = now or datetime.now(timezone.utc)
    from . import prep
    briefs = prep._briefs(con)
    up, seen = [], set()
    for r in con.execute(f"SELECT i.id, i.ts, i.subject, i.url, i.payload, m.role FROM mentions m JOIN items i ON i.id=m.ref_id WHERE m.ref_type='item' "
                         f"AND m.entity_type='person' AND m.entity_id=? AND i.kind='event' AND i.ts >= ? AND i.ts <= ? AND {_shown('m')} ORDER BY i.ts",
                         (pid, _iso(now - timedelta(hours=1)), _iso(now + timedelta(days=14)))):
        pl = json.loads(r["payload"] or "{}")
        st, en = prep._utc(pl.get("start") or r["ts"]), prep._utc(pl.get("end"))
        subject = (pl.get("subject") or r["subject"] or "").strip()
        if pl.get("isCancelled") or not st or (en and en < now) or (subject.lower(), st) in seen or prep.PERSONAL.search(subject):
            continue
        seen.add((subject.lower(), st))
        att = [a for a in (pl.get("attendees") or []) if a and not prep.SAM.search(a)]
        eid = pl.get("id")
        up.append({"event_id": eid, "item_id": r["id"], "subject": subject, "start": st.isoformat(), "end": en.isoformat() if en else None,
                   "others": len(att), "one_to_one": len(att) == 1, "join_url": prep._join(pl), "web_link": pl.get("webLink") or r["url"] or "",
                   "brief": briefs.get(eid), "organizer": prep._name(pl.get("organizer") or "")})
    return up[:limit]


def on_the_table(con, pid, name, limit=5):
    """The current Top of mind topics (assist/topics.py) this person raised or is part of, the ones they raised first, then
    the ones they are most involved in (a topic lists its people most involved first). A topic names people as the run
    wrote them, so a name matches by the full name, any name alias SleePO holds for them, or a first name no one else in
    People has. Reads only."""
    from . import db, topics
    if not db.has_table(con, "topics"):
        return []
    first = name.split(" ")[0].lower()
    names = {name.lower()} | {a for (a,) in con.execute("SELECT LOWER(alias) FROM people_aliases WHERE person_id=? AND alias NOT LIKE '%@%'", (pid,))}
    uniq = [n.split(" ")[0].lower() for (n,) in con.execute("SELECT name FROM people")].count(first) == 1

    def is_them(n):
        n = re.sub(r"\s*\(.*\)$", "", (n or "").strip()).lower()   # "Nell Harlow (塩谷 晴久)"
        return bool(n) and n != "you" and (n in names or (uniq and n.split(" ")[0] == first))

    out = []
    for i, t in enumerate(topics.listing(con)["topics"]):
        where = next((k for k, n in enumerate(t["people"]) if is_them(n)), None)
        raised = is_them(t["raised_by"])
        if where is None and not raised:
            continue
        out.append(({"id": t["id"], "title": t["title"], "summary": t["summary"] or "", "ask": t["ask"] or "", "initiative": t["initiative"],
                     "initiative_slug": t["initiative_slug"], "area_name": t["area_name"], "private": t["private"], "pinned": t["pinned"],
                     "raised": "them" if raised else "you" if (t["raised_by"] or "").lower() == "you" else (t["raised_by"] or ""),
                     "last_ts": t["last_ts"], "is_new": t["is_new"]}, (not raised, where if where is not None else 99, i)))
    return [x for x, _ in sorted(out, key=lambda x: x[1])][:limit]
