"""One definition of source freshness (assist/source_status.py), shared by the Today widget, the Sources pages and the brief.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, source_status

NOW = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)


def ago(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


class SourceStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        self.con.execute("DELETE FROM sources")   # a new database is seeded with the core sources (m031); these tests set their own
        rows = [("outlook.inbox", "outlook", "ok", ago(1), ""), ("outlook.sent", "outlook", "ok", ago(2), ""),
                ("sharepoint", "sharepoint", "ok", ago(116), ""),       # stored health says ok, but it is five days old
                ("salesforce", "salesforce", "ok", ago(108), ""),       # weekly by design: not stale yet
                ("slack", "slack", "ok", ago(1), "not authenticated"), ("teams", "teams", "capped", ago(1), "")]
        for i, (sid, system, health, last, note) in enumerate(rows):
            self.con.execute("INSERT OR REPLACE INTO sources(id, system, name, health, last_pull_at, note, sort) VALUES (?,?,?,?,?,?,?)",
                             (sid, system, sid, health, last, note, i))
        self.con.execute("INSERT INTO pulls(source_id, agent, finished_at) VALUES ('outlook.inbox', 'assist mail-local', ?)", (ago(1),))
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_states_age_and_do_not_trust_stored_health(self):
        s = {x["id"]: x["state"] for x in source_status.streams(self.con, NOW)}
        self.assertEqual(s, {"outlook.inbox": "fresh", "outlook.sent": "fresh", "sharepoint": "stale", "salesforce": "fresh", "slack": "off", "teams": "capped"})

    def test_system_age_is_its_stale_streams_not_a_fresh_one(self):
        # the roadmap workbook never goes stale; an old one must not make SharePoint look 20 days old
        self.con.execute("INSERT INTO sources(id, system, name, health, last_pull_at, sort) VALUES ('roadmap','sharepoint','roadmap','ok',?,9)", (ago(480),))
        self.con.commit()
        self.assertEqual(round(source_status.systems(self.con, NOW)["sharepoint"]["age_hours"]), 116)

    def test_system_takes_worst_stream_and_via(self):
        sysmap = source_status.systems(self.con, NOW)
        self.assertEqual(sysmap["outlook"]["state"], "fresh")
        self.assertEqual(sysmap["outlook"]["via"], "Apple Mail")
        self.assertEqual(sysmap["sharepoint"]["label"], "Stale")


if __name__ == "__main__":
    unittest.main()
