"""Which emails belong to one thread: one rule for the whole app (22 Oct 2026, from the codebase review: five copies with
different windows and checks).

Two emails are in the same thread when they share a conversation id, or when their subjects are the same once reply and
forward prefixes are stripped (key()). Apple Mail and Microsoft 365 give the same thread different ids, so the subject rule
is what joins them. With people=True the subject rule also needs someone in common besides Sam, so two unrelated
"Re: Update" emails are not joined (task links, Needs response); without it a forward to new people stays in the thread
(briefings, the action pack's thread history).
"""
import json
import re

from . import db

PREFIX = re.compile(r"^\s*(re|fw|fwd|aw|wg|tr|antw|sv|vs|rif)\s*(\[\d+\])?\s*:\s*", re.I)


def key(subject):
    """The subject without reply/forward prefixes, lower case; None when too short to identify a thread."""
    s = subject or ""
    while True:
        t = PREFIX.sub("", s)
        if t == s:
            break
        s = t
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s if len(s) >= 8 else None


def people(r):
    """Everyone on a message (from, To, Cc) except Sam, lower case."""
    out = {(r["from_address"] or "").lower()}
    for x in json.loads(r["to_json"] or "[]") + json.loads(r["cc_json"] or "[]"):
        out.add((x.get("address") or "").lower())
    return {a for a in out if a and not db.ME_ADDRESS.search(a)}


def same(a, b, with_people=True):
    """Are mail rows a and b in one thread?"""
    if a["conversation_id"] and a["conversation_id"] == b["conversation_id"]:
        return True
    k = key(a["subject"])
    if not k or key(b["subject"]) != k:
        return False
    return not with_people or bool(people(a) & people(b))


def rows(con, item_id, days=120, with_people=True):
    """The mail_messages rows of an email's thread within `days` of it (None: any time), oldest first, the email included.
    [] when it is not an email."""
    m = con.execute("SELECT * FROM mail_messages WHERE item_id=?", (item_id,)).fetchone()
    if not m:
        return []
    k = key(m["subject"])
    q = "SELECT * FROM mail_messages WHERE (item_id=? OR (conversation_id IS NOT NULL AND conversation_id=?)" + \
        (" OR instr(lower(subject), ?) > 0)" if k else ")")
    args = [item_id, m["conversation_id"] or "\x00"] + ([k] if k else [])
    if days is not None:
        ts = m["received_at"] or m["sent_at"]
        if ts:
            q += " AND COALESCE(received_at, sent_at) BETWEEN datetime(?, ?) AND datetime(?, ?)"
            args += [ts, f"-{int(days)} days", ts, f"+{int(days)} days"]
    out = [r for r in con.execute(q, args) if r["item_id"] == item_id or same(m, r, with_people)]
    if not any(r["item_id"] == item_id for r in out):
        out.append(m)
    return sorted(out, key=lambda r: r["received_at"] or r["sent_at"] or "")


def ids(con, item_id, days=120, with_people=True):
    """The item ids of an email's thread (sorted), or [item_id] for anything that is not an email."""
    got = [r["item_id"] for r in rows(con, item_id, days, with_people)]
    return sorted(got) if got else [item_id]
