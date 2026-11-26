"""Graph view model: people in the middle, everything else around the people it involves.

People are the main entities of the ontology (DESIGN.md §3.1): a bet, a task, a topic, a company, a meeting or a document
is reached through the people in it. So every edge has a person at one end, except the ties between two things (a thing →
the bet or area it is filed under, a topic → the meetings it came up in, a topic or task → the companies on its sources,
a meeting → the companies in it), which the view draws only when one of their ends is selected.
It follows how SleePO is organised since 29 Oct 2026: work is initiative (bet) or day-to-day area → task → step, so
the tasks Sam works from replace the open-items register (which still feeds Tasks but is no longer a list he reads);
companies are the Companies page's (assist/companies.py: merged records, what each is to Acme, its logo); what is top
of mind is the Initiatives page's topics (assist/topics.py); decisions were retired on 26 Oct.

Built from the links assist/entities.py makes, with the person page's rules (assist/person_page.py): a link counts when
Sam ticked it, or it is unreviewed with confidence >= 0.6, never when crossed; "involved" means taking part (from, to,
speaker, attendee, owner...), not being named.
- Sam is the centre node (`me`). His ties are not edges (nearly everything connects to him, so they would hide the
  structure); instead each person's `contact` (days in touch with Sam in the last 90) sets how close to him they sit.
- person → person: reports to (org chart); works with (the same meetings, emails and chats in 90 days, small groups only).
- person → org: works at (outside people; Acme itself is never a node).
- person → bet: drives (the bet's key people); works on (5+ of their items tagged to the bet in 90 days).
- person → meeting: attended (meeting_people: Sam's tick, or a suggestion at 0.8+).
- person → company: works at (outside people); deals with (the Acme people on 2+ of its mail, chats and meetings in
  90 days, the 4 most involved). Partners, customers, prospects and investors are shown; a company someone works at always.
  Acme itself is never a node.
- person → topic: raised (who brought it up first), discussed (the others in it).
- person → task: owes (the task or one of its steps is with them: Sam waits on them), named in (people linked to it).
  Open and snoozed tasks, and suggestions of the last SUGGESTED_DAYS still waiting on Sam. A task that names no one but
  Sam takes the people on its sources: involved (the email, chat or meeting it came from; broadcasts of more than
  EVIDENCE_MAX people left out).
- person → document: owns, shared (the document's owner and sharer links).
Things no person links to are left out and counted in `unlinked`: they are gaps in the people links, not noise.
Personal meetings are skipped.
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import companies as _companies, db
from . import org
from . import profile
from .person_page import CONTACT_KINDS, DOC_PREFIX, INVOLVED, NOT_A_DOC, _in, _shown

SMALL_GROUP = 8                     # an item with more people than this is a broadcast: it says nothing about who works with whom
WORKS_WITH_MIN, WORKS_WITH_TOP = 3, 5
WORKS_ON_MIN = 5
EVIDENCE_MAX = 10                   # a source with more people than this does not say who a claim is about
COMPANY_MIN, COMPANY_TOP = 2, 4      # an Acme person deals with a company: on 2+ of its items in 90 days; its 4 most involved
COMPANY_RELATIONS = ("partner", "customer", "prospect", "investor")
RELATION = {"partner": "Partner", "customer": "Customer", "prospect": "Prospect", "investor": "Investor", "vendor": "Vendor", "other": "Company"}
COMPANY_BETS = 2                     # the bets a company's items are most often tagged to (2+ items in 90 days)
SUGGESTED_DAYS = 14                  # suggested tasks still waiting on Sam (tasks.py expires them at 30)
TASK_STATUS = {"open": "Open", "snoozed": "Snoozed", "suggested": "Suggested"}
APP_MEETING = re.compile(r"#/meetings/(m-\d+)")


def _norm(s):
    return re.sub(r"[^a-z]+", " ", (s or "").lower()).strip()

# naming a company in a topic or task: its name without the legal form, a distinctive word of it, or its initials ("NWT").
# Not the company links on the sources: one customer named in a recurring meeting is on nearly every topic's sources.
LEGAL = re.compile(r"\b(the|ltd|limited|inc|corp|corporation|co|company|llc|plc|gmbh|ag|sa|se|nv|bv|kg|b s c)\b", re.I)
GENERIC = {"data", "world", "bank", "technology", "technologies", "group", "partners", "partner", "solutions", "systems", "planning",
           "financial", "services", "international", "global", "digital", "software", "consulting", "holding", "holdings", "network",
           "energy", "health", "credit", "union", "federal", "first", "national", "american", "management", "business", "school",
           "medical", "brands", "market", "corporate", "ntt", "with", "werk", "middle", "east"}


def _namer(name):
    """A test for whether a text names this company."""
    core = " ".join(LEGAL.sub(" ", re.sub(r"[,.()]", " ", name)).split())
    words = core.split()
    alts = [re.escape(core)] if len(core) >= 4 else []
    alts += [re.escape(w) for w in words if w.lower() not in GENERIC and (len(w) >= 4 or (len(w) == 3 and w.isupper()))]
    wide = re.compile(r"(?<![\w-])(" + "|".join(alts) + r")(?![\w-])", re.I) if alts else None
    initials = "".join(w[0] for w in words if len(w) > 1 and w[0].isalpha()).upper()
    exact = re.compile(r"(?<![\w-])" + initials + r"(?![\w-])") if len(words) >= 3 and len(initials) >= 3 else None
    return lambda text: bool((wide and wide.search(text)) or (exact and exact.search(text)))


def _day(s):
    try:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
        return f"{d.day} {d:%b}"
    except (TypeError, ValueError):
        return s or ""


def build(d, con=None):
    own = con is None
    con = con or db.connect()
    try:
        return _build(d, con)
    finally:
        if own:
            con.close()


def _build(d, con):
    now = datetime.now(timezone.utc)
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    since90, now_s = iso(now - timedelta(days=90)), iso(now)
    nodes, edges, touched, into = {}, {}, set(), {}

    def node(nid, typ, label, sub="", href="", **kw):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": typ, "label": label, "sub": sub, "href": href, "weight": None, "avatar": "", **kw}
        return nid

    def edge(a, b, rel, w=1):
        if a and b and a != b and a in nodes and b in nodes and (b, a, rel) not in edges:
            edges[(a, b, rel)] = max(edges.get((a, b, rel), 0), w)
            touched.update((a, b))
            into.setdefault(b, set()).add(a)

    # ---- people: the centre of the picture
    me = next((p for p in d["people"] if p["status"] == "me"), None)
    me_id = me["id"] if me else None
    contact = {f"p-{r[0]}": r[1] for r in con.execute(
        f"SELECT m.entity_id, COUNT(DISTINCT substr(i.ts, 1, 10)) FROM mentions m JOIN items i ON i.id=m.ref_id "
        f"WHERE m.ref_type='item' AND m.entity_type='person' AND i.noise=0 AND i.kind IN ({_in(CONTACT_KINDS)}) "
        f"AND m.role IN ({_in(INVOLVED)}) AND {_shown('m')} AND i.ts >= ? AND i.ts <= ? GROUP BY 1",
        (*CONTACT_KINDS, *INVOLVED, since90, now_s))}
    pid_of = {}   # lower-case name, alias or normalised name → node id
    for p in d["people"]:
        if p["affiliation"] == "former employee":
            continue
        if p is me:
            node(p["id"], "person", p["name"], "You", "/me", avatar=p["avatar"], me=True)
            continue
        ext = p["affiliation"] not in ("employee", "unclassified")
        node(p["id"], "partner" if ext else "person", p["name"], p["title"] or (p["org"] if ext else "") or p["affiliation"], f"/people/{p['id']}",
             avatar=p["avatar"], contact=contact.get(p["id"], 0), group=(p["org"] if ext else p["department"]) or "")
        pid_of[p["name"].lower()] = pid_of[_norm(p["name"])] = p["id"]
    for alias, pid in con.execute("SELECT alias, person_id FROM people_aliases"):
        if f"p-{pid}" in nodes:
            pid_of.setdefault(alias.lower(), f"p-{pid}")
    firsts = {}
    for k, v in list(pid_of.items()):
        if " " in k:
            firsts.setdefault(k.split()[0], set()).add(v)

    def person(name):
        n = (name or "").strip().lower()
        if not n:
            return None
        if n == "me" or profile.is_me(n):
            return me_id
        hit = pid_of.get(n) or pid_of.get(_norm(n))
        if hit:
            return hit
        f = firsts.get(n.split()[0], set())
        return next(iter(f)) if len(f) == 1 else None

    def pnode(person_id):
        nid = f"p-{person_id}"
        return nid if nid in nodes else None

    # person → person: the org chart, and who works together (Sam left out: he is on everything)
    for r in con.execute("SELECT id, manager_id FROM people WHERE manager_id IS NOT NULL"):
        edge(pnode(r["id"]), pnode(r["manager_id"]), "reports to")
    me_num = int(me_id[2:]) if me_id else -1
    pairs = list(con.execute(
        f"WITH inv AS (SELECT DISTINCT m.ref_id AS item, m.entity_id AS pid FROM mentions m JOIN items i ON i.id=m.ref_id "
        f"  WHERE m.ref_type='item' AND m.entity_type='person' AND m.entity_id != ? AND i.noise=0 AND i.kind IN ({_in(CONTACT_KINDS)}) "
        f"  AND m.role IN ({_in(INVOLVED)}) AND {_shown('m')} AND i.ts >= ? AND i.ts <= ?), "
        f"small AS (SELECT item FROM inv GROUP BY item HAVING COUNT(*) BETWEEN 2 AND ?) "
        f"SELECT a.pid AS a, b.pid AS b, COUNT(*) AS n FROM inv a JOIN inv b ON a.item=b.item AND a.pid < b.pid "
        f"WHERE a.item IN (SELECT item FROM small) GROUP BY 1, 2 HAVING n >= ?",
        (me_num, *CONTACT_KINDS, *INVOLVED, since90, now_s, SMALL_GROUP, WORKS_WITH_MIN)))
    top = {}
    for r in sorted(pairs, key=lambda r: -r["n"]):
        for x in (r["a"], r["b"]):
            top.setdefault(x, []).append(r)
    keep = {(r["a"], r["b"]) for rs in top.values() for r in rs[:WORKS_WITH_TOP]}
    for r in pairs:
        if (r["a"], r["b"]) in keep:
            edge(pnode(r["a"]), pnode(r["b"]), "works with", r["n"])

    # ---- companies (assist/companies.py): one node per company however many records it has, with what it is to Acme
    orgs = _companies._orgs(con)
    listed = {x["id"]: x for x in _companies.listing(con)}

    def company(oid):
        rid = _companies.root(orgs, oid)
        x, o = listed.get(rid), orgs.get(rid)
        if not o or o.get("relation") == "hidden" or (x or {}).get("relation") == "ours" or o.get("kind") == "internal" or org.is_own_company(o["name"]):
            return None
        rel = x["relation"] if x else (o.get("relation") or o.get("kind") or "other")
        deals = x["deals_open"] if x else 0
        return node(f"o-{rid}", "org", o["name"], RELATION.get(rel, "Company") + (f" · {deals} open deal{'s' if deals != 1 else ''}" if deals else ""),
                    f"/companies/{rid}", relation=rel, logo=f"/api/companies/{rid}/logo?v={x['logo']}" if x and x.get("logo") else "",
                    deals=deals, open_usd=x["open_usd"] if x else 0)

    # outside people and the company they work for
    for r in con.execute("SELECT id, org_id FROM people WHERE org_id IS NOT NULL AND is_me=0 "
                         "AND COALESCE(affiliation, '') NOT IN ('employee', 'unclassified', 'former employee')"):
        if pnode(r["id"]):
            edge(pnode(r["id"]), company(r["org_id"]), "works at")

    # ---- bets: through the people who drive them and the people whose work is tagged to them
    ini_id, ini_slug = {}, {}
    for r in con.execute("SELECT id, slug, name, weight, status, key_people FROM initiatives WHERE COALESCE(active, 1)=1 AND merged_into IS NULL"):
        iid = node(f"i-{r['id']}", "initiative", r["name"], r["status"] or "", f"/initiatives/{r['slug']}", weight=r["weight"])
        ini_id[r["id"]] = ini_id[r["name"]] = iid
        ini_slug[r["id"]] = r["slug"]
        for name in json.loads(r["key_people"] or "[]"):
            edge(person(name), iid, "drives")
    for r in con.execute(
            f"SELECT mp.entity_id AS pid, mi.entity_id AS iid, COUNT(DISTINCT mp.ref_id) AS n FROM mentions mp JOIN items i ON i.id=mp.ref_id "
            f"JOIN mentions mi ON mi.ref_type='item' AND mi.ref_id=mp.ref_id AND mi.entity_type='initiative' "
            f"WHERE mp.ref_type='item' AND mp.entity_type='person' AND mp.entity_id != ? AND mp.role IN ({_in(INVOLVED)}) "
            f"AND {_shown('mp')} AND {_shown('mi')} AND i.ts >= ? AND i.noise=0 GROUP BY 1, 2 HAVING n >= ?",
            (me_num, *INVOLVED, since90, WORKS_ON_MIN)):
        p, i = pnode(r["pid"]), ini_id.get(r["iid"])
        if p and i and (p, i, "drives") not in edges:
            edge(p, i, "works on", r["n"])

    unlinked = {}

    # the Acme people who deal with each partner, customer, prospect or investor: on its mail, chats and meetings in 90 days
    # (broadcasts left out); a company only Sam deals with is a gap like any other
    staff = {nid for nid, n in nodes.items() if n["type"] == "person" and not n.get("me")}
    on, seen_items = defaultdict(lambda: defaultdict(int)), defaultdict(set)
    for r in con.execute(
            f"WITH ev AS (SELECT DISTINCT m.ref_id AS item, m.entity_id AS oid FROM mentions m JOIN items i ON i.id=m.ref_id "
            f"  WHERE m.ref_type='item' AND m.entity_type='org' AND {_shown('m')} AND i.noise=0 AND i.kind IN ({_in(CONTACT_KINDS)}) AND i.ts >= ? AND i.ts <= ?), "
            f"inv AS (SELECT DISTINCT m.ref_id AS item, m.entity_id AS pid FROM mentions m WHERE m.ref_type='item' AND m.entity_type='person' "
            f"  AND m.role IN ({_in(INVOLVED)}) AND {_shown('m')} AND m.ref_id IN (SELECT item FROM ev)), "
            f"small AS (SELECT item FROM inv GROUP BY item HAVING COUNT(*) <= ?) "
            f"SELECT ev.oid, ev.item, inv.pid FROM ev LEFT JOIN inv ON inv.item=ev.item AND inv.item IN (SELECT item FROM small)",
            (*CONTACT_KINDS, since90, now_s, *INVOLVED, EVIDENCE_MAX)):
        rid = _companies.root(orgs, r["oid"])
        seen_items[rid].add(r["item"])
        if r["pid"] is not None and f"p-{r['pid']}" in staff:
            on[rid][r["pid"]] += 1
    for rid, items in seen_items.items():
        ppl, x = on[rid], listed.get(rid)
        if not x or x["relation"] not in COMPANY_RELATIONS:
            continue
        top = [(pid, n) for pid, n in sorted(ppl.items(), key=lambda kv: -kv[1]) if n >= COMPANY_MIN][:COMPANY_TOP]
        if top:
            cid = company(rid)
            for pid, n in top:
                edge(pnode(pid), cid, "deals with", n)
        elif len(items) >= COMPANY_MIN and f"o-{rid}" not in nodes:
            unlinked["org"] = unlinked.get("org", 0) + 1
    if any(n["type"] == "org" for n in nodes.values()):
        best = defaultdict(int)
        for r in con.execute(
                f"SELECT mo.entity_id AS oid, mi.entity_id AS iid, COUNT(DISTINCT mo.ref_id) AS n FROM mentions mo JOIN items i ON i.id=mo.ref_id "
                f"JOIN mentions mi ON mi.ref_type='item' AND mi.ref_id=mo.ref_id AND mi.entity_type='initiative' "
                f"WHERE mo.ref_type='item' AND mo.entity_type='org' AND {_shown('mo')} AND {_shown('mi')} AND i.noise=0 AND i.ts >= ? GROUP BY 1, 2",
                (since90,)):
            best[(_companies.root(orgs, r["oid"]), r["iid"])] += r["n"]
        per = defaultdict(list)
        for (rid, iid), n in best.items():
            if n >= 2 and f"o-{rid}" in nodes and ini_id.get(iid):
                per[rid].append((n, iid))
        for rid, xs in per.items():
            for n, iid in sorted(xs, reverse=True)[:COMPANY_BETS]:
                edge(f"o-{rid}", ini_id[iid], "about", n)

    def linked(nid, typ):
        """Keep a thing only if a person is on it; otherwise count it as a gap."""
        if nid in touched:
            return True
        nodes.pop(nid, None)
        unlinked[typ] = unlinked.get(typ, 0) + 1
        return False

    def about(nid, iids):
        for i in iids:
            if i:
                edge(nid, i, "about")

    # the people taking part (not named) in a piece of evidence, for things that name no one but Sam
    on_item = {}

    def people_on(items):
        need = [i for i in set(items) if i not in on_item]
        for i in need:
            on_item[i] = set()
        if need:
            for r in con.execute(f"SELECT m.ref_id, m.entity_id FROM mentions m JOIN items i ON i.id=m.ref_id WHERE m.ref_type='item' AND m.entity_type='person' "
                                 f"AND m.entity_id != ? AND m.role IN ({_in(INVOLVED)}) AND {_shown('m')} AND i.noise=0 AND m.ref_id IN ({_in(need)})",
                                 (me_num, *INVOLVED, *need)):
                on_item[r["ref_id"]].add(r["entity_id"])
        return on_item

    def evidence(nid, items):
        if into.get(nid, set()) - {me_id}:
            return
        got = people_on(items)
        for item in items:
            ppl = got.get(item, set())
            if len(ppl) <= EVIDENCE_MAX:
                for pid in ppl:
                    edge(pnode(pid), nid, "involved")

    namers = {}

    def companies_named(nid, text):
        """A topic or task → the companies on the graph that its own words name."""
        for cid, n in list(nodes.items()):
            if n["type"] == "org":
                if cid not in namers:
                    namers[cid] = _namer(n["label"])
                if namers[cid](text):
                    edge(nid, cid, "involves")

    # ---- meetings: the people in the room
    attendees = {}
    for r in con.execute("SELECT meeting_id, person_id FROM meeting_people WHERE person_id IS NOT NULL "
                         "AND (status='confirmed' OR (status='suggested' AND confidence >= 0.8))"):
        attendees.setdefault(f"m-{r['meeting_id']}", []).append(r["person_id"])
    for m in d["meetings"]:
        if m["status"] == "personal":
            continue
        mid = node(m["id"], "meeting", m["title"], m["date"], f"/meetings/{m['id']}")
        for pid in attendees.get(m["id"], []):
            edge(pnode(pid), mid, "attended")
        if linked(mid, "meeting"):
            about(mid, [ini_id.get(n) for n in m["initiatives"]])
    for r in con.execute(f"SELECT mt.id, m.entity_id FROM meetings mt JOIN mentions m ON m.ref_type='item' AND m.ref_id=mt.note_item_id "
                         f"AND m.entity_type='org' AND {_shown('m')}"):   # the companies in each meeting
        edge(f"m-{r['id']}", f"o-{_companies.root(orgs, r['entity_id'])}", "with")

    # ---- day-to-day areas (tasks.AREAS): work that keeps the business running but moves no bet; shown when something is filed there
    from . import tasks as _tasks
    area_id = {a["key"]: node(f"area-{a['key']}", "area", a["name"], "Day-to-day area", "/tasks") for a in _tasks.areas(con)}

    # ---- top of mind (assist/topics.py): who raised each topic and who else was in it; the meetings it came up in
    for r in con.execute("SELECT id, rank, title, summary, ask, initiative_id, area, private, raised_by, people_json, sources_json FROM topics "
                         "WHERE status='current' ORDER BY rank"):
        slug = ini_slug.get(r["initiative_id"])
        tid = node(f"topic-{r['id']}", "topic", r["title"], f"#{r['rank']} on your mind", f"/initiatives/{slug}" if slug else "/initiatives",
                   rank=r["rank"], detail=r["summary"] or "", ask=r["ask"] or "", private=bool(r["private"]))
        edge(me_id if r["raised_by"] == "you" else person(r["raised_by"]), tid, "raised")
        for name in json.loads(r["people_json"] or "[]"):
            p = person(name)
            if p and (p, tid, "raised") not in edges:
                edge(p, tid, "discussed")
        if not linked(tid, "topic"):
            continue
        about(tid, [ini_id.get(r["initiative_id"]), area_id.get(r["area"])])
        for src in json.loads(r["sources_json"] or "[]"):
            hit = APP_MEETING.search(src.get("app") or "")
            if hit:
                edge(tid, hit.group(1), "came up in")
        companies_named(tid, " ".join(x or "" for x in (r["title"], r["summary"], r["ask"])))

    # ---- tasks (assist/tasks.py): Sam's list, initiative or area → task → step. A task's steps count for it: whoever a step
    # is with (Sam waits on them) and the people linked to it
    since_s = iso(now - timedelta(days=SUGGESTED_DAYS))
    rows = list(con.execute("SELECT id, parent_id, initiative_id, area, title, done_when, status, due, owner_person_id, sources_json, created_at FROM tasks "
                            "WHERE status IN ('open', 'snoozed', 'suggested') ORDER BY id"))
    tops = {r["id"]: r for r in rows if r["parent_id"] is None and (r["status"] != "suggested" or (r["created_at"] or "") >= since_s)}
    steps = defaultdict(list)
    for r in rows:
        if r["parent_id"] in tops:
            steps[r["parent_id"]].append(r)
    named = defaultdict(set)
    for r in con.execute("SELECT ref_id, entity_id FROM mentions WHERE ref_type='task' AND entity_type='person' AND COALESCE(verdict, '') != 'rejected'"):
        named[r["ref_id"]].add(r["entity_id"])
    for t in tops.values():
        st = steps[t["id"]]
        kid = node(f"task-{t['id']}", "task", t["title"], TASK_STATUS[t["status"]] + (f" · {len(st)} step{'s' if len(st) != 1 else ''}" if st else "")
                   + (f" · due {_day(t['due'])}" if t["due"] else ""), f"/tasks?open={t['id']}", status=t["status"])
        items = []
        for x in (t, *st):
            edge(pnode(x["owner_person_id"]), kid, "owes")
            for pid in named.get(x["id"], ()):
                if (f"p-{pid}", kid, "owes") not in edges:
                    edge(pnode(pid), kid, "named in")
            for src in json.loads(x["sources_json"] or "[]"):
                v = src.get("item_id") if isinstance(src, dict) else None
                if isinstance(v, int) or str(v or "").isdigit():
                    items.append(int(v))
        evidence(kid, items)
        if linked(kid, "task"):
            about(kid, [ini_id.get(t["initiative_id"]), area_id.get(t["area"])])
            companies_named(kid, " ".join(x["title"] + " " + (x["done_when"] or "") for x in (t, *st)))

    # ---- documents: whose they are and who shared them
    docs = {}
    for r in con.execute(f"SELECT i.id, i.source_id, i.subject, m.entity_id, m.role FROM mentions m JOIN items i ON i.id=m.ref_id "
                         f"WHERE m.ref_type='item' AND m.entity_type='person' AND i.kind='doc' AND m.role IN ('owner', 'shared', 'from') AND {_shown('m')}"):
        pre = DOC_PREFIX.get(r["source_id"])
        if not pre or not r["subject"] or NOT_A_DOC.search(r["subject"]):
            continue
        nid = node(f"{pre}-{r['id']}", "document", r["subject"], "", f"/documents?open={pre}-{r['id']}")
        docs[nid] = r["id"]
        edge(pnode(r["entity_id"]), nid, "shared" if r["role"] == "shared" else "owns")
    if docs:
        filed = {}
        for r in con.execute(f"SELECT ref_id, entity_id FROM mentions WHERE ref_type='item' AND entity_type='initiative' AND role='filed' "
                             f"AND ref_id IN ({_in(list(docs.values()))})", list(docs.values())):
            filed.setdefault(r["ref_id"], []).append(ini_id.get(r["entity_id"]))
        for nid, item_id in docs.items():
            if linked(nid, "document"):
                about(nid, filed.get(item_id, []))

    # what each person has on Sam's list, and an outside person's company logo
    on_list = defaultdict(set)
    for a, b, rel in edges:
        if b.startswith("task-") and nodes[a]["type"] in ("person", "partner"):
            on_list[a].add(b)
        elif rel == "works at" and nodes[b].get("logo"):
            nodes[a]["org_logo"] = nodes[b]["logo"]
    for a, ts in on_list.items():
        nodes[a]["tasks"] = len(ts)

    # people with no links and no contact with Sam say nothing here
    out = [n for n in nodes.values() if n["id"] in touched or n.get("me") or n["type"] == "initiative" or n.get("contact")]
    ids = {n["id"] for n in out}
    return {"nodes": out, "me": me_id, "unlinked": unlinked,
            "edges": [{"source": a, "target": b, "rel": r, "w": w} for (a, b, r), w in sorted(edges.items()) if a in ids and b in ids]}
