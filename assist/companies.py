"""Companies (Sam, 23 Oct 2026): People › Companies, one page per company Sam deals with. Acme itself (the old Company
page), partners, customers, prospects, investors, and everything else folded under Other.

Built on orgs (Salesforce accounts, mail domains, records kept by hand) and what is linked to them (mentions, the same rule
as the person and initiative pages: confirmed, or unreviewed at confidence 0.6 and up, never rejected).

What a company is to Acme (relation): Sam's own call (orgs.relation) wins; Acme is ours; a record kept by hand says
partner, investor or vendor; a Salesforce account is a customer when it has a renewal, an upsell, a cross-sell or a won deal,
and a prospect when it only has new-logo deals (an account Salesforce types Partner is a partner); the rest is Other. One company recorded twice is merged by Sam
(orgs.merged_into): it then shows every record's people, deals and activity under one name.

Deals are Salesforce opportunities: company and deal data only, never contact details (org rule). People are the ones in
SleePO's own material (mail, meetings, messages) linked to the company.
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import entities, logos as _logos
from . import org

RELATIONS = ("partner", "customer", "prospect", "investor", "vendor", "other")
ORDER = ("ours", "partner", "customer", "prospect", "investor", "vendor", "other")   # sections of the list, and which record of a merge speaks for it
LABEL = {"ours": "Our company", "partner": "Partners", "customer": "Customers", "prospect": "Prospects", "investor": "Investors & board",
         "vendor": "Vendors", "other": "Other"}
CUSTOMER_SALES = set(org.section("crm", {}).get("customer_sales") or [])   # the org pack
SHOWN = "(COALESCE(m.verdict, '') = 'confirmed' OR (m.verdict IS NULL AND m.confidence >= 0.6))"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _orgs(con):
    return {r["id"]: dict(r) for r in con.execute("SELECT id, name, kind, source, region, relation, merged_into, sf_type, website FROM orgs")}


def root(orgs, oid):
    """The record a company is shown under: follow merged_into (a few steps at most; a loop stops where it started)."""
    seen = set()
    while oid in orgs and orgs[oid].get("merged_into") and oid not in seen:
        seen.add(oid)
        oid = orgs[oid]["merged_into"]
    return oid


def _deals(con):
    """Salesforce opportunities by account name (orgs.name of the account record)."""
    out = defaultdict(list)
    for (p,) in con.execute("SELECT payload FROM items WHERE source_id='salesforce' AND kind='opportunity'"):
        d = json.loads(p or "{}")
        if d.get("account"):
            out[d["account"]].append({k: d.get(k) for k in ("name", "stage", "close_date", "acv", "currency", "net_forecast_usd", "sale_type",
                                                             "is_open", "forecast_category", "probability")})
    return out


def worked_out(o, deals):
    """What one record says the company is, before Sam's call."""
    if o["kind"] == "internal":
        return "ours"
    if o["kind"] in ("partner", "investor", "vendor", "customer"):
        return o["kind"]
    if o.get("sf_type") == "Partner":   # Salesforce's account Type (its Partner Type field also marks deals sold through a partner)
        return "partner"
    if deals:
        return "customer" if any(d.get("sale_type") in CUSTOMER_SALES or d.get("stage") == "Closed Won" for d in deals) else "prospect"
    return "other"


def _usd(d):
    try:
        return float(d.get("acv") or 0) if (d.get("currency") or "USD") == "USD" else float(d.get("net_forecast_usd") or d.get("acv") or 0)
    except (TypeError, ValueError):
        return 0.0


def _logo(rid, doms, have):
    """The logo fields of a company: a version for its address (changes when the logo does) and its size in px."""
    d = doms.get(rid)
    f = have.get(d[0]) if d else None
    return {"logo": re.sub(r"\D", "", f[2]) if f else None, "logo_px": f[1] if f else None}


def listing(con, logos=True):
    """Every company with something to show (activity, deals, or a relation), grouped and newest activity first."""
    orgs, deals_by = _orgs(con), _deals(con)
    act = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT m.entity_id, COUNT(DISTINCT m.ref_id), MAX(i.ts) FROM mentions m JOIN items i ON i.id=m.ref_id "
        f"WHERE m.ref_type='item' AND m.entity_type='org' AND {SHOWN} AND i.noise=0 AND i.kind != 'opportunity' AND i.ts <= ? GROUP BY m.entity_id", (_now(),))}
    ppl = _their_people(con)
    groups = defaultdict(list)
    for oid in orgs:
        groups[root(orgs, oid)].append(oid)
    year = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
    doms, have = (_logos.domains(con, orgs, groups), _logos.cached(con)) if logos else ({}, {})
    out = []
    for rid, members in groups.items():
        r = orgs[rid]
        deals = [d for m in members for d in deals_by.get(orgs[m]["name"], [])]
        links = sum(act.get(m, (0, None))[0] for m in members)
        last = max((act[m][1] for m in members if m in act and act[m][1]), default=None)
        guesses = [worked_out(orgs[m], deals_by.get(orgs[m]["name"], [])) for m in members]
        rel = r["relation"] or min(guesses, key=ORDER.index)
        if r["relation"] == "hidden" or not (links or deals or r["relation"] or r["kind"] in ("internal", "partner", "investor")):
            continue
        open_ = [d for d in deals if d.get("is_open")]
        out.append({"id": rid, "name": r["name"], "relation": rel, "relation_by": "you" if r["relation"] else "sleepo", "region": r["region"],
                    "merged": [orgs[m]["name"] for m in members if m != rid], "links": links, "last": last,
                    "people": len(set().union(*(ppl.get(m, set()) for m in members))),
                    "deals_open": len(open_), "open_usd": round(sum(_usd(d) for d in open_)),
                    "won_usd": round(sum(_usd(d) for d in deals if d.get("stage") == "Closed Won" and (d.get("close_date") or "") >= year)),
                    **_logo(rid, doms, have)})
    return sorted(out, key=lambda x: (ORDER.index(x["relation"]), -_ts(x["last"]), x["name"].lower()))


def _their_people(con):
    """{org id: person ids} for a company's own people: an address at one of its domains, or tied to it (people.org_id).
    Sharing a thread with a company is not working there (a joint meeting brings the partner's people too)."""
    by_domain = {d: o for d, o in con.execute("SELECT domain, org_id FROM org_domains")}
    out = defaultdict(set)
    for alias, pid in con.execute("SELECT a.alias, a.person_id FROM people_aliases a JOIN people p ON p.id=a.person_id AND p.is_me=0 "
                                  "AND COALESCE(p.affiliation, '') NOT IN ('employee', 'former employee') WHERE a.alias LIKE '%@%'"):
        o = by_domain.get(alias.rsplit("@", 1)[1].lower())
        if o:
            out[o].add(pid)
    for p in con.execute("SELECT id, org_id FROM people WHERE org_id IS NOT NULL AND is_me=0 AND COALESCE(affiliation, '') NOT IN ('employee', 'former employee')"):
        out[p["org_id"]].add(p["id"])
    return out


def _ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def page(con, org_id):
    """One company: who it is, its people, its deals, its latest activity and the initiatives it touches."""
    orgs, deals_by = _orgs(con), _deals(con)
    if org_id not in orgs:
        return None
    rid = root(orgs, org_id)
    members = [m for m in orgs if root(orgs, m) == rid]
    r = orgs[rid]
    deals = [d for m in members for d in deals_by.get(orgs[m]["name"], [])]
    rel = r["relation"] or min((worked_out(orgs[m], deals_by.get(orgs[m]["name"], [])) for m in members), key=ORDER.index)
    q = ",".join("?" * len(members))
    domains = sorted({x[0] for x in con.execute(f"SELECT domain FROM org_domains WHERE org_id IN ({q})", members)})
    mine = set().union(*(_their_people(con).get(m, set()) for m in members))
    counts = defaultdict(int)
    for pid, n in con.execute(
            "SELECT m2.entity_id, COUNT(DISTINCT m.ref_id) FROM mentions m JOIN mentions m2 ON m2.ref_type='item' AND m2.ref_id=m.ref_id AND m2.entity_type='person' "
            f"WHERE m.ref_type='item' AND m.entity_type='org' AND m.entity_id IN ({q}) AND {SHOWN} GROUP BY m2.entity_id", members):
        counts[pid] += n
    for pid in mine:
        counts[pid] += 1
    theirs, ours = [], []
    for p in con.execute(f"SELECT id, name, title, affiliation, is_me FROM people WHERE id IN ({','.join('?' * len(counts)) or 'NULL'})", list(counts)):
        if p["is_me"]:
            continue
        x = {"id": f"p-{p['id']}", "name": p["name"], "title": p["title"] or "", "n": counts[p["id"]]}
        if p["affiliation"] in ("employee", "former employee"):
            (theirs if rel == "ours" else ours).append(x)
        elif p["id"] in mine:
            theirs.append(x)
    theirs.sort(key=lambda x: -x["n"]); ours.sort(key=lambda x: -x["n"])
    if rel == "ours":   # Acme: its people are the staff
        theirs = [{"id": f"p-{p['id']}", "name": p["name"], "title": p["title"] or "", "n": 0} for p in con.execute(
            "SELECT id, name, title FROM people WHERE affiliation='employee' AND is_me=0 ORDER BY name")]
    activity = sorted((x for m in members for x in entities.timeline(con, "org", m, limit=30)), key=lambda x: x["ts"] or "", reverse=True)
    # a sender recorded only as an address shows as the person it belongs to, or not at all: no bare addresses on a company page
    names = {a.lower(): n for a, n in con.execute("SELECT a.alias, p.name FROM people_aliases a JOIN people p ON p.id=a.person_id WHERE a.alias LIKE '%@%'")}
    seen, recent = set(), []
    for x in activity:
        if x["id"] not in seen:
            seen.add(x["id"]); recent.append({k: x.get(k) for k in ("id", "kind", "label", "ts", "from", "title", "url", "mine", "where")})
            if "@" in (recent[-1]["from"] or ""):
                recent[-1]["from"] = names.get(recent[-1]["from"].strip().lower(), "")
    inis = [dict(x) for x in con.execute(
        "SELECT ini.id, ini.slug, ini.name, COUNT(DISTINCT m.ref_id) AS n FROM mentions m JOIN mentions m2 ON m2.ref_type='item' AND m2.ref_id=m.ref_id "
        "AND m2.entity_type='initiative' JOIN initiatives ini ON ini.id=m2.entity_id AND ini.active=1 "
        f"WHERE m.ref_type='item' AND m.entity_type='org' AND m.entity_id IN ({q}) AND {SHOWN} GROUP BY ini.id ORDER BY n DESC LIMIT 4", members)]
    order = lambda d: (not d.get("is_open"), d.get("close_date") or "")
    return {"id": rid, "name": r["name"], "relation": rel, "relation_by": "you" if r["relation"] else "sleepo", "kind": r["kind"], "region": r["region"],
            "sf_type": next((orgs[m]["sf_type"] for m in members if orgs[m].get("sf_type")), None),
            **_logo(rid, _logos.domains(con, orgs, {rid: members}), _logos.cached(con)),
            "domains": domains, "records": [{"id": m, "name": orgs[m]["name"], "kind": orgs[m]["kind"]} for m in members],
            "people": theirs[:16], "people_total": len(theirs), "our_people": ours[:8], "deals": sorted(deals, key=order)[:40], "activity": recent[:40], "initiatives": inis}


def set_relation(con, org_id, relation):
    """Sam's call on what a company is to Acme; None hands it back to SleePO; 'hidden' keeps it off the list."""
    if relation not in RELATIONS + ("hidden", None):
        raise ValueError("relation must be one of " + ", ".join(RELATIONS + ("hidden",)))
    orgs = _orgs(con)
    if org_id not in orgs:
        raise ValueError("no such company")
    con.execute("UPDATE orgs SET relation=?, updated_at=? WHERE id=?", (relation, _now(), root(orgs, org_id)))
    con.commit()


def merge(con, org_id, into_id):
    """Show org_id (and anything merged into it) under into_id's company. Unmerge with into_id=None."""
    orgs = _orgs(con)
    if org_id not in orgs or (into_id is not None and into_id not in orgs):
        raise ValueError("no such company")
    if into_id is None:
        con.execute("UPDATE orgs SET merged_into=NULL, updated_at=? WHERE id=?", (_now(), org_id))
    else:
        target = root(orgs, into_id)
        if root(orgs, org_id) == target:
            raise ValueError("already the same company")
        con.execute("UPDATE orgs SET merged_into=?, updated_at=? WHERE id=? OR merged_into=?", (target, _now(), org_id, org_id))
        con.execute("UPDATE orgs SET merged_into=NULL WHERE id=?", (target,))
    con.commit()


def rename(con, org_id, name):
    """Sam's name for a company SleePO made from a mail domain ("Fabrikam" -> "Fabrikam"). A Salesforce account keeps
    Salesforce's name: deals are matched to it by name."""
    orgs = _orgs(con)
    rid = root(orgs, org_id) if org_id in orgs else None
    name = re.sub(r"\s+", " ", name or "").strip()
    if rid is None:
        raise ValueError("no such company")
    if not name or len(name) > 120:
        raise ValueError("give a name of up to 120 characters")
    if orgs[rid]["kind"] == "account":
        raise ValueError("a Salesforce account keeps its Salesforce name")
    con.execute("UPDATE orgs SET name=?, updated_at=? WHERE id=?", (name, _now(), rid))
    # the morning's full re-link re-derives mail domains and finds a domain's company by the name it made ("Fabrikam"):
    # the renamed company's domains are pinned so they stay with it (entities.link deletes only 'domain' and 'salesforce-match')
    members = [m for m in orgs if root(orgs, m) == rid]
    con.execute(f"UPDATE org_domains SET source='sam' WHERE source IN ('domain', 'salesforce-match') AND org_id IN ({','.join('?' * len(members))})", members)
    con.commit()


ACCOUNT_FIELDS = ("name", "type", "website", "email_domain")   # company fields only (org rule): never owners, contacts or free text


def store_accounts(con, accounts):
    """Salesforce account facts, matched to the account records by name: the account Type, the website (the logo is looked
    up by it) and the mail domain. A website or mail domain no company holds yet is added to the account, so mail from there
    links to it. One that a company made from a mail domain holds is the same company recorded twice: it is merged into the
    account, once, when the account's facts first arrive (Sam's "separate" then sticks), and a pick Sam made on it carries over."""
    # a shared suffix (gov.za, org.uk) is no one's domain: the first load on 23 Oct 2026 stored ten before registrable knew them
    for (d,) in con.execute("SELECT domain FROM org_domains WHERE source='salesforce'").fetchall():
        if entities.public_suffix(d):
            con.execute("DELETE FROM org_domains WHERE domain=? AND source='salesforce'", (d,))
    orgs = _orgs(con)
    by_name = {o["name"]: o for o in orgs.values() if o["kind"] == "account"}
    out = {"matched": 0, "domains": 0, "merged": 0}
    for a in accounts:
        o = by_name.get((a.get("name") or "").strip())
        if not o:
            continue
        out["matched"] += 1
        first = o["sf_type"] is None and o["website"] is None
        site = _logos.host_of(a.get("website"))
        con.execute("UPDATE orgs SET sf_type=COALESCE(?, sf_type), website=COALESCE(?, website), updated_at=? WHERE id=?",
                    (a.get("type") or None, site, _now(), o["id"]))
        o["sf_type"], o["website"] = a.get("type") or o["sf_type"], site or o["website"]
        doms = {entities.registrable(d) for d in (site, _logos.host_of(a.get("email_domain"))) if d}
        for d in sorted(x for x in doms if x and x not in entities.FREE_MAIL and x not in entities.INTERNAL and not entities.public_suffix(x)):
            row = con.execute("SELECT org_id FROM org_domains WHERE domain=?", (d,)).fetchone()
            if not row:
                con.execute("INSERT INTO org_domains (domain, org_id, source) VALUES (?,?,'salesforce')", (d, o["id"]))
                out["domains"] += 1
                continue
            other = orgs.get(row[0])
            target = root(orgs, o["id"])
            if first and other and other["kind"] == "external" and not other["merged_into"] and root(orgs, other["id"]) != target:
                con.execute("UPDATE orgs SET merged_into=?, updated_at=? WHERE id=?", (target, _now(), other["id"]))
                if other["relation"] and not orgs[target]["relation"]:
                    con.execute("UPDATE orgs SET relation=? WHERE id=?", (other["relation"], target))
                    orgs[target]["relation"] = other["relation"]
                other["merged_into"] = target
                out["merged"] += 1
    return out

def search(con, q, limit=12):
    """Records by name, for "same company as…" (every org, merged or not)."""
    orgs = _orgs(con)
    ql = (q or "").strip().lower()
    hits = [o for o in orgs.values() if ql and ql in o["name"].lower()]
    hits.sort(key=lambda o: (not o["name"].lower().startswith(ql), len(o["name"])))
    return [{"id": o["id"], "name": o["name"], "kind": o["kind"], "company": orgs[root(orgs, o["id"])]["name"]} for o in hits[:limit]]
