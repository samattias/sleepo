"""Open Salesforce pipeline for the Pipeline view (company and deal data only, as stored by the /salesforce skill).

Values are in each deal's own currency. For totals they are converted to approximate US dollars with the rate the data
itself implies (median of net_forecast_usd / net_forecast per currency), falling back to fixed rates. Flags: overdue
(close date already passed but still open) and implausible close dates (more than five years out).
"""
import json
import statistics
from datetime import date
from . import org

_CRM = org.section("crm", {})   # the org pack: the company's CRM conventions
FALLBACK_FX = _CRM.get("fx") or {"USD": 1.0}
STAGE_ORDER = _CRM.get("stage_order") or []


def fx_rates(rows):
    found = {}
    for d in rows:
        nf, nu = d.get("net_forecast") or 0, d.get("net_forecast_usd") or 0
        if nf > 0 and nu > 0 and d.get("currency"):
            found.setdefault(d["currency"], []).append(nu / nf)
    rates = dict(FALLBACK_FX)
    rates.update({c: statistics.median(v) for c, v in found.items() if len(v) >= 3 or c not in rates})
    rates["USD"] = 1.0
    return rates


def quarter(d):
    try:
        y, m = int(d[:4]), int(d[5:7])
    except (TypeError, ValueError):
        return ""
    return f"Q{(m - 1) // 3 + 1} {y}"


def listing(con):
    rows, pulled = [], None
    for r in con.execute("SELECT id, url, payload FROM items WHERE source_id='salesforce' AND kind='opportunity' AND noise=0"):
        d = json.loads(r["payload"] or "{}")
        if d.get("is_open") is False:
            continue
        d["_item"], d["_url"] = r["id"], r["url"]
        rows.append(d)
        pulled = max(pulled or "", d.get("seen") or "")
    rates = fx_rates(rows)
    today = date.today().isoformat()
    far = date(date.today().year + 5, 12, 31).isoformat()
    out = []
    for d in rows:
        cur = d.get("currency") or "USD"
        acv = float(d.get("acv") or 0)
        acv_usd = acv * rates.get(cur, 1.0)
        prob = d.get("probability")
        close = d.get("close_date") or ""
        name = d.get("name") or ""
        out.append({
            "id": d.get("id"), "item_id": d["_item"], "url": d["_url"], "account": d.get("account") or name.split(" - ")[0],
            "name": name, "stage": d.get("stage") or "", "stage_rank": STAGE_ORDER.index(d["stage"]) if d.get("stage") in STAGE_ORDER else 99,
            "forecast_category": d.get("forecast_category") or "", "probability": prob, "sale_type": d.get("sale_type") or "",
            "use_case": d.get("use_case") or "", "region": d.get("account_region") or d.get("target_region") or "",
            "currency": cur, "acv": acv, "acv_usd": round(acv_usd), "weighted_usd": round(acv_usd * (prob or 0) / 100),
            "forecast_usd": round(d.get("net_forecast_usd") or 0), "close_date": close, "quarter": quarter(close),
            "created": d.get("created") or "", "overdue": bool(close) and close < today, "odd_date": bool(close) and close > far,
        })
    out.sort(key=lambda x: (x["close_date"] or "9999", -x["acv_usd"]))
    return {"opportunities": out, "fx": {k: round(v, 4) for k, v in rates.items() if any(o["currency"] == k for o in out)},
            "pulled": pulled, "today": today}


NEW_BUSINESS = set(_CRM.get("new_business") or [])


def _kind(d):
    """New business / Renewal / Services. Services deals carry no ACV; their value is the net forecast."""
    if "| Service |" in (d.get("name") or "") or (d.get("acv") is None and d.get("sale_type") != "Renewal"):
        return "Services"
    return "Renewal" if d.get("sale_type") == "Renewal" else "New business"


def closed(con, since="2026-01-01"):
    """Closed Won / Closed Lost deals with a close date on or after `since`, for the Pipeline view's history tab.

    value_usd is ACV (for Services, the net forecast) in approximate USD; net_usd is the net ARR change Salesforce records
    (net forecast, converted), which is what a renewal adds or loses against the previous contract. Region is the sales
    territory (target_region; APAC is folded into EMEA there), falling back to the account's region."""
    rows = []
    for r in con.execute("SELECT id, url, payload FROM items WHERE source_id='salesforce' AND kind='opportunity' AND noise=0"):
        d = json.loads(r["payload"] or "{}")
        if not (d.get("stage") or "").startswith("Closed") or (d.get("close_date") or "") < since:
            continue
        d["_item"], d["_url"] = r["id"], r["url"]
        rows.append(d)
    rates = fx_rates(rows)
    out = []
    for d in rows:
        cur = d.get("currency") or "USD"
        kind = _kind(d)
        rate = rates.get(cur, 1.0)
        acv_usd = float(d.get("acv") or 0) * rate
        net_usd = d.get("net_forecast_usd")
        if net_usd is None:
            net_usd = float(d.get("net_forecast") or 0) * rate
        name, close, created = d.get("name") or "", d.get("close_date") or "", d.get("created") or ""
        try:
            cycle = (date.fromisoformat(close) - date.fromisoformat(created)).days
        except ValueError:
            cycle = None
        out.append({
            "id": d.get("id"), "item_id": d["_item"], "url": d["_url"], "account": d.get("account") or name.split(" - ")[0], "name": name,
            "won": d.get("stage") == "Closed Won", "sale_type": d.get("sale_type") or "", "kind": kind,
            "region": d.get("target_region") or d.get("account_region") or "", "use_case": d.get("use_case") or "",
            "currency": cur, "acv": float(d.get("acv") or d.get("net_forecast") or 0),
            "value_usd": round(acv_usd if kind != "Services" else net_usd), "net_usd": round(net_usd),
            "close_date": close, "quarter": quarter(close), "created": created, "cycle_days": cycle,
        })
    out.sort(key=lambda x: x["close_date"], reverse=True)
    pulled = max((d.get("seen") or "" for d in rows), default=None)
    return {"deals": out, "since": since, "pulled": pulled, "today": date.today().isoformat(),
            "fx": {k: round(v, 4) for k, v in rates.items() if any(o["currency"] == k for o in out)}}
