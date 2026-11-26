"""How fresh each source is: the one definition the Today widget, the Sources page, each source's page and the daily brief
all use, so they cannot disagree.

A stream (sources row, e.g. outlook.inbox) is
  off      the connector cannot be read: a current problem in assist/connections.py stopped its latest pull (labelled
           Sign-in needed, No access…, aged from its last complete pull), health broken/planned, or the note says so
  unknown  never pulled
  stale    last successful pull older than how often it is meant to update (MAX_AGE_HOURS)
  capped   pulled recently, but a search limit was hit or the pull was partial
  fresh    pulled recently and complete
A system (Outlook, SharePoint…) takes the worst state of its streams and the age of its oldest stream.
Computed at request time from sources.last_pull_at, never from a stored health that does not age.
"""
import re
from datetime import datetime, timezone

# How old each source may get before it counts as stale, by how often it is meant to update (hours). None = never stale.
# Salesforce is pulled weekly by design (settings salesforce_every_days, see api.salesforce_due): its limit follows that setting.
MAX_AGE_HOURS = {"granola": 6, "local": 6, "calendar": 30, "outlook.inbox": 30, "outlook.sent": 30, "teams": 30, "slack": 30,
                 "sharepoint": 30, "acme-kb": 24 * 8, "public-docs": 24 * 8, "roadmap": None}
DEFAULT_MAX_AGE = 30
WORST_FIRST = ["stale", "off", "capped", "unknown", "fresh"]
LABEL = {"fresh": "Up to date", "stale": "Stale", "off": "Not connected", "capped": "Capped", "unknown": "Not pulled yet"}
ISSUE_LABEL = {"signin": "Sign-in needed", "access": "No access", "app": "Not running", "unreachable": "Not answering"}   # connections.BAD kinds
# how the latest pull really ran, from pulls.agent
VIA = [(r"mail-local", "Apple Mail"), (r"mail-full|mail-envelopes", "Microsoft 365"), (r"calendar-local", "Calendar.app")]


def _age_hours(iso, now):
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (now - (t if t.tzinfo else t.replace(tzinfo=timezone.utc))).total_seconds() / 3600
    except ValueError:
        return None


def _max_age(con):
    ages = dict(MAX_AGE_HOURS)
    r = con.execute("SELECT value FROM settings WHERE key='salesforce_every_days'").fetchone()
    try:
        days = float(r["value"]) if r and r["value"] else 7
    except ValueError:
        days = 7
    ages["salesforce"] = days * 24 + 24   # one day's grace for the morning it falls due
    return ages


def streams(con, now=None):
    """One row per source stream."""
    now = now or datetime.now(timezone.utc)
    limits = _max_age(con)
    try:   # a connector that needs a new sign-in, or a local import without access (assist/connections.py)
        from . import connections
        stopped = connections.affected_sources(con, now)
    except Exception:
        stopped = {}
    out = []
    for r in con.execute("SELECT id, system, name, health, last_pull_at, note FROM sources ORDER BY sort, id"):
        age = _age_hours(r["last_pull_at"], now)
        limit = limits.get(r["id"], DEFAULT_MAX_AGE)
        health, note = (r["health"] or "").lower(), r["note"] or ""
        issue = stopped.get(r["id"])
        if issue:   # 17 Nov 2026: Teams said Up to date for 11 days while every pull failed (a failed pull moves last_pull_at)
            state, note = "off", issue["headline"]
            ok = next((a["last_ok"] for a in issue["affected"] if a["id"] == r["id"]), None)
            age = _age_hours(ok, now)   # the age of what was last read in full
        elif health in ("broken", "planned") or re.search(r"not authenticated|not connected|cannot", note, re.I):
            state = "off"
        elif age is None:
            state = "unknown"
        elif limit is not None and age > limit:
            state = "stale"
        elif health in ("capped", "partial"):
            state = "capped"
        else:
            state = "fresh"
        # the importer's own rows (it reloads the calendar file on every sync) say nothing about where the data came from
        agent = con.execute("SELECT agent FROM pulls WHERE source_id=? AND agent NOT IN ('claude-code (prototype)', 'importer') "
                            "ORDER BY finished_at DESC, id DESC LIMIT 1", (r["id"],)).fetchone()
        via = next((v for pat, v in VIA if agent and re.search(pat, agent["agent"] or "")), None)
        out.append({"id": r["id"], "system": r["system"], "name": r["name"], "last": r["last_pull_at"],
                    "age_hours": round(age, 1) if age is not None else None, "max_age_hours": limit,
                    "state": state, "label": ISSUE_LABEL.get(issue["kind"], LABEL[state]) if issue else LABEL[state], "note": note, "via": via,
                    "issue": issue["key"] if issue else None})
    return out


def systems(con, now=None):
    """One row per system (as the Sources page groups them): worst state of its streams, and the age of the oldest stream in
    that state (28 Oct 2026: SharePoint said "Stale · 20 d ago" from the roadmap workbook, which never goes stale, while its
    documents were 6 days old)."""
    by = {}
    for s in streams(con, now):
        by.setdefault(s["system"], []).append(s)
    out = {}
    for sysid, rows in by.items():
        state = min((r["state"] for r in rows), key=WORST_FIRST.index)
        worst = [r for r in rows if r["state"] == state]
        ages = [r["age_hours"] for r in worst if r["age_hours"] is not None]
        lasts = [r["last"] for r in worst if r["last"]]
        label = next((r["label"] for r in worst if r.get("issue")), LABEL[state])
        out[sysid] = {"state": state, "label": label, "issue": next((r["issue"] for r in worst if r.get("issue")), None),
                      "age_hours": max(ages) if ages else None, "last": min(lasts) if lasts else None,
                      "via": " + ".join(dict.fromkeys(r["via"] for r in rows if r["via"])) or None,
                      "streams": rows, "note": "\n".join(f"{r['name']}: {r['label']}" + (f" · {r['note']}" if r["note"] else "") for r in rows)}
    return out
