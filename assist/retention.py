"""Retention: how long SleePO keeps personal data. RETENTION_DAYS below is the one place to change it.

The Acme org rule: derived data containing personal information is deleted within 30 days. Every purge reads
RETENTION_DAYS: full mail and Teams/Slack text, local file text, Claude Code session summaries, reply drafts and
pre-drafts, working replies, task proposals, Outlook draft records, Ask SleePO conversations and their ~/SleePO
Workspace folders, meeting screenshots and file previews. Email briefings keep 7 days (never longer than
RETENTION_DAYS) and job files a day. Raising it needs a documented exception from IT or privacy
(memory/context/assistant-soul.md).

What this module clears beyond those purges:
- one-line summaries (items.text) of mail, Teams and Slack older than the window
- mail envelopes kept for governance (sender, recipients, subject) - only if `retention_envelopes` is on

It never runs by itself. `report()` shows what would go; `apply()` blanks summaries (the row, date and link stay, so
counts and the governance index are not broken) and only runs when settings key retention_summaries_enabled = "1".
"""
from datetime import datetime, timedelta, timezone

# The retention period, in days, for everything listed above.
RETENTION_DAYS = 1000
assert RETENTION_DAYS >= 1, "RETENTION_DAYS is a number of days: to keep longer, raise it"

SOURCES = ("outlook.inbox", "outlook.sent", "teams", "slack")


def report(con):
    cut = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"cutoff": cut, "days": RETENTION_DAYS, "sources": {}}
    for s in SOURCES:
        r = con.execute("SELECT COUNT(*) AS n, SUM(CASE WHEN text IS NOT NULL AND text<>'' THEN 1 ELSE 0 END) AS t FROM items WHERE source_id=? AND ts < ?", (s, cut)).fetchone()
        out["sources"][s] = {"items_older": r["n"], "with_summary_text": r["t"] or 0}
    on = con.execute("SELECT value FROM settings WHERE key='retention_summaries_enabled'").fetchone()
    out["enabled"] = bool(on and on["value"] == "1")
    return out


def apply(con):
    rep = report(con)
    if not rep["enabled"]:
        return {"applied": False, "reason": "retention_summaries_enabled is not '1'", **rep}
    n = 0
    for s in SOURCES:
        n += con.execute("UPDATE items SET text=NULL WHERE source_id=? AND ts < ? AND text IS NOT NULL AND text<>'' "
                         "AND id NOT IN (SELECT item_id FROM fact_sources WHERE item_id IS NOT NULL)", (s, rep["cutoff"])).rowcount
    con.commit()
    return {"applied": True, "blanked": n, **rep}
