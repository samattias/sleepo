"""Known gaps (assist/gaps.py): each is stamped when a pull reports it, only recent ones are current, a gap reported again
is current again, clearing removes both rows, and recording an unchanged gap writes nothing.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from assist import db, gaps


class Gaps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_only_recent_gaps_are_current(self):
        now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        gaps.note(self.con, "Slack: not authenticated", at="2026-10-07T08:00:00Z")
        gaps.note(self.con, "Teams: window not paginated", at="2026-10-27T08:00:00Z")
        self.con.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("gap:" + db.fingerprint("undated"), "undated"))
        self.assertEqual(gaps.current(self.con, now), ["Teams: window not paginated"])
        self.assertEqual([g["text"] for g in gaps.listing(self.con, now)][-1], "undated")
        gaps.note(self.con, "Slack: not authenticated", at="2026-10-28T08:00:00Z")   # reported again
        self.assertIn("Slack: not authenticated", gaps.current(self.con, now))

    def test_unchanged_note_writes_nothing_and_clear_removes_it(self):
        gaps.note(self.con, "Calendar: 1 event not fetched", at="2026-10-27T08:00:00Z")
        self.con.commit()
        before = self.con.total_changes
        gaps.note(self.con, "Calendar: 1 event not fetched", at="2026-10-26T08:00:00Z")   # older report: no change
        self.assertEqual(self.con.total_changes, before)
        gaps.clear(self.con, "Calendar: 1 event not fetched")
        self.assertEqual(gaps.listing(self.con), [])

    def test_backfill_dates_old_gaps_from_processed_bundles(self):
        self.con.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("gap:" + db.fingerprint("Old gap"), "Old gap"))
        done = Path(self.tmp.name) / "done"
        done.mkdir()
        f = done / "extract-2026-10-16.json"
        f.write_text(json.dumps({"gaps": ["Old gap"]}))
        t = datetime(2026, 10, 16, 7, tzinfo=timezone.utc).timestamp()
        os.utime(f, (t, t))
        self.assertEqual(gaps.backfill(self.con, done), (1, 1))
        self.assertEqual(gaps.listing(self.con)[0]["seen"], "2026-10-16T07:00:00Z")


if __name__ == "__main__":
    unittest.main()
