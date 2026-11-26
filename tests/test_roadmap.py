"""The product roadmap (assist/roadmap.py): Rowan's workbook's Initiatives sheet as a snapshot, and Roadmap › Refresh, which
reads the sheet again and loads it only when it differs (30 Oct 2026). An unchanged sheet writes nothing; a sheet that comes
back much shorter is a cut-off read and is refused; a change the search date does not show yet is dated when it was seen.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import db, roadmap

HEAD = "\t".join(roadmap.COLS)


def row(rid, name, status="planned", owner="Gray Selby", committed="FALSE"):
    vals = {"ID": rid, "Name_Internal": name, "Strategic_Theme": "Big Bets", "Start_Q": "Q1 2027", "End_Q": "Q2 2027",
            "Status": status, "Owner": owner, "Committed": committed}
    return "\t".join(vals.get(h, "") for h in roadmap.COLS)


class Roadmap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "t.db"
        self.con = db.connect(self.path)
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('sharepoint','sharepoint','SharePoint')")
        # the bundle goes to <ASSIST>/inbox/queue: a temporary folder here, never the real inbox
        self.patches = [mock.patch.object(db, "ASSIST", self.dir), mock.patch("assist.ingest.reindex", lambda con: None)]
        for p in self.patches:
            p.start()
        self.tsv = self.dir / "sheet.tsv"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.con.close()
        self.tmp.cleanup()

    def load(self, rows, modified=None, force=False):
        self.tsv.write_text("\n".join([HEAD, *rows]) + "\n")
        return roadmap.import_tsv(self.con, self.tsv, modified, force=force)

    def ten(self, change=None):
        return [row(f"AI-{n:03d}", (change or {}).get(n, f"Initiative {n}")) for n in range(1, 11)]

    def test_the_connectors_blank_row_lines_are_not_initiatives(self):
        items = roadmap.parse_tsv("\n".join([HEAD, row("AI-001", "One"), "[1 empty row]", "", row("AI-002", "Two"), "[3 empty rows]"]))
        self.assertEqual([i["id"] for i in items], ["AI-001", "AI-002"])
        self.assertEqual([i["sort"] for i in items], [0, 1])
        self.assertEqual(items[0]["owners"], ["Gray Selby"])

    def test_first_read_then_unchanged_writes_nothing(self):
        r = self.load(self.ten(), "2026-10-07T17:17:34Z")
        self.assertEqual((r["status"], r["count"], len(r["added"])), ("imported", 10, 10))
        self.assertEqual(roadmap.listing(self.con)["meta"]["modified"], "2026-10-07T17:17:34Z")
        self.assertEqual(len(list((self.dir / "inbox" / "queue" / "done").glob("roadmap-*.json"))), 1)
        self.con.commit()
        before = self.con.total_changes, os.stat(self.path).st_mtime_ns
        r = self.load(self.ten(), "2026-10-07T17:17:34Z")
        self.assertEqual(r["status"], "unchanged")
        self.assertEqual((self.con.total_changes, os.stat(self.path).st_mtime_ns), before)
        self.assertEqual(roadmap.note(r), "No change: the workbook's 10 initiatives match")

    def test_a_change_is_named_by_id(self):
        self.load(self.ten(), "2026-10-07T17:17:34Z")
        rows = self.ten({3: "Initiative three, renamed"})[1:] + [row("PLT-077", "New one")]
        r = self.load(rows, "2026-10-29T09:00:00Z")
        self.assertEqual((r["status"], r["added"], r["changed"], r["removed"]), ("imported", ["PLT-077"], ["AI-003"], ["AI-001"]))
        self.assertEqual(roadmap.note(r), "Updated: 1 new (PLT-077) · 1 changed (AI-003) · 1 removed (AI-001)")
        got = {i["id"]: i for i in roadmap.listing(self.con)["items"]}
        self.assertEqual(got["AI-003"]["name_internal"], "Initiative three, renamed")
        self.assertNotIn("AI-001", got)

    def test_a_change_the_search_date_does_not_show_is_dated_now(self):
        self.load(self.ten(), "2026-10-07T17:17:34Z")
        r = self.load(self.ten({5: "Changed after the index"}), "2026-10-07T17:17:34Z")
        self.assertEqual((r["status"], r["changed"]), ("imported", ["AI-005"]))
        self.assertGreater(r["modified"], "2026-10-07T17:17:34Z")
        self.assertEqual(roadmap.listing(self.con)["meta"]["modified"], r["modified"])

    def test_a_cut_off_read_is_refused_and_the_snapshot_kept(self):
        self.load(self.ten(), "2026-10-07T17:17:34Z")
        r = self.load(self.ten()[:5], "2026-10-30T08:00:00Z")
        self.assertEqual((r["status"], r["count"], r["before"]), ("refused", 5, 10))
        self.assertIn("5 of 10 initiatives", roadmap.note(r))
        self.assertEqual(len(roadmap.listing(self.con)["items"]), 10)
        self.assertEqual(self.load(self.ten()[:5], "2026-10-30T08:00:00Z", force=True)["status"], "imported")
        self.assertEqual(len(roadmap.listing(self.con)["items"]), 5)

    def test_a_refresh_that_died_is_reported_as_stopped(self):
        job = self.dir / "roadmap_pull.json"
        with mock.patch.object(roadmap, "JOB", job), mock.patch.object(roadmap.jobs, "held", lambda name: False):
            job.write_text(json.dumps({"running": True, "started": "2026-10-30T09:00:00Z", "pid": 999999}))
            st = roadmap.state()
        self.assertFalse(st["running"])
        self.assertFalse(st["ok"])
        self.assertIn("stopped", st["note"])

    def test_the_refresh_reads_ira_s_workbook_into_its_own_files(self):
        self.assertIn(roadmap.FILE_URI, roadmap.PULL_PROMPT)
        for f in (roadmap.PULLED, roadmap.PULLED_MODIFIED):   # not the morning refresh's initiatives.tsv
            self.assertIn(f"inbox/roadmap/{f.name}", roadmap.PULL_PROMPT)
        self.assertNotEqual(roadmap.PULLED, roadmap.TSV)
        self.assertEqual(roadmap.ISO.match("2026-10-07T17:17:34.000Z").group(1), "2026-10-07T17:17:34")


if __name__ == "__main__":
    unittest.main()
