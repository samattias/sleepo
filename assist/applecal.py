"""Calendar from Calendar.app's local store: the live path for Sam's Exchange calendar (no Claude, read only).

Calendar.app keeps the Exchange calendar on disk in one SQLite file and syncs it within minutes, so a meeting moved in
Outlook is moved here too, and it records Sam's own reply (accepted, tentative, declined, not answered), which the
Microsoft 365 connector does not return. Reading it needs Full Disk Access for the process, the same grant Apple Mail's
import uses (assist/applemail.py). We never write to it.

Events come out in the inbox/calendar/events.json schema with the ids the connector uses (Exchange item ids are rebuilt
from the same database GUID, item counter and occurrence date), so both paths update one record per meeting, and links to
recordings and meeting briefs survive. importer.merge_calendar() applies them as a pull that is authoritative for its
window: an event stored in the window that the calendar no longer has was moved out of it, deleted or declined.
"""
import base64
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

PATHS = ("~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb", "~/Library/Calendars/Calendar.sqlitedb")
EPOCH = 978307200                      # Core Data dates are seconds since 2001-01-01 UTC
PAST_DAYS, AHEAD_DAYS = 14, 60         # the window each sync owns
EXCHANGE = 1                           # Store.type of an Exchange account
STALE_HOURS = 6                        # Calendar.app has not synced the account for this long: say so, own nothing

# Sam's reply in Participant.status (Calendar's own codes, not EventKit's enum): observed on this Mac against Outlook.
RESPONSE = {1: "accepted", 2: "declined", 3: "tentative", 7: "none"}

# Connector-form Exchange ids (Graph REST: '/' written '-', '+' written '_'): a fixed head, then the item's key (database GUID, 16 bytes, and
# item counter, 6 bytes) and 0000; an occurrence of a series carries its original date as .NET ticks and ends 0x10.
_SINGLE = bytes.fromhex("0009002e00000000001d840311aa6611cd9bc800aa002fc45a0d00")
_OCC_HEAD, _OCC_MID = bytes.fromhex("000901390008"), bytes.fromhex("2e000000001d840311aa6611cd9bc800aa002fc45a0d00")
_CAL_OCC = bytes.fromhex("01510008")                  # Calendar.app's id of a changed occurrence: ...0151 0008 <ticks>...
TEAMS_BLOCK = re.compile(r"_{8,}|Microsoft Teams (?:meeting|Need help)|Join:\s*https?://|Join the meeting now")
JOIN_RX = re.compile(r"https://(?:teams\.microsoft\.com/(?:l/meetup-join|meet)/|[\w.-]*zoom\.us/j/|meet\.google\.com/)[^\s<>\"')\]]+")


class NoAccess(Exception):
    pass


def db_path():
    for p in PATHS:
        p = os.path.expanduser(p)
        try:
            os.listdir(os.path.dirname(p))
        except PermissionError:
            raise NoAccess("no Full Disk Access to Calendar.app's store (System Settings › Privacy & Security › Full Disk Access)")
        except FileNotFoundError:
            continue
        if os.path.exists(p):
            return p
    raise NoAccess("Calendar.app has no calendar store on this Mac")


def connect():
    c = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------------------------------------------- ids
def _b64(s):
    s = (s or "").replace("-", "/").replace("_", "+")
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        return b""


def _ticks(d):
    return (d - date(1, 1, 1)).days * 864_000_000_000


def _ticks_date(b):
    return date(1, 1, 1) + timedelta(microseconds=int.from_bytes(b, "big") // 10)


def key_of(ext_id):
    """(item key hex, original date or None) of an Exchange id in either form: the connector's or Calendar.app's."""
    b = _b64(ext_id)
    if len(b) < 30:
        return None, None
    if b.endswith(b"\x00\x00\x10"):                     # an occurrence: the series' key and the original date
        if b.startswith(_OCC_HEAD):
            t = b[6:14]
        else:
            i = b.find(_CAL_OCC)
            t = b[i + 4:i + 12] if i >= 0 else None
        return b[-25:-3].hex(), (_ticks_date(t) if t else None)
    if b.endswith(b"\x00\x00"):
        return b[-24:-2].hex(), None
    return None, None


def connector_id(key, occ_date=None):
    """The id the Microsoft 365 connector gives this item (or this occurrence of a series)."""
    k = bytes.fromhex(key) + b"\x00\x00"
    raw = _SINGLE + k if occ_date is None else _OCC_HEAD + _ticks(occ_date).to_bytes(8, "big") + _OCC_MID + k + b"\x10"
    return base64.b64encode(raw).decode().replace("/", "-").replace("+", "_")


def web_link(eid):
    from urllib.parse import quote
    return "https://outlook.office365.com/owa/?itemid=" + quote(eid.replace("-", "/").replace("_", "+"), safe="") + "&exvsurl=1&path=/calendar/item"


# ---------------------------------------------------------------------------------------------------- reading
def _iso(secs):
    return datetime.fromtimestamp(secs + EPOCH, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def calendar_row(c):
    """The Exchange account's main calendar (the one the connector reads): its biggest calendar that is not holidays or birthdays."""
    rows = c.execute("SELECT cal.ROWID, cal.title, s.ROWID AS store, s.last_sync_end, cal.last_sync_end AS cal_sync, cal.self_identity_email, "
                     "(SELECT COUNT(*) FROM CalendarItem WHERE calendar_id=cal.ROWID) AS n FROM Calendar cal JOIN Store s ON s.ROWID=cal.store_id "
                     "WHERE s.type=? AND COALESCE(s.disabled, 0)=0 ORDER BY n DESC", (EXCHANGE,)).fetchall()
    rows = [r for r in rows if not re.search(r"holiday|birthday", r["title"] or "", re.I)]
    if not rows:
        raise NoAccess("Calendar.app has no Exchange calendar (add the Exchange account in System Settings › Internet Accounts with Calendars on)")
    return rows[0]


def _people(c, item_ids):
    out = {}
    q = ",".join("?" * len(item_ids))
    for p in c.execute(f"SELECT owner_id, ROWID, email, is_self, status FROM Participant WHERE owner_id IN ({q}) ORDER BY ROWID", list(item_ids)):
        out.setdefault(p["owner_id"], []).append(p)
    return out


def _summary(text):
    """The invite text as the connector's preview carries it, up to the Teams join block (never the passcode or dial-ins)."""
    s = TEAMS_BLOCK.split(text or "")[0]
    s = re.sub(r"(?im)^.*(passcode|meeting id|dial[- ]in|conference id).*$", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()[:200]


def _me(c, cal):
    return (cal["self_identity_email"] or (c.execute("SELECT email FROM Participant WHERE is_self=1 AND email LIKE '%@%' "
                                                     "GROUP BY email ORDER BY COUNT(*) DESC LIMIT 1").fetchone() or [""])[0] or "")


def read(c, cal, since, until):
    """Occurrences starting in [since, until) of the Exchange calendar, as events.json events. Each carries `calkey` (this
    item, or its series and original date) and `series`, which stay in events.json so the next sync finds it again after a
    move; `_key`, `_series` and `_date` are how a connector-form id is rebuilt (assign_ids)."""
    lo, hi = since.timestamp() - EPOCH, until.timestamp() - EPOCH
    # one row per day for a multi-day event: the first day has no occurrence_start_date, the others carry the real start
    occ = c.execute("SELECT o.event_id, o.occurrence_date, o.occurrence_end_date, ci.* FROM OccurrenceCache o "
                    "JOIN CalendarItem ci ON ci.ROWID=o.event_id WHERE o.calendar_id=? AND o.occurrence_date >= ? AND o.occurrence_date < ? "
                    "AND o.occurrence_start_date IS NULL AND COALESCE(ci.hidden, 0)=0 ORDER BY o.occurrence_date", (cal["ROWID"], lo, hi)).fetchall()
    masters = {r["orig_item_id"] for r in occ if r["orig_item_id"]}
    master_ext = {r["ROWID"]: r["external_id"] for r in c.execute(
        f"SELECT ROWID, external_id FROM CalendarItem WHERE ROWID IN ({','.join('?' * len(masters))})", list(masters))} if masters else {}
    people = _people(c, {r["event_id"] for r in occ} | masters) if occ else {}
    locs = {r["ROWID"]: r["title"] for r in c.execute(
        "SELECT ROWID, title FROM Location WHERE ROWID IN (SELECT location_id FROM CalendarItem WHERE calendar_id=?)", (cal["ROWID"],))}
    me = _me(c, cal)
    out, seen = [], set()
    for r in occ:
        start, end = r["occurrence_date"], r["occurrence_end_date"] or r["end_date"]
        if (r["event_id"], start) in seen:
            continue
        seen.add((r["event_id"], start))
        if r["all_day"] and end and int(end) % 60 == 59:          # all-day ends 23:59:59; the connector says next midnight
            end += 1
        if r["orig_item_id"]:                                      # a changed occurrence: the series' key and its original date
            key, d = key_of(r["external_id"])
            if not d and r["orig_date"] is not None:
                d = datetime.fromtimestamp(r["orig_date"] + EPOCH, timezone.utc).date()
            series = key_of(master_ext.get(r["orig_item_id"]))[0] or key
        elif r["has_recurrences"]:                                 # a plain occurrence of a series
            series = key = key_of(r["external_id"])[0]
            d = datetime.fromtimestamp(start + EPOCH, timezone.utc).date()
        else:
            series, (key, d) = None, (key_of(r["external_id"])[0], None)
        ps = people.get(r["event_id"]) or people.get(r["orig_item_id"]) or []
        org = next((p for p in ps if p["ROWID"] == r["organizer_id"]), None)
        selfp = next((p for p in ps if p["ROWID"] == r["self_attendee_id"]), None) or next((p for p in ps if p["is_self"]), None)
        org_email = (org["email"] if org else "") or ""
        is_org = not org or bool(org["is_self"]) or (bool(me) and org_email.lower() == me.lower())
        emails = []
        for p in ps:
            e = p["email"] or ""
            if e and e.lower() not in {x.lower() for x in emails} and not (is_org and p["ROWID"] == r["organizer_id"]):
                emails.append(e)
        response = "organizer" if is_org else RESPONSE.get(selfp["status"] if selfp else None, "none")
        show = {1: "free", 2: "tentative", 3: "oof"}.get(r["availability"], "busy")
        if response in ("tentative", "none") and show == "busy":
            show = "tentative"                                     # how Outlook shows a tentative or unanswered invite
        desc = r["description"] or ""
        join = r["conference_url"] or (JOIN_RX.search(desc).group(0) if JOIN_RX.search(desc) else "")
        base = series if d else key
        eid = connector_id(base, d) if base else f"calapp-{r['UUID']}-{int(start)}"
        out.append({"id": eid, "subject": r["summary"] or "", "start": _iso(start), "start_tz": "UTC", "end": _iso(end),
                    "organizer": (me or org_email) if is_org else org_email, "attendees": emails, "location": locs.get(r["location_id"]) or "",
                    "isCancelled": r["status"] == 3, "isOrganizer": is_org, "isAllDay": bool(r["all_day"]), "showAs": show, "response": response,
                    "webLink": web_link(eid), "summary": _summary(desc), "join_url": join, "source": "calendar.app",
                    "calkey": f"{base}@{d.isoformat()}" if d else (base or eid), "series": series,
                    "_key": key, "_series": series, "_date": d})
    return out


# ---------------------------------------------------------------------------------------------------- matching to stored ids
def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def assign_ids(events, stored):
    """Give each Calendar.app event the id its meeting already has in events.json, so recordings, briefs and links stay on it:
    the event this sync matched last time (calkey, which survives a move), else the same rebuilt id, else the series' id
    under the item counter the connector uses for it (some series differ), else the same subject at the same start (a few
    items carry another counter), else an event removed earlier coming back; otherwise the rebuilt id is new. Returns how
    many matched each way."""
    live = [e for e in stored if not e.get("removed")]
    by_id = {e["id"]: e for e in stored}
    by_calkey, gone_calkey, by_key, by_slot = {}, {}, {}, {}
    alias = {}
    for e in stored:
        if e.get("calkey"):
            (gone_calkey if e.get("removed") else by_calkey)[e["calkey"]] = e["id"]
        k, d = key_of(e["id"])
        if e.get("series") and k and d and k != e["series"]:
            alias.setdefault(e["series"], k)
    for e in live:
        k, d = key_of(e["id"])
        if k:
            by_key[(k, d)] = e["id"]
        if not e.get("isCancelled"):
            by_slot.setdefault((_norm(e.get("subject")), (e.get("start") or "")[:16]), []).append(e["id"])
    for ev in events:                                      # a series the connector names after another counter
        if ev["_series"] and ev["_date"] and ev["_series"] not in alias and ev["calkey"] not in by_calkey and ev["id"] not in by_id:
            for sid in by_slot.get((_norm(ev["subject"]), ev["start"][:16]), []):
                k, d = key_of(sid)
                if k and d and k != ev["_series"]:
                    alias[ev["_series"]] = k
                    break
    stats = {"remembered": 0, "same id": 0, "series alias": 0, "same slot": 0, "returned": 0, "new": 0}
    taken = set()

    def pick(ev):
        if by_calkey.get(ev["calkey"]) not in (None, *taken):
            return by_calkey[ev["calkey"]], "remembered"
        if ev["id"] in by_id and ev["id"] not in taken:
            return ev["id"], "same id"
        if ev["_series"] in alias and ev["_date"]:
            k, d = alias[ev["_series"]], ev["_date"]
            sid = by_key.get((k, d)) or connector_id(k, d)
            if sid not in taken:
                return sid, "series alias"
        free = [s for s in by_slot.get((_norm(ev["subject"]), ev["start"][:16]), []) if s not in taken]
        if free:
            return free[0], "same slot"
        if gone_calkey.get(ev["calkey"]) not in (None, *taken):
            return gone_calkey[ev["calkey"]], "returned"
        return ev["id"], "new"

    for ev in events:
        ev["id"], how = pick(ev)
        ev["_how"] = how
        taken.add(ev["id"])
        ev["webLink"] = web_link(ev["id"]) if not ev["id"].startswith("calapp-") else ""
        stats[how] += 1
    return stats


def clean(ev):
    return {k: v for k, v in ev.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------------------------------- sync
class Stale(Exception):
    pass


def sync(con, log=print, dry_run=False):
    """Read the Exchange calendar from Calendar.app, give each event its stored id, and merge it into events.json as a pull
    that owns its window (importer.merge_calendar): moved meetings move, removed and declined ones drop out, and Sam's
    reply is recorded. Records the pull in the database; the importer (sync-granola) loads events.json into it."""
    import json
    from . import db, importer
    now = datetime.now(timezone.utc)
    c = connect()
    try:
        cal = calendar_row(c)
        synced = cal["last_sync_end"] or cal["cal_sync"]
        if synced and now.timestamp() - (synced + EPOCH) > STALE_HOURS * 3600:
            raise Stale(f"Calendar.app last synced the Exchange calendar {_iso(synced)[:16].replace('T', ' ')} UTC "
                        f"(is the account signed in and Calendar allowed online?)")
        since = (now - timedelta(days=PAST_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
        until = (now + timedelta(days=AHEAD_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
        events = read(c, cal, since, until)
    finally:
        c.close()
    ev_path = importer.ASSIST / "inbox" / "calendar" / "events.json"
    stored = json.loads(ev_path.read_text()).get("events", []) if ev_path.exists() else []
    stats = assign_ids(events, stored)
    window = {"afterDateTime": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "beforeDateTime": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "totalResultCount": len(events), "events_fetched": len(events), "source": "calendar.app"}
    res = importer.merge_calendar({"window": window, "events": [clean(e) for e in events]}, record_window=False, dry_run=dry_run)
    replies = {}
    for e in events:
        if e["response"] in ("tentative", "none") and e["start"] >= now.strftime("%Y-%m-%dT%H:%M") and not e["isCancelled"]:
            replies[e["response"]] = replies.get(e["response"], 0) + 1
    line = (f"calendar.app: {len(events)} events {since:%d %b} – {until:%d %b} · {res['added']} new · {res['moved']} moved · "
            f"{res['removed']} removed · {res['changed']} changed · upcoming not answered {replies.get('none', 0)}, tentative {replies.get('tentative', 0)}"
            f" · last synced {_iso(synced)[11:16] if synced else '?'} UTC")
    log(line + (" (dry run, nothing written)" if dry_run else ""))
    log("  ids: " + ", ".join(f"{k} {v}" for k, v in stats.items() if v))
    for m in res["moves"]:
        log(f"  moved: {m}")
    if dry_run:
        for e in events:
            if e["_how"] != "same id":
                log(f"  {e['_how']}: {e['start'][:16]} {e['subject'][:50]!r}")
    if not dry_run:
        pid = db.start_pull(con, "calendar", "assist calendar-local", window["afterDateTime"], window["beforeDateTime"], note=line)
        db.finish_pull(con, pid, available=len(events), pulled=len(events), complete=1)
        con.commit()
    return res
