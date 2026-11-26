"""Link each message to the person who sent it (items.from_person_id), by identity only.

Uses the sender's email address (mail envelopes and full mail), then the full name, then a first name only when nobody
else in the company has it (relevance.resolve). Fills gaps only; never overwrites an existing link. Safe to re-run.
"""
import json


def up(con):
    from .. import relevance as R
    cache = {}
    rows = con.execute("SELECT i.id, i.from_name, i.payload, m.from_address FROM items i LEFT JOIN mail_messages m ON m.item_id=i.id "
                       "WHERE i.from_person_id IS NULL AND i.source_id IN ('outlook.inbox','outlook.sent','teams','slack')").fetchall()
    for r in rows:
        keys = []
        if r["from_address"]:
            keys.append(r["from_address"])
        try:
            p = json.loads(r["payload"] or "{}")
            if isinstance(p, dict) and p.get("sender"):
                keys.append(p["sender"])
        except ValueError:
            pass
        if r["from_name"]:
            keys.append(r["from_name"])
        pid = None
        for k in keys:
            k = (k or "").strip().lower()
            if not k:
                continue
            if k not in cache:
                q = R.resolve(con, k)
                cache[k] = q["id"] if q else None
            pid = cache[k]
            if pid:
                break
        if pid:
            con.execute("UPDATE items SET from_person_id=? WHERE id=?", (pid, r["id"]))
