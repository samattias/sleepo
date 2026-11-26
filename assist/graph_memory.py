"""Graph memory, phase 1 (DESIGN-GRAPH-MEMORY.md; Sam, 17 Nov 2026: "for every input we receive ... update the record for that
specific topic ... and traverse also the graph to look at related elements ... the first or second related nodes").

The code walks the graph, never the model. Each new item marks the records it touches, in table graph_touches:
  hop 1  its own sure links (bets, open tasks, people, companies, documents) and the current topics whose cited mail
         thread or chat conversation it continues;
  hop 2  only along chosen edges: a task's bet, a topic's bet, and the briefs of meetings in the next two working days
         that a person it links to attends. A person is never a pass-through (the user least of all).
Pages read what came in since their record was written (`since_record`); `report` measures the churn that sizes phase 2
(the model refresh). No model call here. `propagate` writes only when something new arrived (reads never write)."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import db
from .retention import RETENTION_DAYS

WINDOW_DAYS = 3                    # items said or sent in the last 3 days are new material; the morning rebuild reads the rest
KINDS = ("mail", "sent", "chat", "note", "doc", "opportunity")
HOP1 = ("initiative", "task", "person", "org", "doc")   # products, roadmap IDs and tickets hold no record to keep current
SURE = {"task": 0.8}               # task_links: sure from 0.8 (0.6-0.8 are its "Part of ...?" questions)
SHOWN = 0.6                        # every other kind: the pages' rule (entities._shown): confirmed, or unreviewed at 0.6+
CAP = {"initiative": 3, "task": 3, "topic": 3, "person": 8, "org": 3, "doc": 3, "event": 3}   # per item, strongest first
TASK_LIVE = ("open", "suggested", "snoozed")
BRIEF_DAYS = 2                     # a person's meetings until the end of the next working day (prep.upcoming)
RECORDS = ("initiative", "topic", "task", "event")       # the kinds that hold a record today (people and companies: phase 3)
SHOWN_KINDS = RECORDS + ("person", "org", "doc")
REFRESH_AFTER_HOURS = 6            # a bet's status with new material rewrites itself when opened, at most this often (front end)
# A topic (the Top of mind run) and a meeting brief are written from everything SleePO held at the time, so an item SleePO
# already had then is not new to them, even when it touches them only later (a run citing a thread makes the thread's older
# messages touch the topic). A bet's status reads only the material linked to it, so for a bet a touch after the status is new.
READ_ALL = ("topic", "event")
# When SleePO first held an item: its first walk for any record, or when it was stored if earlier (a sync stores mail before it
# links it; pulled_at alone is no guide, a later pull moves it). SQL over "graph_touches t JOIN items i".
ARRIVED = ("MIN(COALESCE(i.pulled_at, '9999'), COALESCE((SELECT MIN(g.seen_at) FROM graph_touches g WHERE g.item_id=t.item_id), '9999'))")


def is_new(etype, seen_at, arrived, rec):
    """Whether a touch (seen at `seen_at`, its item first held at `arrived`) is new for a record written at `rec`."""
    if rec and (seen_at or "") <= rec:
        return False
    return etype not in READ_ALL or not rec or (arrived or seen_at or "") > rec


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS graph_touches (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id     INTEGER NOT NULL,              -- the new item (items.id)
      entity_type TEXT NOT NULL,                 -- initiative | topic | task | event | person | org | doc
      entity_id   INTEGER NOT NULL,              -- event: the calendar entry's items.id
      hop         INTEGER NOT NULL,              -- 1: the item links to it; 2: through via
      via_type    TEXT, via_id INTEGER,          -- hop 2: the task, topic or person it came through
      reason      TEXT,                          -- the link's role, "same thread", "task's bet", "attends"
      item_ts     TEXT,                          -- when the item was said or sent
      seen_at     TEXT NOT NULL,                 -- when this walk saw it: compared with the record's own time
      UNIQUE(item_id, entity_type, entity_id))""")
    con.execute("CREATE INDEX IF NOT EXISTS graph_touches_node ON graph_touches(entity_type, entity_id, seen_at)")


# ---------------------------------------------------------------- the walk
def _sure(etype, conf, verdict):
    if verdict == "rejected":
        return False
    return verdict == "confirmed" or (conf or 0) >= SURE.get(etype, SHOWN)


def _personal_notes(con, ids):
    """Meeting notes of the user's personal meetings: out of scope everywhere."""
    from . import profile
    out = set()
    if not ids or not db.has_table(con, "meetings"):
        return out
    q = ",".join("?" * len(ids))
    for r in con.execute(f"SELECT m.note_item_id, m.status, COALESCE(m.title, i.subject, '') AS title FROM meetings m "
                         f"JOIN items i ON i.id=m.note_item_id WHERE m.note_item_id IN ({q})", list(ids)):
        if r["status"] == "personal" or profile.PERSONAL.search(r["title"] or ""):
            out.add(r["note_item_id"])
    return out


def _threads(con, item_ids):
    """Each item's thread keys: a mail's conversation id and subject key, a chat's conversation."""
    from .threads import key as thread_key
    out = defaultdict(set)
    if not item_ids:
        return out
    q = ",".join("?" * len(item_ids))
    ids = list(item_ids)
    for r in con.execute(f"SELECT item_id, conversation_id, subject FROM mail_messages WHERE item_id IN ({q})", ids):
        if r["conversation_id"]:
            out[r["item_id"]].add("m:" + r["conversation_id"])
        k = thread_key(r["subject"])
        if k and len(k) >= 8:   # "re: hi" is no thread
            out[r["item_id"]].add("s:" + k)
    if db.has_table(con, "chat_messages"):
        for r in con.execute(f"SELECT item_id, COALESCE(conversation_id, conversation_name) AS conv FROM chat_messages WHERE item_id IN ({q})", ids):
            if r["conv"]:
                out[r["item_id"]].add("c:" + r["conv"])
    return out


def _topic_threads(con):
    """Current topics: {thread key: {topic id}} from the mail and chat sources each one cites, and each topic's bet."""
    if not db.has_table(con, "topics"):
        return {}, {}
    from . import topics
    cited, bet = defaultdict(set), {}
    for r in con.execute(f"SELECT id, initiative_id, sources_json FROM topics WHERE {topics._latest(con)}"):
        bet[r["id"]] = r["initiative_id"]
        try:
            srcs = json.loads(r["sources_json"] or "[]")
        except ValueError:
            srcs = []
        ids = {s.get("id") for s in srcs if s.get("kind") in ("mail", "chat") and isinstance(s.get("id"), int)}
        for keys in _threads(con, ids).values():
            for k in keys:
                cited[k].add(r["id"])
    return cited, bet


def _attending(con):
    """{person id: [calendar entry items.id]} for the meetings worth a brief until the end of the next working day."""
    from . import prep
    out = defaultdict(list)
    try:
        events = prep.upcoming(con, BRIEF_DAYS)
    except Exception:
        return out
    for e in events:
        pids = {db.resolve_person(con, a) for a in e.get("attendee_addresses") or []}
        pids |= {r["entity_id"] for r in con.execute("SELECT entity_id, confidence, verdict FROM mentions WHERE ref_type='item' AND ref_id=? "
                                                     "AND entity_type='person'", (e["item_id"],)) if _sure("person", r["confidence"], r["verdict"])}
        for pid in pids - {None}:
            out[pid].append(e["item_id"])
    return out


def touches_for(con, now=None):
    """What each item of the window touches: [(item_id, entity_type, entity_id, hop, via_type, via_id, reason, item_ts)].
    Reads only."""
    now = now or datetime.now(timezone.utc)
    rows = con.execute(f"SELECT id, kind, ts FROM items WHERE noise=0 AND kind IN ({','.join('?' * len(KINDS))}) AND ts >= ? AND ts <= ?",
                       [*KINDS, _iso(now - timedelta(days=WINDOW_DAYS)), _iso(now + timedelta(hours=1))]).fetchall()
    skip = _personal_notes(con, [r["id"] for r in rows if r["kind"] == "note"])
    items = {r["id"]: r["ts"] for r in rows if r["id"] not in skip}
    if not items:
        return []
    ids = list(items)
    me = {r["id"] for r in con.execute("SELECT id FROM people WHERE COALESCE(is_me, 0)=1")}
    ours = {r["id"] for r in con.execute("SELECT id FROM orgs WHERE kind='internal'")}
    live = {r["id"]: r["initiative_id"] for r in con.execute(f"SELECT id, initiative_id FROM tasks WHERE status IN ({','.join('?' * len(TASK_LIVE))})",
                                                             TASK_LIVE)} if db.has_table(con, "tasks") else {}
    ini_cols = {r[1] for r in con.execute("PRAGMA table_info(initiatives)")}
    active = {r["id"] for r in con.execute("SELECT id FROM initiatives" + (" WHERE COALESCE(active, 1)=1" if "active" in ini_cols else ""))}

    hop1 = defaultdict(list)   # item -> [(etype, eid, conf, reason)]
    q = ",".join("?" * len(ids))
    for r in con.execute(f"SELECT ref_id, entity_type, entity_id, confidence, verdict, role FROM mentions WHERE ref_type='item' AND ref_id IN ({q}) "
                         f"AND entity_type IN ({','.join('?' * len(HOP1))})", [*ids, *HOP1]):
        t, e = r["entity_type"], r["entity_id"]
        if not _sure(t, r["confidence"], r["verdict"]):
            continue
        if (t == "person" and e in me) or (t == "org" and e in ours) or (t == "task" and e not in live) or (t == "initiative" and e not in active):
            continue
        hop1[r["ref_id"]].append((t, e, r["confidence"] or 0, r["role"] or "linked"))
    cited, topic_bet = _topic_threads(con)
    if cited:
        for iid, keys in _threads(con, ids).items():
            for tid in sorted({t for k in keys for t in cited.get(k, ())}):
                hop1[iid].append(("topic", tid, 0.9, "same thread"))
    attends = _attending(con) if any(t == "person" for v in hop1.values() for t, *_ in v) else {}

    out = []
    for iid, links in hop1.items():
        got, n = set(), defaultdict(int)
        for t, e, _c, why in sorted(links, key=lambda x: -x[2]):
            if (t, e) in got or n[t] >= CAP[t]:
                continue
            got.add((t, e)); n[t] += 1
            out.append((iid, t, e, 1, None, None, why, items[iid]))
        second = []
        for t, e in list(got):
            if t == "task" and live.get(e) in active:
                second.append(("initiative", live[e], "task", e, "task's bet"))
            elif t == "topic" and topic_bet.get(e) in active:
                second.append(("initiative", topic_bet[e], "topic", e, "topic's bet"))
            elif t == "person":
                second += [("event", ev, "person", e, "attends") for ev in attends.get(e, ())]
        for t, e, vt, vi, why in second:
            if (t, e) in got or n[t] >= CAP[t]:
                continue
            got.add((t, e)); n[t] += 1
            out.append((iid, t, e, 2, vt, vi, why, items[iid]))
    return out


def propagate(con, now=None):
    """Mark what the window's items touch. Writes only rows not there yet (and purges past retention), so a pass with nothing
    new writes nothing. The first pass ever dates its rows by the items' own times, so old records do not all look stale."""
    if not db.has_table(con, "graph_touches"):
        ensure_schema(con)
    now = now or datetime.now(timezone.utc)
    found = touches_for(con, now)
    first = con.execute("SELECT 1 FROM graph_touches LIMIT 1").fetchone() is None
    have = set()
    if found:
        ids = sorted({t[0] for t in found})
        have = {(r[0], r[1], r[2]) for r in con.execute(f"SELECT item_id, entity_type, entity_id FROM graph_touches WHERE item_id IN ({','.join('?' * len(ids))})", ids)}
    new = [t for t in found if (t[0], t[1], t[2]) not in have]
    seen = _iso(now)
    for t in new:
        con.execute("INSERT OR IGNORE INTO graph_touches (item_id, entity_type, entity_id, hop, via_type, via_id, reason, item_ts, seen_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (*t, min(t[7] or seen, seen) if first else seen))
    cut = _iso(now - timedelta(days=RETENTION_DAYS))
    purged = 0
    if con.execute("SELECT 1 FROM graph_touches WHERE seen_at < ? LIMIT 1", (cut,)).fetchone():
        purged = con.execute("DELETE FROM graph_touches WHERE seen_at < ?", (cut,)).rowcount
    by = defaultdict(int)
    for t in new:
        by[f"{t[1]}:{t[3]}"] += 1
    return {"items": len({t[0] for t in new}), "touches": len(new), "by": dict(by), "purged": purged}


# ---------------------------------------------------------------- reading
def _briefs(con):
    try:
        from . import prep
        return prep._briefs(con)
    except Exception:
        return {}


def _event_key(con, item_id):
    r = con.execute("SELECT external_id, payload FROM items WHERE id=?", (item_id,)).fetchone()
    if not r:
        return None
    try:
        return json.loads(r["payload"] or "{}").get("id") or r["external_id"]
    except ValueError:
        return r["external_id"]


def record_time(con, etype, eid, briefs=None):
    """When the record was last written, or None when the kind holds no record (yet) or this one has none."""
    if etype == "initiative" and db.has_table(con, "initiative_updates"):
        r = con.execute("SELECT MAX(COALESCE(approved_at, drafted_at)) FROM initiative_updates WHERE initiative_id=? AND COALESCE(discarded, 0)=0",
                        (eid,)).fetchone()
        return r[0] if r else None
    if etype == "topic" and db.has_table(con, "topics"):
        r = con.execute("SELECT updated_at FROM topics WHERE id=?", (eid,)).fetchone()
        return r[0] if r else None
    if etype == "task" and db.has_table(con, "tasks"):
        r = con.execute("SELECT updated_at FROM tasks WHERE id=?", (eid,)).fetchone()
        return r[0] if r else None
    if etype == "event":
        b = (briefs if briefs is not None else _briefs(con)).get(_event_key(con, eid))
        return (b or {}).get("updated_at") or None
    return None


def _label(con, row):
    from .entities import KIND_LABEL, item_link
    it = dict(row)
    if it["kind"] == "note":
        m = con.execute("SELECT id FROM meetings WHERE note_item_id=?", (it["id"],)).fetchone() if db.has_table(con, "meetings") else None
        it["meeting_id"] = m["id"] if m else None
    title = (it.get("subject") or "").strip() or " ".join((it.get("text") or "").split())[:90]
    return {"kind": it["kind"], "label": KIND_LABEL.get(it["kind"], it["kind"]), "who": it.get("from_name") or "", "title": title,
            "ts": it.get("ts"), "app": item_link(it)}


def _via(con, vt, vi):
    if vt == "task":
        r = con.execute("SELECT title FROM tasks WHERE id=?", (vi,)).fetchone()
        return f"through the task “{r['title']}”" if r else "through a task"
    if vt == "topic":
        r = con.execute("SELECT title FROM topics WHERE id=?", (vi,)).fetchone()
        return f"through the topic “{r['title']}”" if r else "through a topic"
    if vt == "person":
        r = con.execute("SELECT name FROM people WHERE id=?", (vi,)).fetchone()
        return f"{r['name']} is in this meeting" if r else "someone in this meeting"
    return ""


def since_record(con, etype, eid, limit=12, now=None):
    """What came in since the record was written: the items, newest first, each with who, what and a link. Reads only.
    A hop-1 link Sam has since rejected, or an item marked noise since, no longer counts. Phase 2 (assist/graph_refresh.py)
    adds how many of them SleePO has not read yet (`unreviewed`), its latest review of the record (`review`: what changed and
    from which item, or that nothing did) and whether a refresh is running now (`refreshing`)."""
    from . import graph_refresh, jobs
    now = now or datetime.now(timezone.utc)
    rec = record_time(con, etype, eid)
    out = {"kind": etype, "id": eid, "record_at": rec, "count": 0, "hops": {"1": 0, "2": 0}, "items": [], "unreviewed": 0,
           "review": graph_refresh.last_review(con, etype, eid) if etype in graph_refresh.KINDS else None,
           "refreshing": jobs.held(graph_refresh.LOCK) if etype in graph_refresh.KINDS else False}
    if not db.has_table(con, "graph_touches"):
        return out
    floor = rec or _iso(now - timedelta(days=WINDOW_DAYS))
    read = graph_refresh.read_items(con, etype, eid)
    rows = con.execute(f"SELECT t.hop, t.via_type, t.via_id, t.reason, t.seen_at, {ARRIVED} AS arrived, i.id, i.kind, i.ts, i.from_name, i.subject, i.text, i.url "
                       "FROM graph_touches t JOIN items i ON i.id=t.item_id "
                       "LEFT JOIN mentions m ON t.hop=1 AND m.ref_type='item' AND m.ref_id=t.item_id AND m.entity_type=t.entity_type AND m.entity_id=t.entity_id "
                       "WHERE t.entity_type=? AND t.entity_id=? AND t.seen_at > ? AND i.noise=0 AND COALESCE(m.verdict, '')<>'rejected' "
                       "ORDER BY i.ts DESC", (etype, eid, floor)).fetchall()
    rows = [r for r in rows if is_new(etype, r["seen_at"], r["arrived"], rec)]
    out["count"] = len(rows)
    out["unreviewed"] = sum(1 for r in rows if r["id"] not in read)
    for r in rows:
        out["hops"][str(r["hop"])] += 1
    for r in rows[:limit]:
        x = _label(con, r)
        x.update({"item_id": r["id"], "hop": r["hop"], "via": _via(con, r["via_type"], r["via_id"]) if r["hop"] == 2 else ""})
        out["items"].append(x)
    return out


def stale(con):
    """Records with new material since they were written, by kind: {kind: {"stale": n, "of": m}}. Reads only."""
    out = {}
    if not db.has_table(con, "graph_touches"):
        return out
    briefs = _briefs(con)
    touches = defaultdict(lambda: defaultdict(list))
    for r in con.execute(f"SELECT t.entity_type, t.entity_id, t.seen_at, {ARRIVED} AS arrived FROM graph_touches t JOIN items i ON i.id=t.item_id "
                         f"WHERE i.noise=0 AND t.entity_type IN ({','.join('?' * len(RECORDS))})", RECORDS):
        touches[r["entity_type"]][r["entity_id"]].append((r["seen_at"], r["arrived"]))
    from . import topics
    # the records that exist now: an active bet, a current topic (a later Top of mind run replaces topics, their touches stay), a live task
    live = {"initiative": "SELECT id FROM initiatives" + (" WHERE COALESCE(active, 1)=1" if "active" in {c[1] for c in con.execute("PRAGMA table_info(initiatives)")} else ""),
            "topic": f"SELECT id FROM topics WHERE {topics._latest(con)}" if db.has_table(con, "topics") else None,
            "task": f"SELECT id FROM tasks WHERE status IN ({','.join(repr(s) for s in TASK_LIVE)})" if db.has_table(con, "tasks") else None}
    try:   # briefs: the meetings still ahead that get one
        from . import prep
        upcoming = {e["item_id"] for e in prep.upcoming(con, BRIEF_DAYS)}
    except Exception:
        upcoming = None
    for kind in RECORDS:
        q = live.get(kind)
        ids = {r[0] for r in con.execute(q)} if q else (upcoming if kind == "event" else None)
        n = 0
        for eid, ts in touches.get(kind, {}).items():
            if ids is not None and eid not in ids:
                continue
            rec = record_time(con, kind, eid, briefs)
            n += any(is_new(kind, seen, first, rec) for seen, first in ts)
        out[kind] = {"stale": n, "of": len(ids) if ids is not None else None}
    return out


def report(con, days=7, now=None):
    """The churn: per day (UTC, by when the walk saw them), items walked, touches by kind and hop, distinct records;
    and the records with new material now."""
    now = now or datetime.now(timezone.utc)
    rows = con.execute("SELECT substr(seen_at, 1, 10) AS d, entity_type, hop, COUNT(*) AS n, COUNT(DISTINCT entity_id) AS nodes, COUNT(DISTINCT item_id) AS items "
                       "FROM graph_touches WHERE seen_at >= ? GROUP BY 1, 2, 3 ORDER BY 1", (_iso(now - timedelta(days=days)),)).fetchall() \
        if db.has_table(con, "graph_touches") else []
    per = defaultdict(lambda: {"items": 0, "touches": {}, "records": {}})
    for r in rows:
        d = per[r["d"]]
        d["touches"][f"{r['entity_type']}:{r['hop']}"] = r["n"]
        d["records"][r["entity_type"]] = d["records"].get(r["entity_type"], 0) + r["nodes"]
    if rows:
        for r in con.execute("SELECT substr(seen_at, 1, 10) AS d, COUNT(DISTINCT item_id) FROM graph_touches WHERE seen_at >= ? GROUP BY 1",
                             (_iso(now - timedelta(days=days)),)):
            per[r[0]]["items"] = r[1]
    return {"days": dict(per), "stale": stale(con)}


def report_text(con, days=7):
    r = report(con, days)
    lines = ["Graph memory: what new items touched (DESIGN-GRAPH-MEMORY.md)"]
    for d, x in sorted(r["days"].items()):
        recs = ", ".join(f"{k} {v}" for k, v in sorted(x["records"].items()))
        lines.append(f"  {d}: {x['items']} items · records touched: {recs}")
    if len(lines) == 1:
        lines.append("  nothing walked yet")
    lines.append("Records with new material since they were written:")
    names = {"initiative": "bets", "topic": "topics", "task": "tasks", "event": "meeting briefs"}
    for k, v in r["stale"].items():
        lines.append(f"  {names[k]}: {v['stale']}" + (f" of {v['of']}" if v["of"] is not None else ""))
    lines += refresh_text(con, days)
    return "\n".join(lines)


def refresh_text(con, days=7):
    """Phase 2 (assist/graph_refresh.py): what the refresh read and changed per day, the last run, and today's spend."""
    from . import graph_refresh
    lines = ["Refresh (phase 2): records read, and what changed"]
    if db.has_table(con, "graph_changes"):
        since = _iso(datetime.now(timezone.utc) - timedelta(days=days))
        per = defaultdict(lambda: defaultdict(int))
        for r in con.execute("SELECT substr(reviewed_at, 1, 10) AS d, entity_type, verdict, COALESCE(applied, '') AS applied, COUNT(*) AS n "
                             "FROM graph_changes WHERE reviewed_at >= ? GROUP BY 1, 2, 3, 4", (since,)):
            d = per[r["d"]]
            d["read"] += r["n"]
            if r["verdict"] == "changed":
                d["changed"] += r["n"]
            if r["applied"]:
                d[r["applied"]] += r["n"]
        for d, x in sorted(per.items()):
            lines.append(f"  {d}: {x['read']} read · {x['changed']} changed · rewritten: {x['status']} bet statuses, {x['topic']} topics, {x['brief']} briefs"
                         + (f" · {x['superseded']} written meanwhile" if x["superseded"] else ""))
    if len(lines) == 1:
        lines.append("  no review yet")
    st = graph_refresh.state()
    if st.get("finished"):
        lines.append(f"  last run {st['finished']}: {st.get('reviewed', 0)} of {st.get('records', 0)} read, {st.get('changed', 0)} changed, ${st.get('cost') or 0:.2f}"
                     + (f", stopped: {st['stopped']}" if st.get("stopped") else "") + (f", error: {st['error']}" if st.get("error") else ""))
    lines.append(f"  spent in the last 24 h: ${graph_refresh.spent(con):.2f} of ${graph_refresh.ceiling(con):.2f}"
                 + ("" if graph_refresh.enabled(con) else " (switched off: settings graph_refresh)"))
    return lines
