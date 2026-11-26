"""Calendar sync: Calendar.app's local store (assist/applecal.py) and the merge into events.json (importer.merge_calendar).
A moved meeting moves (and leaves its old day), a meeting no longer on the calendar is marked removed, Sam's reply is read
(tentative, not answered), multi-day events come once, and ids match the connector's so links survive.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import base64
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import applecal, db, importer, views

GUID = bytes(range(16))
EPOCH = applecal.EPOCH


def counter(n):
    return n.to_bytes(6, "big")


def cal_single(n):
    """A Calendar.app (EWS) id of a single item: mailbox prefix, folder key, item key, 0000."""
    return base64.b64encode(b"\x00\x03\x24\x00" + b"mbx" * 10 + b"\x00\x46\x00\x00" + GUID + counter(1) + b"\x00\x00" + GUID + counter(n) + b"\x00\x00").decode()


def cal_exception(series, d):
    ticks = applecal._ticks(d).to_bytes(8, "big")
    return base64.b64encode(b"\x00\x03\x24\x00" + b"mbx" * 10 + b"\x01\x51\x00\x08" + ticks + b"\x46\x00\x00" + GUID + counter(1) + b"\x00\x00"
                            + GUID + counter(series) + b"\x00\x00\x10").decode()


def key(n):
    return (GUID + counter(n)).hex()


def secs(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() - EPOCH


class Ids(unittest.TestCase):
    def test_round_trip_both_forms(self):
        k = key(0x0123)
        self.assertEqual(applecal.key_of(cal_single(0x0123)), (k, None))
        single = applecal.connector_id(k)
        self.assertEqual(applecal.key_of(single), (k, None))
        occ = applecal.connector_id(k, date(2026, 10, 20))
        self.assertEqual(applecal.key_of(occ), (k, date(2026, 10, 20)))
        self.assertEqual(applecal.key_of(cal_exception(0x0123, date(2026, 10, 15))), (k, date(2026, 10, 15)))
        self.assertNotIn("/", occ + single)    # Graph form: '/' written '-', '+' written '_'
        self.assertNotIn("+", occ + single)

    def test_web_link_uses_standard_base64(self):
        eid = applecal.connector_id(key(0x3fffff))
        self.assertIn("itemid=", applecal.web_link(eid))
        self.assertNotIn("-", applecal.web_link(eid).split("itemid=")[1].split("&")[0])


class FakeStore:
    """The few Calendar.app tables the reader uses."""

    def __init__(self, path):
        self.c = c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        c.executescript("""
            CREATE TABLE Store (ROWID INTEGER PRIMARY KEY, name TEXT, type INTEGER, disabled INTEGER, last_sync_end REAL);
            CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, store_id INTEGER, title TEXT, last_sync_end REAL, self_identity_email TEXT);
            CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY KEY, summary TEXT, location_id INTEGER, description TEXT, start_date REAL,
              end_date REAL, all_day INTEGER, calendar_id INTEGER, orig_item_id INTEGER, orig_date REAL, organizer_id INTEGER,
              self_attendee_id INTEGER, status INTEGER, availability INTEGER, external_id TEXT, hidden INTEGER, has_recurrences INTEGER,
              UUID TEXT, conference_url TEXT);
            CREATE TABLE Participant (ROWID INTEGER PRIMARY KEY, owner_id INTEGER, email TEXT, is_self INTEGER, status INTEGER);
            CREATE TABLE OccurrenceCache (day REAL, event_id INTEGER, calendar_id INTEGER, occurrence_date REAL, occurrence_start_date REAL,
              occurrence_end_date REAL);
            CREATE TABLE Location (ROWID INTEGER PRIMARY KEY, title TEXT);
            INSERT INTO Store VALUES (1, 'Exchange', 1, 0, NULL), (2, 'Subscribed', 4, 0, NULL);
            INSERT INTO Calendar VALUES (5, 1, 'Calendar', NULL, NULL), (6, 1, 'United Kingdom holidays', NULL, NULL), (7, 2, 'UK Holidays', NULL, NULL);
        """)
        self.n = 0

    def synced(self, when):
        self.c.execute("UPDATE Store SET last_sync_end=? WHERE ROWID=1", (when.timestamp() - EPOCH,))

    def event(self, summary, start, end, ext, me=1, other="pat.lee@acme.example", organizer_me=False, all_day=0, recurs=0, exc_of=0,
              orig=None, availability=0, desc="", occurrences=None, status=0):
        """me: Sam's Participant.status (1 accepted, 2 declined, 3 tentative, 7 not answered); other=None: no invitees."""
        self.n += 1
        rid = self.n
        org = sam = 0
        if other is not None:
            sam = self.c.execute("INSERT INTO Participant (owner_id, email, is_self, status) VALUES (?,?,1,?)", (rid, "Sam.doe@acme.example", me)).lastrowid
            o = self.c.execute("INSERT INTO Participant (owner_id, email, is_self, status) VALUES (?,?,0,1)", (rid, other)).lastrowid
            org = sam if organizer_me else o
        self.c.execute("INSERT INTO CalendarItem VALUES (?,?,NULL,?,?,?,?,5,?,?,?,?,?,?,?,0,?,?,NULL)",
                       (rid, summary, desc, secs(start), secs(end), all_day, exc_of, secs(orig) if orig else None, org, sam, status,
                        availability, ext, recurs, f"U{rid}"))
        for s, e in occurrences or [(start, end)]:
            self.c.execute("INSERT INTO OccurrenceCache VALUES (?,?,5,?,NULL,?)", (secs(s[:10] + "T00:00:00"), rid, secs(s), secs(e)))
        return rid

    def continuation(self, rid, day, start, end):
        """A multi-day event's later days: one cache row per day carrying the real start."""
        self.c.execute("INSERT INTO OccurrenceCache VALUES (?,?,5,?,?,?)", (secs(day), rid, secs(day), secs(start), secs(end)))


class Reader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FakeStore(Path(self.tmp.name) / "Calendar.sqlitedb")
        self.since, self.until = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 30, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        c = self.store.c
        return {e["subject"]: e for e in applecal.read(c, applecal.calendar_row(c), self.since, self.until)}

    def test_replies_and_show_as(self):
        s = self.store
        s.event("Accepted", "2026-10-20T14:00:00", "2026-10-20T15:00:00", cal_single(1), me=1)
        s.event("Unanswered", "2026-10-20T15:00:00", "2026-10-20T15:45:00", cal_single(2), me=7, availability=2)
        s.event("Maybe", "2026-10-21T15:00:00", "2026-10-21T15:30:00", cal_single(3), me=3, availability=0)
        s.event("Mine", "2026-10-22T09:00:00", "2026-10-22T09:30:00", cal_single(4), organizer_me=True)
        s.event("Block", "2026-10-22T10:00:00", "2026-10-22T11:00:00", cal_single(5), other=None)
        s.event("Cancelled", "2026-10-23T10:00:00", "2026-10-23T11:00:00", cal_single(6), status=3)
        ev = self.read()
        self.assertEqual((ev["Accepted"]["response"], ev["Accepted"]["showAs"]), ("accepted", "busy"))
        self.assertEqual((ev["Unanswered"]["response"], ev["Unanswered"]["showAs"]), ("none", "tentative"))
        self.assertEqual((ev["Maybe"]["response"], ev["Maybe"]["showAs"]), ("tentative", "tentative"))   # Outlook hatches it
        self.assertEqual(ev["Mine"]["response"], "organizer")
        self.assertTrue(ev["Mine"]["isOrganizer"])
        self.assertEqual(ev["Mine"]["attendees"], ["pat.lee@acme.example"])
        self.assertEqual(ev["Block"]["response"], "organizer")
        self.assertTrue(ev["Cancelled"]["isCancelled"])
        self.assertEqual(ev["Accepted"]["id"], applecal.connector_id(key(1)))
        self.assertEqual(ev["Accepted"]["organizer"], "pat.lee@acme.example")

    def test_multi_day_event_comes_once_and_ends_at_midnight(self):
        s = self.store
        rid = s.event("Lisbon", "2026-11-01T00:00:00", "2026-11-06T23:59:59", cal_single(7), other=None, all_day=1)
        for d in ("2026-11-02", "2026-11-03"):
            s.continuation(rid, d + "T00:00:00", "2026-11-01T00:00:00", "2026-11-06T23:59:59")
        events = applecal.read(s.c, applecal.calendar_row(s.c), self.since, self.until)
        self.assertEqual([e["subject"] for e in events], ["Lisbon"])
        self.assertEqual((events[0]["start"], events[0]["end"], events[0]["isAllDay"]), ("2026-11-01T00:00:00", "2026-11-07T00:00:00", True))

    def test_series_occurrences_and_a_moved_one(self):
        s = self.store
        master = s.event("Weekly", "2026-10-07T14:00:00", "2026-10-07T14:30:00", cal_single(9), recurs=1,
                         occurrences=[("2026-10-07T14:00:00", "2026-10-07T14:30:00"), ("2026-10-14T14:00:00", "2026-10-14T14:30:00")])
        # the 21 Oct occurrence moved to the 22nd: an exception row, named after the series and its original date
        s.event("Weekly", "2026-10-22T09:00:00", "2026-10-22T09:30:00", cal_exception(9, date(2026, 10, 21)), exc_of=master, orig="2026-10-21T14:00:00")
        events = sorted(applecal.read(s.c, applecal.calendar_row(s.c), self.since, self.until), key=lambda e: e["start"])
        self.assertEqual([e["id"] for e in events], [applecal.connector_id(key(9), date(2026, 10, d)) for d in (7, 14, 21)])
        self.assertEqual(events[-1]["start"], "2026-10-22T09:00:00")
        self.assertEqual(events[-1]["calkey"], f"{key(9)}@2026-10-21")

    def test_invite_text_without_passcodes(self):
        self.store.event("Call", "2026-10-20T14:00:00", "2026-10-20T15:00:00", cal_single(10),
                         desc="Agenda: pricing\n\n________________\nMicrosoft Teams meeting\nJoin: https://teams.microsoft.com/meet/123?p=abc\nPasscode: xyz")
        ev = self.read()["Call"]
        self.assertEqual(ev["summary"], "Agenda: pricing")
        self.assertEqual(ev["join_url"], "https://teams.microsoft.com/meet/123?p=abc")

    def test_main_calendar_skips_holidays(self):
        self.assertEqual(applecal.calendar_row(self.store.c)["title"], "Calendar")


def stored(eid, subject, start, minutes=30, **kw):
    st = datetime.fromisoformat(start)
    return {"id": eid, "subject": subject, "start": start, "end": (st + timedelta(minutes=minutes)).isoformat(), "start_tz": "UTC",
            "showAs": "busy", "isCancelled": False, **kw}


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.json"
        self.path.write_text(json.dumps({"events": [
            stored("A", "QBR", "2026-10-19T14:00:00"),
            stored("B", "Sync", "2026-10-15T14:00:00"),
            stored("C", "Old", "2026-09-01T10:00:00"),
            stored("D", "Two weeks", "2026-10-27T23:00:00", minutes=120),   # ends after the window
        ], "windows": []}))

    def tearDown(self):
        self.tmp.cleanup()

    def events(self):
        return {e["id"]: e for e in json.loads(self.path.read_text())["events"]}

    def pull(self, events, complete=True):
        w = {"afterDateTime": "2026-10-14T00:00:00Z", "beforeDateTime": "2026-10-28T00:00:00Z", "totalResultCount": len(events),
             "events_fetched": len(events) if complete else len(events) - 1}
        return importer.merge_calendar({"window": w, "events": events}, self.path)

    def test_moved_meeting_moves_and_missing_one_is_removed(self):
        r = self.pull([stored("A", "QBR", "2026-10-20T14:00:00")])
        ev = self.events()
        self.assertEqual(ev["A"]["start"], "2026-10-20T14:00:00")
        self.assertEqual((r["moved"], r["removed"]), (1, 1))
        self.assertTrue(ev["B"]["isCancelled"])
        self.assertTrue(ev["B"]["removed"])
        self.assertFalse(ev["C"]["isCancelled"])     # outside the window: not this pull's to judge
        self.assertFalse(ev["D"]["isCancelled"])     # ends after the window: the connector would not return it

    def test_incomplete_pull_removes_nothing(self):
        self.pull([stored("A", "QBR", "2026-10-20T14:00:00")], complete=False)
        self.assertFalse(self.events()["B"]["isCancelled"])

    def test_removed_meeting_comes_back(self):
        self.pull([stored("A", "QBR", "2026-10-20T14:00:00")])
        self.pull([stored("A", "QBR", "2026-10-20T14:00:00"), stored("B", "Sync", "2026-10-16T14:00:00")])
        b = self.events()["B"]
        self.assertFalse(b["isCancelled"])
        self.assertNotIn("removed", b)

    def test_connector_pull_keeps_join_link_and_drops_a_stale_reply(self):
        self.pull([stored("A", "QBR", "2026-10-19T14:00:00", response="none", showAs="tentative", join_url="https://teams.microsoft.com/meet/1")])
        self.pull([stored("A", "QBR", "2026-10-19T14:00:00", showAs="busy")])   # Sam accepted; the connector has no reply field
        a = self.events()["A"]
        self.assertEqual(a["join_url"], "https://teams.microsoft.com/meet/1")
        self.assertNotIn("response", a)

    def test_unchanged_local_pull_does_not_rewrite_the_file(self):
        self.pull([stored("A", "QBR", "2026-10-19T14:00:00"), stored("B", "Sync", "2026-10-15T14:00:00")])
        before = self.path.stat().st_mtime_ns
        w = {"afterDateTime": "2026-10-14T00:00:00Z", "beforeDateTime": "2026-10-28T00:00:00Z", "totalResultCount": 2, "events_fetched": 2}
        r = importer.merge_calendar({"window": w, "events": [stored("A", "QBR", "2026-10-19T14:00:00"), stored("B", "Sync", "2026-10-15T14:00:00")]},
                                    self.path, record_window=False)
        self.assertEqual(r["changed"], 0)
        self.assertEqual(self.path.stat().st_mtime_ns, before)


def local(subject, start, k, d=None, series=None):
    ev = {"id": applecal.connector_id(series or k, d), "subject": subject, "start": start, "_key": k, "_series": series, "_date": d,
          "calkey": f"{series or k}@{d.isoformat()}" if d else k, "series": series}
    return ev


class AssignIds(unittest.TestCase):
    def test_remembered_event_keeps_its_id_after_a_move(self):
        st = [stored("X1", "Lisbon", "2026-11-01T00:00:00", calkey=key(5))]   # matched by time once, id differs from the rebuilt one
        ev = local("Lisbon", "2026-11-02T00:00:00", key(5))
        stats = applecal.assign_ids([ev], st)
        self.assertEqual((ev["id"], stats["remembered"]), ("X1", 1))

    def test_series_named_after_another_counter(self):
        connector_key = key(0x99)
        st = [stored(applecal.connector_id(connector_key, date(2026, 10, 20)), "CFT", "2026-10-20T15:00:00")]
        a = local("CFT", "2026-10-20T15:00:00", key(0x11), date(2026, 10, 20), series=key(0x11))
        b = local("CFT", "2026-11-10T16:00:00", key(0x11), date(2026, 11, 10), series=key(0x11))
        stats = applecal.assign_ids([a, b], st)
        self.assertEqual(a["id"], st[0]["id"])
        self.assertEqual(b["id"], applecal.connector_id(connector_key, date(2026, 11, 10)))   # the id the connector gives it
        self.assertEqual(stats["series alias"], 2)

    def test_same_subject_and_time_then_new(self):
        st = [stored("Y", "Dinner", "2026-11-02T09:00:00")]
        a, b = local("Dinner", "2026-11-02T09:00:00", key(1)), local("Lunch", "2026-11-03T03:00:00", key(2))
        stats = applecal.assign_ids([a, b], st)
        self.assertEqual((a["id"], b["id"]), ("Y", applecal.connector_id(key(2))))
        self.assertEqual((stats["same slot"], stats["new"]), (1, 1))

    def test_removed_event_returns_under_its_id(self):
        st = [stored("Z", "Sync", "2026-10-15T14:00:00", calkey=key(3), isCancelled=True, removed="2026-10-15")]
        ev = local("Sync", "2026-10-29T14:00:00", key(3))
        applecal.assign_ids([ev], st)
        self.assertEqual(ev["id"], "Z")


class SyncGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "inbox" / "calendar").mkdir(parents=True)
        self.store = FakeStore(root / "Calendar.sqlitedb")
        self.store.c.commit()
        self.con = db.connect(root / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('calendar','outlook','Calendar')")
        self.patches = [mock.patch.object(applecal, "db_path", lambda: str(root / "Calendar.sqlitedb")), mock.patch.object(importer, "ASSIST", root)]
        for p in self.patches:
            p.start()
        self.root = root

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.con.close()
        self.tmp.cleanup()

    def test_stale_store_is_not_used(self):
        self.store.synced(datetime.now(timezone.utc) - timedelta(hours=applecal.STALE_HOURS + 1))
        self.store.c.commit()
        with self.assertRaises(applecal.Stale):
            applecal.sync(self.con, log=lambda s: None)
        self.assertFalse((self.root / "inbox" / "calendar" / "events.json").exists())

    def test_sync_writes_events_and_records_a_pull(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.store.synced(now)
        start = (now + timedelta(days=1)).replace(hour=14, minute=0, second=0)
        self.store.event("Review", start.strftime("%Y-%m-%dT%H:%M:%S"), (start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"), cal_single(1), me=7)
        self.store.c.commit()
        applecal.sync(self.con, log=lambda s: None)
        ev = json.loads((self.root / "inbox" / "calendar" / "events.json").read_text())["events"]
        self.assertEqual([(e["subject"], e["response"], e["source"]) for e in ev], [("Review", "none", "calendar.app")])
        self.assertFalse(any(k.startswith("_") for k in ev[0]))
        pull = self.con.execute("SELECT agent, complete, pulled FROM pulls WHERE source_id='calendar'").fetchone()
        self.assertEqual(tuple(pull), ("assist calendar-local", 1, 1))


class Reply(unittest.TestCase):
    def test_reply_from_calendar_app_or_show_as(self):
        self.assertEqual(views.reply({"response": "none"}), "not answered")
        self.assertEqual(views.reply({"response": "tentative", "showAs": "tentative"}), "tentative")
        self.assertEqual(views.reply({"response": "accepted"}), "accepted")
        self.assertEqual(views.reply({"showAs": "tentative"}), "tentative")          # connector only: the proxy
        self.assertEqual(views.reply({"showAs": "tentative", "isOrganizer": True}), "organizer")
        self.assertEqual(views.reply({"showAs": "busy"}), "")


if __name__ == "__main__":
    unittest.main()
