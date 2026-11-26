"""Revenue retention from Salesforce renewals, for the Retention page (Sales). Company and deal data only.

Every renewal opportunity carries the contract value it renews (the prior ARR) and its outcome. Salesforce records
the quoted value as ACV and the change against the old contract as the net forecast, so prior = ACV - net forecast for a
won or open renewal, and prior = -net forecast for a lost one (ACV is 0). Values are approximate US dollars (net
forecast in USD where Salesforce gives it, ACV at the rates pipeline.fx_rates() finds in the data).

Two levels of figures:
- Renewal book: of the ARR that came up for renewal, what was kept. Gross renewal rate = (prior - churn - downsell) /
  prior, never above 100%; net renewal rate = renewed / prior (uplifts and downsells included); logo retention =
  customers still under contract after their renewals.
- Company: GRR and NRR on the whole ARR base, which Salesforce shows only indirectly. The base today is the contract
  value of every open renewal (each live contract has one); the base on 1 January is that bridged back through this
  year's new logos, expansion, uplifts, downsell and churn. regional partner and white-label ARR has no Salesforce renewal,
  so the base is lower than finance's ARR.

Two bases: "recorded" takes Salesforce as it is; "adjusted" treats a lost renewal as a likely re-paper when the same
account won a comparable deal within 90 days (a duplicate renewal is dropped; a renewal replaced by an upsell, cross-sell
or new contract counts as kept, and its old value comes out of that deal's expansion, so NRR does not count it twice).

The outlook for next year weights each segment (region x contract size) by its share of next year's renewal book and
applies that segment's rates from this year's closed renewals (falling back to the region, then everything, when a
segment has fewer than MIN_N closed renewals). Salesforce's stage probability and "every renewal closes as quoted" are
shown beside it as the low and high views. Expansion next year is assumed to run at this year's pace.
"""
import json
import re
from collections import defaultdict
from datetime import date, timedelta

from . import pipeline
from . import org

_CRM = org.section("crm", {})   # the org pack: the company's CRM conventions
SINCE = _CRM.get("history_start") or "2026-01-01"
MIN_N = 8                  # closed renewals a segment needs before its own rate is used
REPAPER_DAYS = 90
REGIONS = tuple(_CRM.get("regions") or ["Other"])
BANDS = tuple(tuple(b) for b in _CRM.get("bands") or [[None, "All"]])
EXPANSION = set(_CRM.get("expansion") or [])
SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


def band(prior):
    for top, label in BANDS:
        if top is None or prior < top:
            return label


def region(d):
    r = d.get("target_region") or d.get("account_region") or ""
    return r if r in ("NAM", "EMEA") else "Other"


def _name_value(name, rates):
    """The prior contract value written at the end of a renewal's name ('… | Renewal | 2027-05-30 | €23.3K'), in USD."""
    m = re.search(r"\|\s*([$€£¥]|[A-Z]{3})\s?([\d.,]+)\s*([KkMm]?)\s*$", name or "")
    if not m:
        return None
    try:
        v = float(m.group(2).replace(",", ""))
    except ValueError:
        return None
    v *= {"k": 1e3, "m": 1e6}.get(m.group(3).lower(), 1)
    return v * rates.get(SYMBOL.get(m.group(1), m.group(1)), 1.0)


def _usd(d, key, rates):
    return float(d.get(key) or 0) * rates.get(d.get("currency") or "USD", 1.0)


def _net(d, rates):
    n = d.get("net_forecast_usd")
    return float(n) if n is not None else _usd(d, "net_forecast", rates)


def _day(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _load(con):
    rows = []
    for r in con.execute("SELECT id, url, payload FROM items WHERE source_id='salesforce' AND kind='opportunity' AND noise=0"):
        d = json.loads(r["payload"] or "{}")
        d["_item"], d["_url"] = r["id"], r["url"]
        rows.append(d)
    return rows


def _renewal(d, rates, today):
    """One renewal: prior ARR, the renewed (or quoted) value and the outcome. None for zero-value placeholders."""
    stage = d.get("stage") or ""
    outcome = "won" if stage == "Closed Won" else "lost" if stage == "Closed Lost" else "open" if d.get("is_open") else None
    if outcome is None:          # no longer open in Salesforce and not closed: deleted or merged
        return None
    net = _net(d, rates)
    if outcome == "lost":
        prior, value = max(0.0, -net), 0.0
    elif d.get("acv") is None:   # no ACV: the prior from the name, the quote from the net change
        prior = _name_value(d.get("name"), rates) or 0.0
        value = max(0.0, prior + net)
    else:
        value = _usd(d, "acv", rates)
        prior = max(0.0, value - net)
    if prior < 100:              # placeholder renewals ($1, €1 or empty): no ARR to keep
        return None
    close = d.get("close_date") or ""
    return {
        "id": d.get("id"), "item_id": d["_item"], "url": d["_url"], "account": d.get("account") or (d.get("name") or "").split(" - ")[0],
        "region": region(d), "band": band(prior), "outcome": outcome, "close_date": close, "quarter": pipeline.quarter(close),
        "prior_usd": round(prior), "value_usd": round(value), "change_usd": round(value - prior),
        "stage": stage, "probability": d.get("probability"), "overdue": outcome == "open" and bool(close) and close < today,
    }


def _agg(rows):
    """Rates over a set of closed renewals (each with prior_usd, value_usd, won)."""
    a = {"n": len(rows), "won": 0, "lost": 0, "prior": 0, "renewed": 0, "kept": 0, "churn": 0, "downsell": 0, "uplift": 0}
    for r in rows:
        p, v = r["prior_usd"], r["value_usd"]
        a["prior"] += p
        if r["won"]:
            a["won"] += 1
            a["renewed"] += v
            a["kept"] += min(p, v)
            a["downsell"] += max(0, p - v)
            a["uplift"] += max(0, v - p)
        else:
            a["lost"] += 1
            a["churn"] += p
    a["lost_arr"] = a["churn"] + a["downsell"]
    a["grr"] = round(a["kept"] / a["prior"], 4) if a["prior"] else None
    a["nrr"] = round(a["renewed"] / a["prior"], 4) if a["prior"] else None
    a["renewal_rate"] = round(a["won"] / a["n"], 4) if a["n"] else None
    return a


def qkey(q):
    m = re.match(r"Q(\d) (\d{4})$", q or "")
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _by(rows, key, order=None):
    groups = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    keys = order or sorted(groups, key=qkey if key == "quarter" else None)
    return [dict(_agg(groups[k]), key=k) for k in keys if k in groups]


def _repapers(lost, won_deals):
    """Lost renewal -> the comparable deal the same account won within REPAPER_DAYS (the likely replacement), or None."""
    out = {}
    for r in lost:
        when = _day(r["close_date"])
        best = None
        for w in won_deals.get(r["account"], []):
            wd = _day(w["close_date"])
            if w["id"] == r["id"] or not when or not wd or abs((wd - when).days) > REPAPER_DAYS or w["value_usd"] < 0.5 * r["prior_usd"]:
                continue
            if best is None or abs((wd - when).days) < abs((_day(best["close_date"]) - when).days):
                best = w
        if best:
            out[r["id"]] = best
    return out


def _cohort(closed, repl, basis):
    """Closed renewals as counted on a basis: rows with won=True/False, plus the expansion to take back out."""
    rows, taken_back, left = [], 0, {}
    for r in closed:
        x = dict(r, won=r["outcome"] == "won")
        rp = repl.get(r["id"]) if basis == "adjusted" else None
        if rp:
            if rp["kind"] == "Renewal":
                continue                                  # a duplicate of a renewal that was won
            x.update(won=True, value_usd=r["prior_usd"])  # replaced by a bigger contract: kept at its old value
            room = left.setdefault(rp["id"], max(rp["net_usd"], 0))   # one deal can replace several renewals, up to its own value
            take = min(r["prior_usd"], room)
            left[rp["id"]] = room - take
            taken_back += take
        rows.append(x)
    return rows, taken_back


def _rates(rows):
    """Segment -> (gross, net, renewal rate, n, where the rate came from), with fallbacks for thin segments."""
    seg, reg = defaultdict(list), defaultdict(list)
    for r in rows:
        seg[(r["region"], r["band"])].append(r)
        reg[r["region"]].append(r)
    overall = _agg(rows)

    def rate(region_, band_):
        for src, l in (("segment", seg.get((region_, band_), [])), ("region", reg.get(region_, [])), ("all", rows)):
            if len(l) >= MIN_N or src == "all":
                a = _agg(l) if l is not rows else overall
                return {"grr": a["grr"] or 0, "nrr": a["nrr"] or 0, "renewal_rate": a["renewal_rate"] or 0, "n": a["n"], "source": src}
    return rate


def _outlook(book, rate):
    """Expected retention for a set of open renewals: by segment share, Salesforce stage, and as quoted."""
    total = sum(r["prior_usd"] for r in book)
    segs = defaultdict(list)
    for r in book:
        segs[(r["region"], r["band"])].append(r)
    out_segs, kept, renewed = [], 0.0, 0.0
    for reg in REGIONS:
        for _, b in BANDS:
            l = segs.get((reg, b))
            if not l:
                continue
            p = sum(r["prior_usd"] for r in l)
            rt = rate(reg, b)
            kept += p * rt["grr"]
            renewed += p * rt["nrr"]
            out_segs.append({"region": reg, "band": b, "n": len(l), "prior": p, "share": round(p / total, 4) if total else 0,
                             "quoted": sum(r["value_usd"] for r in l), "grr": rt["grr"], "nrr": rt["nrr"], "renewal_rate": rt["renewal_rate"],
                             "hist_n": rt["n"], "source": rt["source"], "expected_kept": round(p * rt["grr"]), "expected_renewed": round(p * rt["nrr"])})
    stage_kept = sum((r["probability"] or 0) / 100 * min(r["prior_usd"], r["value_usd"]) for r in book)
    stage_renewed = sum((r["probability"] or 0) / 100 * r["value_usd"] for r in book)
    quoted_kept = sum(min(r["prior_usd"], r["value_usd"]) for r in book)
    quoted = sum(r["value_usd"] for r in book)
    f = lambda x: round(x / total, 4) if total else None
    return {"n": len(book), "accounts": len({r["account"] for r in book}), "prior": total, "segments": out_segs,
            "grr": f(kept), "nrr": f(renewed), "expected_kept": round(kept), "expected_renewed": round(renewed), "expected_lost": round(total - kept),
            "stage": {"grr": f(stage_kept), "nrr": f(stage_renewed)}, "as_quoted": {"grr": f(quoted_kept), "nrr": f(quoted)},
            "downsell_quoted": round(sum(max(0, r["prior_usd"] - r["value_usd"]) for r in book))}


def summary(con, today=None):
    today = today or date.today()
    iso = today.isoformat()
    rows = _load(con)
    rates = pipeline.fx_rates(rows)
    pulled = max((d.get("seen") or "" for d in rows), default=None) or None
    year = today.year

    ren, deals = [], []          # deals: every won non-services deal since SINCE (for re-papers and expansion)
    for d in rows:
        kind = pipeline._kind(d)
        if kind == "Renewal":
            r = _renewal(d, rates, iso)
            if r:
                ren.append(r)
        if kind != "Services" and d.get("stage") == "Closed Won" and (d.get("close_date") or "") >= SINCE:
            net = _net(d, rates)
            deals.append({"id": d.get("id"), "account": d.get("account") or "", "kind": kind, "sale_type": d.get("sale_type") or "",
                          "close_date": d.get("close_date") or "", "value_usd": round(_usd(d, "acv", rates) if d.get("acv") is not None else net),
                          "net_usd": round(net), "name": d.get("name") or "", "url": d["_url"], "item_id": d["_item"]})
    closed = [r for r in ren if r["outcome"] != "open" and r["close_date"] >= SINCE]
    book = [r for r in ren if r["outcome"] == "open"]
    won_by_acct = defaultdict(list)
    for w in deals:
        if w["kind"] == "Renewal" or w["sale_type"] in EXPANSION or w["sale_type"] == "New Logo":
            won_by_acct[w["account"]].append(w)
    repl = _repapers([r for r in closed if r["outcome"] == "lost"], won_by_acct)

    days_in = max(1, (today - date.fromisoformat(SINCE)).days + 1)
    days_left = max(0, (date(year, 12, 31) - today).days)
    new_logo = sum(w["net_usd"] for w in deals if w["sale_type"] == "New Logo")
    expansion_all = sum(w["net_usd"] for w in deals if w["sale_type"] in EXPANSION)
    base_now = sum(r["prior_usd"] for r in book)
    open_accounts = {r["account"] for r in book}
    won_accounts = {w["account"] for w in deals}

    bases = {}
    for basis in ("recorded", "adjusted"):
        cohort, taken_back = _cohort(closed, repl, basis)
        a = _agg(cohort)
        expansion = expansion_all - taken_back
        # logos: a customer is lost when every renewal it had this year was lost and nothing else keeps it under contract
        acc = defaultdict(list)
        for r in cohort:
            acc[r["account"]].append(r)
        lost_logos = sorted(k for k, l in acc.items() if not any(r["won"] for r in l) and k not in open_accounts and k not in won_accounts)
        start = base_now - new_logo - expansion - a["uplift"] + a["lost_arr"]
        rate = _rates(cohort)
        rest = [r for r in book if r["close_date"] and r["close_date"] <= f"{year}-12-31"]   # still due this year, overdue included
        nxt = [r for r in book if r["close_date"][:4] == str(year + 1)]
        rest_o, next_o = _outlook(rest, rate), _outlook(nxt, rate)
        pace = expansion / days_in                                             # expansion per day this year
        fy_lost = a["lost_arr"] + rest_o["expected_lost"]
        fy_uplift = a["uplift"] + max(0, rest_o["expected_renewed"] - rest_o["expected_kept"])
        fy_expansion = expansion + pace * days_left
        # 1 January next year: today's contracts after the rest of this year's renewals, plus expansion at this year's pace
        # (new logos still to close this year are left out)
        start_next = base_now - rest_o["prior"] + rest_o["expected_renewed"] + pace * days_left
        nxt_up = max(0, next_o["expected_renewed"] - next_o["expected_kept"])
        nxt_expansion = pace * 365
        bases[basis] = {
            "actual": dict(a, by_quarter=_by(cohort, "quarter"), by_region=_by(cohort, "region", list(REGIONS)),
                           by_band=_by(cohort, "band", [b for _, b in BANDS]),
                           by_region_quarter=[dict(_agg([r for r in cohort if r["region"] == g and r["quarter"] == q]), region=g, quarter=q)
                                              for q in sorted({r["quarter"] for r in cohort}, key=qkey) for g in REGIONS
                                              if any(r["region"] == g and r["quarter"] == q for r in cohort)],
                           logos=len(acc), logos_lost=len(lost_logos), logo_retention=round(1 - len(lost_logos) / len(acc), 4) if acc else None,
                           lost_logo_accounts=lost_logos),
            "company": {
                "base_start": round(start), "new_logo": round(new_logo), "expansion": round(expansion), "expansion_taken_back": round(taken_back),
                "grr": round(1 - a["lost_arr"] / start, 4) if start > 0 else None,
                "nrr": round(1 + (a["uplift"] + expansion - a["lost_arr"]) / start, 4) if start > 0 else None,
                "fy": {"lost": round(fy_lost), "uplift": round(fy_uplift), "expansion": round(fy_expansion),
                       "grr": round(1 - fy_lost / start, 4) if start > 0 else None,
                       "nrr": round(1 + (fy_uplift + fy_expansion - fy_lost) / start, 4) if start > 0 else None},
            },
            "rest_of_year": rest_o,
            "next_year": dict(next_o, year=year + 1, base_start=round(start_next), expansion=round(nxt_expansion), uplift=round(nxt_up),
                              company_grr=round(1 - next_o["expected_lost"] / start_next, 4) if start_next > 0 else None,
                              company_nrr=round(1 + (nxt_up + nxt_expansion - next_o["expected_lost"]) / start_next, 4) if start_next > 0 else None,
                              by_quarter=[{"quarter": q, "prior": sum(r["prior_usd"] for r in nxt if r["quarter"] == q),
                                           "n": sum(1 for r in nxt if r["quarter"] == q),
                                           "expected_kept": round(sum(r["prior_usd"] * rate(r["region"], r["band"])["grr"] for r in nxt if r["quarter"] == q))}
                                          for q in (f"Q{i} {year + 1}" for i in range(1, 5))]),
        }

    churned = defaultdict(list)          # accounts that lost or cut ARR this year: a flag on next year's renewals
    for r in closed:
        if r["outcome"] == "lost" or r["change_usd"] < 0:
            churned[r["account"]].append(r["outcome"])
    rate_rec, rate_adj = _rates(_cohort(closed, repl, "recorded")[0]), _rates(_cohort(closed, repl, "adjusted")[0])
    upcoming = sorted((r for r in book if r["close_date"][:4] == str(year + 1) or r["overdue"] or r["close_date"][:4] == str(year)),
                      key=lambda r: -r["prior_usd"])
    for r in upcoming:
        r["history"] = "lost a renewal" if "lost" in churned.get(r["account"], []) else "downsold" if r["account"] in churned else ""
        r["rate"] = {"recorded": rate_rec(r["region"], r["band"])["grr"], "adjusted": rate_adj(r["region"], r["band"])["grr"]}
    for r in closed:
        rp = repl.get(r["id"])
        r["replaced_by"] = {k: rp[k] for k in ("sale_type", "close_date", "value_usd", "url", "kind")} if rp else None
    by_region_now = {g: round(sum(r["prior_usd"] for r in book if r["region"] == g)) for g in REGIONS}
    return {
        "today": iso, "pulled": pulled, "since": SINCE, "year": year, "min_n": MIN_N, "repaper_days": REPAPER_DAYS,
        "fx": {k: round(v, 4) for k, v in rates.items() if any(d.get("currency") == k for d in rows)},
        "base_now": {"arr": round(base_now), "contracts": len(book), "accounts": len(open_accounts), "by_region": by_region_now},
        "bases": bases,
        "closed": sorted(closed, key=lambda r: r["close_date"], reverse=True),
        "upcoming": upcoming[:300],
        "notes": {"loss_reasons": sum(1 for d in rows if d.get("stage") == "Closed Lost" and pipeline._kind(d) == "Renewal" and (d.get("loss_reason") or d.get("churn_reason"))),
                  "lost_renewals": sum(1 for r in closed if r["outcome"] == "lost"), "repapers": len(repl),
                  "regions_other": sorted({d.get("target_region") or d.get("account_region") or "—" for d in rows
                                           if pipeline._kind(d) == "Renewal" and region(d) == "Other"})},
    }
