"""An initiative's status (assist/initiatives.py draft_update): written by SleePO and current at once (no draft left to
approve), with suggested actions stored as task suggestions under the initiative, never repeating a task Sam has.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import db, initiatives, tasks


class Status(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        tasks.ensure_schema(self.con)
        self.con.execute("INSERT INTO initiatives (slug, name, weight, status, goal, active, updated_at) VALUES ('plt', 'PLT / NOVA', 5, 'on track', 'Three customers', 1, '2026-10-01')")
        self.ini = self.con.execute("SELECT id FROM initiatives WHERE slug='plt'").fetchone()[0]
        tasks.create(self.con, {"title": "Shareable Nova project document", "initiative": self.ini})
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_status_is_current_and_actions_are_suggestions(self):
        answer = json.dumps({"health": "at risk", "status": "Kick-off on 1 Nov; the document has gaps [S1].", "progress": "Trip approved.",
                             "blockers": "None", "next": "Send the document", "scope": "None", "sources": [],
                             "suggestions": [{"title": "Design partnership terms agreed for NWT", "why": "No commercial model yet", "subtasks": [{"title": "Draft terms with Glen"}]},
                                             {"title": "Shareable Nova project document", "why": "a repeat of a task Sam has"}]})
        with mock.patch.object(initiatives, "_model", return_value=answer):
            initiatives.draft_update(self.con, "plt")
        d = initiatives.detail(self.con, "plt")
        self.assertIsNone(d["draft"])                                  # nothing left to approve
        self.assertEqual(d["last_update"]["health"], "at risk")
        self.assertEqual(d["last_update"]["status"], "Kick-off on 1 Nov; the document has gaps.")   # references stripped
        rows = self.con.execute("SELECT title, status, initiative_id FROM tasks WHERE parent_id IS NULL AND status='suggested'").fetchall()
        self.assertEqual([(r["title"], r["initiative_id"]) for r in rows], [("Design partnership terms agreed for NWT", self.ini)])
        self.assertEqual(d["tasks_open"], 1)
        self.assertEqual(d["tasks_suggested"], 1)


if __name__ == "__main__":
    unittest.main()
