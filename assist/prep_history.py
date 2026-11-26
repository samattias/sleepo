"""Everything Sam and each person in the meeting said to each other recently, for the meeting brief (prep.context).

Per person, newest first: every meeting with them in the last 90 days (an index, with the notes of the most recent ones),
mail both ways in the last 30 days (whole threads, Sam's own text above the quoted history), Teams and Slack DMs, and the
group chats and channels where they wrote. A 1:1 gets the full picture; a big meeting gets less per person, so the pack
stays readable. Something shown under one person is not repeated under the next.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import relevance as R
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from . import profile

SAM = profile.NAME   # the user, by full name or address (assist/profile.py)
DM_KINDS = ("dm", "oneOnOne")

# (meeting notes kept, chars per note, mail messages, chars per mail, chat messages, chars per chat line)
BUDGET = {"one": (6, 1500, 40, 700, 60, 350), "small": (3, 1000, 15, 450, 25, 280), "large": (2, 600, 6, 300, 10, 220)}


def _clip(t, n):
    t = re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", (t or "").strip()))
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def _own(body):
    from .replies import _own_text
    return _own_text(body or "")


def _addrs(js):
    try:
        return {(x.get("address") or "").lower() for x in json.loads(js or "[]")}
    except ValueError:
        return set()


def _ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meetings(con, matcher, before, budget, exclude, seen):
    n_notes, n_chars = budget[0], budget[1]
    rows = []
    for m in con.execute("SELECT m.*, i.url FROM meetings m LEFT JOIN items i ON i.id=m.note_item_id WHERE m.status != 'personal' "
                         "AND m.starts_at >= ? AND m.starts_at < ? ORDER BY m.starts_at DESC", (_ago(90), before)):
        att = [a for a in json.loads(m["attendees"] or "[]") if not SAM.search(a or "")]
        if any(matcher.name(a) for a in att) or matcher.text(m["title"]):
            rows.append((m, att))
    if not rows:
        return ["- no recorded meetings with them in the last 90 days"]
    # notes: the most recent meeting of any size, then the most recent small ones (where they had room to speak)
    pick = [rows[0][0]["id"]] + [m["id"] for m, att in rows if len(att) <= 3]
    notes = [i for i in dict.fromkeys(pick) if i not in exclude and i not in seen][:n_notes]
    big = budget is BUDGET["large"]
    listed = [(m, att) for m, att in rows if not big or len(att) <= 3 or m["id"] in notes]
    L = [f"{len(rows)} meeting(s) in the last 90 days, newest first" + (f" ({len(rows) - len(listed)} larger group meetings not listed)" if big else "") + ":"]
    for m, att in listed:
        size = "1:1" if len(att) <= 1 else f"{len(att) + 1} people"
        mark = " (notes above)" if m["id"] in exclude or (m["id"] in seen and m["id"] not in notes) else ""
        L.append(f"- {(m['starts_at'] or '')[:10]} · {m['title']} · {size}" + (f" · [Granola]({m['url']})" if m["url"] else "") + mark)
        if m["id"] in notes:
            body = R.meeting_notes(con, m, n_chars)
            L.append("  " + (re.sub(r"(?m)^#{1,6} ", "", body).replace("\n", "\n  ") if body else "_no notes_"))
    seen.update(notes)
    return L


def _mail(con, addrs, budget, seen):
    n_msgs, n_chars = budget[2], budget[3]
    if not addrs:
        return ["- no email address known"]
    direct, copied = [], []
    for r in con.execute("SELECT m.*, i.noise FROM mail_messages m JOIN items i ON i.id=m.item_id WHERE COALESCE(m.received_at, m.sent_at) >= ? "
                         "ORDER BY COALESCE(m.received_at, m.sent_at) DESC", (_ago(30),)):
        if r["noise"]:
            continue
        frm, rcpt = (r["from_address"] or "").lower(), _addrs(r["to_json"]) | _addrs(r["cc_json"])
        if frm in addrs or (r["folder"] == "sentitems" and rcpt & addrs):
            direct.append(r)
        elif rcpt & addrs:
            copied.append(r)
    L = []
    if not direct:
        L.append("- no email between you and them in the last 30 days")
    threads, order = {}, []
    for r in direct:
        k = r["conversation_id"] or r["graph_id"]
        if k not in threads:
            threads[k] = []
            order.append(k)
        threads[k].append(r)
    shown = skipped = 0
    for k in order:
        msgs = [r for r in threads[k] if r["item_id"] not in seen]
        if not msgs:
            L.append(f"- thread “{threads[k][0]['subject']}” (shown above)")
            continue
        if shown >= n_msgs:
            skipped += 1
            if skipped <= 10:
                L.append(f"- {(msgs[0]['received_at'] or msgs[0]['sent_at'] or '')[:10]} · “{msgs[0]['subject']}” · {len(msgs)} message(s), not expanded")
            continue
        L.append(f"- Thread “{msgs[0]['subject']}” ({len(msgs)} message(s)):")
        for r in reversed(msgs):   # oldest first inside a thread
            if shown >= n_msgs:
                break
            others = len(_addrs(r["to_json"]) | _addrs(r["cc_json"])) - 1
            who = (f"{USER.first} → them" + (f" (+{others} others)" if others > 0 else "")) if r["folder"] == "sentitems" else f"{r['from_name']} → {USER.first}"
            L.append(f"  - {(r['received_at'] or r['sent_at'] or '')[:16].replace('T', ' ')} · {who} · reply_to: {r['graph_id']}"
                     + (f" · [Outlook]({r['web_link']})" if r["web_link"] else ""))
            L.append("    > " + _clip(_own(r["body_text"]), n_chars).replace("\n", "\n    > "))
            seen.add(r["item_id"])
            shown += 1
    if skipped > 10:
        L.append(f"- and {skipped - 10} older thread(s)")
    if copied and budget is not BUDGET["large"]:
        L.append(f"- Also on {len(copied)} other mail(s) to you, from someone else (subjects only):")
        L += [f"  - {(r['received_at'] or '')[:10]} · {r['from_name']}: “{r['subject']}”" + (f" · [Outlook]({r['web_link']})" if r["web_link"] else "")
              for r in copied[:8]]
    return L


def _chat(con, matcher, budget, seen):
    n_msgs, n_chars = budget[4], budget[5]
    rows = list(con.execute("SELECT c.*, i.noise FROM chat_messages c JOIN items i ON i.id=c.item_id WHERE c.sent_at >= ? ORDER BY c.sent_at DESC", (_ago(30),)))
    convs = {}
    for r in rows:
        key = (r["source_id"], r["conversation_id"] or r["conversation_name"])
        dm = r["conversation_kind"] in DM_KINDS and matcher.text(r["conversation_name"])
        member = r["conversation_kind"] in ("group", "meeting") and matcher.text(r["conversation_name"])   # group chats are named after their members
        if dm or member or matcher.name(r["author"]):
            convs.setdefault(key, {"dm": False, "name": r["conversation_name"], "kind": r["conversation_kind"], "src": r["source_id"]})
            convs[key]["dm"] |= dm
    if not convs:
        return ["- no Teams or Slack messages with them in the last 30 days"]
    by_conv = {}
    for r in rows:
        key = (r["source_id"], r["conversation_id"] or r["conversation_name"])
        c = convs.get(key)
        if not c or r["noise"] or r["item_id"] in seen:
            continue
        # in a channel only their messages and Sam's; in a DM or group chat the whole exchange
        if c["kind"] == "channel" and not (matcher.name(r["author"]) or SAM.search(r["author"] or "")):
            continue
        by_conv.setdefault(key, []).append(r)
    order = sorted(by_conv, key=lambda k: (not convs[k]["dm"], -max(_ts(r) for r in by_conv[k])))   # DMs first, then most recent
    L, left = [], n_msgs
    for k in order:
        if left <= 0:
            L.append(f"- {convs[k]['src']} · {convs[k]['name'] or convs[k]['kind']}: {len(by_conv[k])} more message(s), not expanded")
            continue
        msgs = by_conv[k][:max(4, left // 2) if not convs[k]["dm"] else left]
        L.append(f"- {convs[k]['src'].title()} · {'DM' if convs[k]['dm'] else convs[k]['kind']} · {convs[k]['name'] or ''} ({len(by_conv[k])} message(s)):")
        for r in reversed(msgs):
            L.append(f"  - {(r['sent_at'] or '')[:16].replace('T', ' ')} · {r['author']}: {_clip(r['body_text'], n_chars)}"
                     + (f" · [open]({r['web_link']})" if r["web_link"] else ""))
            seen.add(r["item_id"])
        left -= len(msgs)
    return L


def _ts(r):
    try:
        return datetime.fromisoformat((r["sent_at"] or "").replace("Z", "")[:19]).timestamp()
    except ValueError:
        return 0


def history(con, people, extra_addresses, before_iso, exclude_meetings=()):
    """Lines for the context pack. people: rows from the people table; extra_addresses: attendees not in the people table."""
    n = len(people) + len(extra_addresses)
    budget = BUDGET["one" if n <= 1 else "small" if n <= 4 else "large"]
    seen_meetings, seen_items, L = set(), set(), []
    L.append("## Your recent communication with each person (meetings 90 days; mail, Teams, Slack 30 days; newest first)")
    L.append("This is complete for the window: every channel, both directions. Read it before saying anything is open or proposing an action.")
    for p in people:
        matcher = R.Matcher(con, [p])
        addrs = {r["alias"].lower() for r in con.execute("SELECT alias FROM people_aliases WHERE person_id=? AND alias LIKE '%@%'", (p["id"],))}
        L += ["", f"### With {p['name']}", "**Meetings**"]
        L += _meetings(con, matcher, before_iso, budget, set(exclude_meetings), seen_meetings)
        L += ["**Email**"] + _mail(con, addrs, budget, seen_items)
        L += ["**Teams / Slack**"] + _chat(con, matcher, budget, seen_items)
    for a in extra_addresses:
        L += ["", f"### With {a} (not in the people database)", "**Email**"] + _mail(con, {a.lower()}, budget, seen_items)
    L.append("")
    return L
