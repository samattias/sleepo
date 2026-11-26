"""Chat suggestions (assist/suggest.py): live hints from the register, the calendar and the meetings; Sam's personal syncs
skipped; a 1:1 named after the person; the CEO always offered; quarters computed from the date.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, entities, loops, suggest

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)   # a Tuesday, 13:00 in London


def at(**kw):
    return (NOW + timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Suggest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        entities.ensure_schema(c)
        loops.ensure_schema(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('calendar','outlook','c'), ('granola','granola','g')")
        c.executemany("INSERT INTO people(id, name, is_me, title) VALUES (?,?,?,?)",
                      [(1, "Sam Doe", 1, "CPO"), (2, "Milo Marsh", 0, "CEO"), (3, "Pat Noel", 0, "Director"), (4, "Parker Rio", 0, "Engineer")])
        c.executemany("INSERT INTO people_aliases VALUES (?,?)", [("pat.lee@acme.example", 3)])
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def event(self, start, subject, attendees):
        self.n += 1
        p = {"subject": subject, "start": start.replace("Z", ".0000000"), "attendees": attendees, "showAs": "busy"}
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, payload, pulled_at) VALUES (?,?,?,?,?,?,?,?)",
                         (self.n, "calendar", f"e{self.n}", "event", start, subject, json.dumps(p), at()))

    def loop(self, kind, person_id=None, origin=None, due=None, suggestion=None):
        self.n += 1
        self.con.execute("INSERT INTO loops(kind, title, person_id, fact_type, fact_id, created_at, origin_at, due, suggestion) VALUES (?,?,?,?,?,?,?,?,?)",
                         (kind, f"loop {self.n}", person_id, "commitment", self.n, at(), origin or at(days=-1), due, suggestion))

    def test_live_hints(self):
        c = self.con
        c.executemany("INSERT INTO todo(id, title, status) VALUES (?,?,?)", [("a", "one", "open"), ("b", "two", "open"), ("c", "old", "done")])
        self.event(at(hours=2), "Sam <> Robin sync", ["robin@example.com"])          # personal: never suggested
        self.event(at(hours=25), "Sam <> Pat 1:1", ["pat.lee@acme.example"])
        for _ in range(5):
            self.loop("promise", person_id=4, due="2026-10-15")
        self.loop("promise", person_id=2)                                               # one open with the CEO
        self.loop("decision", origin=at(days=-40))
        self.loop("waiting", person_id=4, origin=at(days=-20), suggestion="decide_or_drop")
        out = suggest.build(c, NOW)
        by = {x["id"]: x for x in out["items"]}

        self.assertEqual(by["focus"]["hint"], "2 actions ranked")
        self.assertEqual(by["next-meeting"]["label"], "Prep me for my 1:1 with Pat")
        self.assertEqual(by["next-meeting"]["hint"], "next meeting · tomorrow 14:00")
        self.assertIn("“Sam <> Pat 1:1”", by["next-meeting"]["prompt"])
        self.assertEqual(by["open-with-4"]["hint"], "6 open items")
        self.assertEqual(by["open-with-2"]["hint"], "1 open item · CEO")               # the CEO is offered with one item
        self.assertEqual(by["promises"]["hint"], "5 due this week · 6 promises open")
        self.assertEqual(by["decisions"]["hint"], "1 pending · oldest 40 days")
        self.assertEqual(by["chase"]["hint"], "1 waiting · 1 over 14 days")
        self.assertEqual(by["stale"]["hint"], "1 gone stale")
        self.assertEqual(by["quarter"]["label"], "How did Q3 go by region versus Q2?")
        self.assertNotIn("closing", by)                                                 # no Salesforce deals pulled
        self.assertEqual([x["score"] for x in out["items"]], sorted((x["score"] for x in out["items"]), reverse=True))
        self.assertEqual({x["group"] for x in out["items"]} - {g["key"] for g in out["groups"]}, set())

    def test_quarter_wraps_the_year(self):
        out = suggest.build(self.con, datetime(2026, 2, 1, 12, tzinfo=timezone.utc))
        self.assertIn("How did Q4 go by region versus Q3?", [x["label"] for x in out["items"]])


if __name__ == "__main__":
    unittest.main()
