"""Known gaps in what the pulls could read (Sam, 28 Oct 2026: the Sources page showed all 120 gaps ever recorded, most of
them about 7 Oct problems long fixed, as one wall of red cards).

A gap is a settings row `gap:<fingerprint>` with the text, as before (ingest writes them from a bundle's `gaps`). Each one
now also has `gap_seen:<fingerprint>` with the last time a pull reported it, so the page can show what is current (reported
in the last CURRENT_DAYS days) and fold the rest. Gaps from before the stamp take the time of the newest processed bundle
that carried them (`backfill`), or stay undated (shown as older).
"""
import json
from datetime import datetime, timedelta, timezone

from . import db

CURRENT_DAYS = 3


def note(con, text, at=None):
    """Record a gap as reported now (or at `at`); writes only when something changed."""
    fp = db.fingerprint(text)
    at = at or db.now()
    if not con.execute("SELECT 1 FROM settings WHERE key=? AND value=?", ("gap:" + fp, text)).fetchone():
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("gap:" + fp, text))
    seen = con.execute("SELECT value FROM settings WHERE key=?", ("gap_seen:" + fp,)).fetchone()
    if not seen or seen[0] < at:
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("gap_seen:" + fp, at))


def clear(con, text):
    fp = db.fingerprint(text)
    con.execute("DELETE FROM settings WHERE key IN (?, ?)", ("gap:" + fp, "gap_seen:" + fp))


def listing(con, now=None):
    """Every gap with when it was last reported, newest first; `current` when within CURRENT_DAYS."""
    now = now or datetime.now(timezone.utc)
    cut = (now - timedelta(days=CURRENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen = {r["key"][9:]: r["value"] for r in con.execute("SELECT key, value FROM settings WHERE key LIKE 'gap_seen:%'")}
    out = [{"text": r["value"], "seen": seen.get(r["key"][4:])} for r in con.execute("SELECT key, value FROM settings WHERE key LIKE 'gap:%'")]
    for g in out:
        g["current"] = bool(g["seen"] and g["seen"] >= cut)
    return sorted(out, key=lambda g: g["seen"] or "", reverse=True)


def current(con, now=None):
    return [g["text"] for g in listing(con, now) if g["current"]]


def backfill(con, folder=None):
    """Date undated gaps from the processed bundles in inbox/queue/done that carried them (the file's time)."""
    folder = folder or db.ASSIST / "inbox" / "queue" / "done"
    undated = {r["key"][4:] for r in con.execute("SELECT key FROM settings WHERE key LIKE 'gap:%'")} - \
              {r["key"][9:] for r in con.execute("SELECT key FROM settings WHERE key LIKE 'gap_seen:%'")}
    found = {}
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            gaps = json.loads(f.read_text()).get("gaps") or []
        except (ValueError, OSError, AttributeError):
            continue
        at = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for g in gaps:
            fp = db.fingerprint(g)
            if fp in undated and at > found.get(fp, ""):
                found[fp] = at
    for fp, at in found.items():
        con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("gap_seen:" + fp, at))
    con.commit()
    return len(found), len(undated)
