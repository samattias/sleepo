"""Salesforce pipeline: turn saved sf_get_open_opportunities results into one ingest bundle.

The /salesforce skill calls the Acme Account Intelligence connector in created-date windows (the tool caps at 500
rows and has no offset) and saves each JSON result. `assist sf-bundle <files>` maps them to items and writes
inbox/queue/salesforce-<date>.json. Only company and deal fields survive (ingest.SF_FIELDS); owner names and free
text never reach the bundle. Opportunities seen before but missing from a complete pull are marked is_open=false.
"""
import json
import re
from datetime import date
from pathlib import Path

from . import db
from . import org
from .ingest import SF_FIELDS

_CRM = org.section("crm", {})   # the org pack: the company's CRM
INSTANCE = _CRM.get("instance") or ""
CAP = 500
# Salesforce holds DealHub billing test records; keep them but mark them as noise.
TEST_ACCOUNT = re.compile(r"\bUAT\b|\btest\b|sandbox|dummy", re.I)


def _payload(o, today):
    acct = o.get("Account") or {}
    p = {"id": o["Id"], "name": o.get("Name"), "account": acct.get("Name"), "account_region": acct.get("Region__c"),
         "target_region": o.get("Target_Region__c"), "stage": o.get("StageName"), "forecast_category": o.get("Mgmt_FCST_Category__c"),
         "probability": o.get("Probability"), "sale_type": o.get("Sale_Type__c"), "use_case": o.get("Use_Case__c"),
         "currency": o.get("CurrencyIsoCode"), "acv": o.get("Amount_ACV__c"), "net_forecast": o.get("Net_Forecast_Amount__c"),
         "net_forecast_usd": o.get("Net_Forecast_Amount_Converted_USD__c"), "close_date": o.get("CloseDate"),
         "created": (o.get("CreatedDate") or "")[:10], "is_open": True, "seen": today}
    return {k: v for k, v in p.items() if k in SF_FIELDS}


def _text(p):
    amt = p.get("net_forecast")
    money = f"{p.get('currency') or ''} {amt:,.0f}".strip() if isinstance(amt, (int, float)) else "no amount"
    return " · ".join(x for x in [p.get("stage"), money, f"close {p.get('close_date')}", p.get("use_case")] if x)


def build(con, files, out=None):
    today = date.today().isoformat()
    seen, available, capped = {}, 0, []
    for f in files:
        d = json.loads(Path(f).read_text())
        rows = d.get("opportunities") or []
        available += d.get("totalSize", len(rows))
        if len(rows) >= CAP:
            capped.append(str(f))
        for o in rows:
            seen[o["Id"]] = o
    complete = not capped
    items = []
    for oid, o in seen.items():
        p = _payload(o, today)
        items.append({"source_id": "salesforce", "external_id": f"sf:{oid}", "kind": "opportunity", "ts": f"{p['close_date']}T00:00:00Z",
                      "subject": p.get("name"), "thread": p.get("account"), "text": _text(p), "payload": p, "pull": 0,
                      "noise": bool(TEST_ACCOUNT.search(p.get("account") or "")),
                      "url": f"{INSTANCE}/lightning/r/Opportunity/{oid}/view"})
    closed = 0
    if complete:
        for r in con.execute("SELECT external_id, ts, subject, thread, text, url, payload FROM items WHERE source_id='salesforce'"):
            p = json.loads(r["payload"] or "{}")
            if r["external_id"][3:] in seen or not p.get("is_open"):
                continue
            p.update(is_open=False)
            items.append({"source_id": "salesforce", "external_id": r["external_id"], "kind": "opportunity", "ts": r["ts"], "subject": r["subject"],
                          "thread": r["thread"], "text": r["text"], "url": r["url"], "payload": p, "pull": 0})
            closed += 1
    note = f"open opportunities created since 2024-01-01, {len(files)} created-date windows; {closed} no longer open"
    if capped:
        note += f"; INCOMPLETE: {len(capped)} window(s) hit the {CAP}-row cap, split them further"
    bundle = {"agent": "claude-code:/salesforce", "prompt_version": "salesforce-2026-10",
              "pulls": [{"source_id": "salesforce", "window_from": "2024-01-01T00:00:00Z", "window_to": f"{today}T23:59:59Z",
                         "available": available, "pulled": len(seen), "noise": sum(1 for i in items if i.get("noise")), "complete": complete, "note": note}],
              "items": items,
              "source_health": [{"source_id": "salesforce", "health": "ok" if complete else "partial", "note": note}]}
    out = Path(out or db.ASSIST / "inbox" / "queue" / f"salesforce-{today}.json")
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    return out, len(seen), closed, capped


CLOSED_FROM = _CRM.get("history_start") or "2026-01-01"
CLOSED_CAP = 100             # sf_search_opportunities returns at most 100 rows and has no offset


def build_closed(con, files, out=None):
    """Closed Won / Closed Lost results from sf_search_opportunities (close-date windows) -> one ingest bundle.

    Same allowlist as the open pull (owner names never reach the bundle). Each deal is stored once by Id, so a deal
    first seen open is updated in place with its final stage and is_open=false."""
    today = date.today().isoformat()
    seen, available, capped = {}, 0, []
    for f in files:
        d = json.loads(Path(f).read_text())
        rows = d.get("opportunities") or []
        available += d.get("totalSize", len(rows))
        if d.get("totalSize", len(rows)) > len(rows) or len(rows) >= CLOSED_CAP:
            capped.append(str(f))
        for o in rows:
            if (o.get("StageName") or "").startswith("Closed"):
                seen[o["Id"]] = o
    items = []
    for oid, o in seen.items():
        p = dict(_payload(o, today), is_open=False)
        items.append({"source_id": "salesforce", "external_id": f"sf:{oid}", "kind": "opportunity", "ts": f"{p['close_date']}T00:00:00Z",
                      "subject": p.get("name"), "thread": p.get("account"), "text": _text(p), "payload": p, "pull": 0,
                      "noise": bool(TEST_ACCOUNT.search(p.get("account") or "")),
                      "url": f"{INSTANCE}/lightning/r/Opportunity/{oid}/view"})
    won = sum(1 for o in seen.values() if o.get("StageName") == "Closed Won")
    note = f"closed opportunities with close date since {CLOSED_FROM}: {won} won, {len(seen) - won} lost, {len(files)} windows"
    if capped:
        note += f"; INCOMPLETE: {len(capped)} window(s) hit the {CLOSED_CAP}-row cap, split them further"
    bundle = {"agent": "claude-code:/salesforce", "prompt_version": "salesforce-closed-2026-10",
              "pulls": [{"source_id": "salesforce", "window_from": f"{CLOSED_FROM}T00:00:00Z", "window_to": f"{today}T23:59:59Z",
                         "available": available, "pulled": len(seen), "noise": sum(1 for i in items if i.get("noise")),
                         "complete": not capped, "note": note}],
              "items": items}
    out = Path(out or db.ASSIST / "inbox" / "queue" / f"salesforce-closed-{today}.json")
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    return out, won, len(seen) - won, capped


def build_accounts(files, out=None):
    """Account lists from sf_list_accounts_by_type (detailed: the only level with the website) -> one ingest bundle of
    company fields only: name, Type, website, mail domain (companies.ACCOUNT_FIELDS). Owners, phones, addresses and the
    free-text health fields never reach the bundle (Sam, 23 Oct 2026: logos and partner types on People › Companies)."""
    today = date.today().isoformat()
    seen, capped = {}, []
    for f in files:
        d = json.loads(Path(f).read_text())
        rows = d.get("accounts") or []
        if d.get("totalSize", len(rows)) > len(rows) or len(rows) >= 500:
            capped.append(str(f))
        for a in rows:
            name = (a.get("Name") or "").strip()
            if name:
                seen[name] = {"name": name, "type": a.get("Type"), "website": a.get("Website"), "email_domain": a.get("eMail_Domain__c")}
    bundle = {"agent": "claude-code:/salesforce", "prompt_version": "salesforce-accounts-2026-10", "accounts": list(seen.values())}
    if capped:
        bundle["gaps"] = [f"Salesforce accounts: {len(capped)} list(s) hit the 500-row cap; accounts beyond it keep their initials"]
    out = Path(out or db.ASSIST / "inbox" / "queue" / f"salesforce-accounts-{today}.json")
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    return out, len(seen), capped
