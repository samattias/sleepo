"""Task history (assist/task_history.py): Sam's actions clustered into the tasks he would have had, one week at a time,
each action used once, later weeks continuing earlier tasks; Sam's edits (merge, split, move, remove) kept; everything
gone after RETENTION_DAYS; and the block task suggestions read.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from assist import db, task_history as th, tasks
from assist.retention import RETENTION_DAYS


class History(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        tasks.ensure_schema(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources (id, system, name) VALUES ('outlook', 'm365', 'Outlook')")
        self.con.execute("INSERT INTO initiatives(id, slug, name, weight, active) VALUES (1, 'budget', 'Team B team & 2027 budget', 4, 1)")
        self.week = th._monday((datetime.now(timezone.utc) - timedelta(days=14)).date())
        self.n = 0
        for i, (subj, to, body) in enumerate([("2027 budget", "Gray Selby", "Gray, can you please send the budget lines by Friday?"),
                                               ("Re: 2027 budget", "Quinn Irving", "Quinn, here is the workbook for your review."),
                                               ("Thanks", "Ellis Ingram", "Thanks!")]):
            self.mail(subj, to, body, i)
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def mail(self, subj, to, body, day):
        self.n += 1
        ts = (datetime(self.week.year, self.week.month, self.week.day, 10, tzinfo=timezone.utc) + timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ")
        iid = self.con.execute("INSERT INTO items (source_id, external_id, kind, ts, pulled_at, subject) VALUES ('outlook', ?, 'mail', ?, ?, ?)",
                               (f"x{self.n}", ts, ts, subj)).lastrowid
        self.con.execute("INSERT INTO mail_messages (item_id, graph_id, folder, subject, sent_at, to_json, body_text, conversation_id, synced_at) "
                         "VALUES (?, ?, 'sentitems', ?, ?, ?, ?, ?, ?)",
                         (iid, f"g{self.n}", subj, ts, json.dumps([{"name": to, "address": to.lower().replace(' ', '.') + "@acme.example"}]),
                          body, "conv-budget" if "budget" in subj else f"conv{self.n}", ts))
        return iid

    def build(self, answer):
        return th.build_week(self.con, self.week, run_model=lambda p: json.dumps(answer), log=lambda *_: None)

    def test_actions_become_a_done_task_with_steps_and_the_rest_is_not_a_task(self):
        text, refs, _h, n = th.pack(self.con, self.week)
        self.assertEqual(n, 3)
        self.assertIn("<actions>", text)
        self.assertIn("Thread: 2027 budget", text)
        made = self.build({"tasks": [{"title": "Build the 2027 budget", "initiative": "Team B team & 2027 budget", "kind": "create",
                                      "steps": [{"title": "Ask Gray for budget lines", "owner": "Gray Selby", "actions": ["A1"]},
                                                {"title": "Send Quinn the workbook", "actions": ["A2", "A2", "A99"]}]}],
                           "not_tasks": ["A3"]})
        self.assertEqual(made, 1)
        t = self.con.execute("SELECT * FROM history_tasks").fetchone()
        self.assertEqual((t["title"], t["status"], t["initiative_id"]), ("Build the 2027 budget", "done", 1))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM history_actions WHERE task_id=?", (t["id"],)).fetchone()[0], 2)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM history_actions WHERE task_id IS NULL").fetchone()[0], 1)
        self.assertIn("Gray Selby", json.loads(t["people_json"]))
        # read once: a second build of the week finds nothing new
        self.assertEqual(th.pack(self.con, self.week)[3], 0)

    def test_a_later_week_continues_an_earlier_task(self):
        self.build({"tasks": [{"title": "Build the 2027 budget", "steps": [{"title": "Ask Gray", "actions": ["A1", "A2"]}]}]})
        later = self.week + timedelta(days=7)
        self.week = later
        self.mail("Re: 2027 budget", "Gray Selby", "Thanks Gray, I will take this to Milo.", 1)
        text, refs, hrefs, n = th.pack(self.con, later)
        self.assertEqual(n, 1)
        h = next(iter(hrefs))
        self.assertIn(h, text)
        self.build({"tasks": [{"continues": h, "steps": [{"title": "Take it to Milo", "actions": ["A1"]}]}]})
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM history_tasks").fetchone()[0], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM history_steps").fetchone()[0], 2)

    def test_merge_split_move_and_remove_are_kept_on_redo(self):
        self.build({"tasks": [{"title": "Budget", "steps": [{"title": "Ask Gray", "actions": ["A1"]}]},
                              {"title": "Workbook", "steps": [{"title": "Send Quinn", "actions": ["A2"]}]}]})
        a, b = [r[0] for r in self.con.execute("SELECT id FROM history_tasks ORDER BY id")]
        th.merge(self.con, b, a)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM history_steps WHERE task_id=?", (a,)).fetchone()[0], 2)
        step = self.con.execute("SELECT id FROM history_steps WHERE title='Send Quinn'").fetchone()[0]
        c = th.split(self.con, step, "Quinn's review")
        self.assertEqual(self.con.execute("SELECT task_id FROM history_actions WHERE step_id=?", (step,)).fetchone()[0], c)
        th.move_action(self.con, self.con.execute("SELECT ref FROM history_actions WHERE task_id=?", (c,)).fetchone()[0], None)
        th.update(self.con, a, {"title": "Build the 2027 budget", "status": "removed"})
        th.clear_week(self.con, self.week)   # --redo keeps what Sam edited
        self.assertEqual(self.con.execute("SELECT title, status, edited FROM history_tasks WHERE id=?", (a,)).fetchone()[:], ("Build the 2027 budget", "removed", 1))

    def test_history_older_than_retention_goes(self):
        self.build({"tasks": [{"title": "Budget", "steps": [{"title": "Ask Gray", "actions": ["A1"]}]}]})
        old = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.con.execute("UPDATE history_tasks SET finished_at=?", (old,))
        self.con.execute("UPDATE history_actions SET ts=?", (old,))
        th.purge(self.con, log=lambda *_: None)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM history_tasks").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM history_actions").fetchone()[0], 0)
        self.assertGreaterEqual(th.earliest(), th._monday((datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).date()))

    def test_block_shows_similar_past_tasks_and_is_empty_without_history(self):
        self.assertEqual(th.block(self.con, "anything"), "")
        self.build({"tasks": [{"title": "Build the 2027 budget workbook", "initiative": "Team B team & 2027 budget",
                               "steps": [{"title": "Ask Gray for lines", "owner": "Gray Selby", "actions": ["A1"]},
                                         {"title": "Send Quinn the workbook", "actions": ["A2"]}]}]})
        b = th.block(self.con, "Quinn Irving asks for the budget workbook for 2027")
        self.assertIn("Build the 2027 budget workbook", b)
        self.assertIn("[Gray Selby]", b)
        self.assertIn("email_new", b)
        self.assertNotIn("Build the 2027", th.block(self.con, "pricing for MCP credits with Oakley"))

    def test_a_failed_run_leaves_the_week_to_retry(self):
        def boom(_p):
            raise RuntimeError("timeout")
        th.build_week(self.con, self.week, run_model=boom, log=lambda *_: None)
        self.assertEqual(self.con.execute("SELECT status FROM history_weeks").fetchone()[0], "error")
        self.assertEqual(th.pack(self.con, self.week)[3], 3)


if __name__ == "__main__":
    unittest.main()
