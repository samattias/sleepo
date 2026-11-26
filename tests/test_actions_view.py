"""The Actions page (assist/actions_view.py; Sam, 25 Nov 2026): reactive (emails that need a response, Teams/Slack messages owed,
follow-ups from meetings) and proactive (emails and messages written for him, promises, other suggestions). Each thing lands in
one section only, long-overdue suggestions sink below current ones, steps that are someone else's are left out, and building
the page writes nothing.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import actions_view, db, replies, tasks


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "t.db"
        self.con = db.connect(self.path)
        self.addCleanup(self.con.close)
        db.migrate(self.con)
        tasks.ensure_schema(self.con)
        c = self.con
        c.executemany("INSERT INTO people(id, name, title) VALUES (?, ?, ?)",
                      [(1, "Gray Selby", "VP Development"), (2, "Milo Marsh", "CEO"), (3, "Quinn Irving", "Finance Director")])
        c.executemany("INSERT INTO people_aliases VALUES (?, ?)", [("gray@example.com", 1), ("milo@example.com", 2), ("quinn@example.com", 3)])
        c.execute("INSERT INTO initiatives(id, slug, name, weight, active) VALUES (1, 'plt', 'PLT', 5, 1)")
        for sid in ("granola", "teams", "outlook.inbox"):
            c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES (?, ?, ?)", (sid, sid, sid))
        c.commit()

    def build(self, inbox=()):
        with mock.patch.object(replies, "inbox", return_value=list(inbox)):
            return actions_view.build(self.con)

    def keys(self, d):
        return {side: {k: [r["key"] for r in rows] for k, rows in d[side].items()} for side in ("reactive", "proactive")}


class Sections(Base):
    def test_each_thing_lands_in_its_own_section_once(self):
        c = self.con
        # a meeting and the follow-up step proposed from it, with an email written: reactive, not "ready to send"
        c.execute("INSERT INTO items (id, source_id, external_id, kind, ts, pulled_at, subject) VALUES (5, 'granola', 'n5', 'note', ?, ?, 'Pricing')", (ago(1), ago(1)))
        c.execute("INSERT INTO meetings (id, note_item_id, title, starts_at, status) VALUES (7, 5, 'Pricing with Gray', ?, 'digested')", (ago(1),))
        src = [{"ref": "G7", "label": "Meeting: Pricing with Gray · Gray at 12:30: “send me the rules”", "url": "#/meetings/m-7?t=750"}]
        fu = tasks.create(c, {"title": "Follow up: Pricing with Gray", "subtasks": [{"title": "Send Gray the pricing rules", "sources": src,
                          "actions": [{"type": "email", "label": "Rules", "to": ["gray@example.com"], "subject": "Pricing rules", "body": "Hi Gray"}]}]},
                          status="suggested", origin="meeting")
        fu_step = c.execute("SELECT id FROM tasks WHERE parent_id=?", (fu,)).fetchone()[0]
        # an email SleePO wrote for a suggested step: ready to send
        rec = tasks.create(c, {"title": "Board pack ready", "initiative": 1, "subtasks": [{"title": "Ask Quinn for the Q4 numbers",
                           "actions": [{"type": "email", "label": "Q4", "to": ["quinn@example.com"], "subject": "Q4 numbers", "body": "Hi Quinn"}]}]},
                           status="suggested", origin="assistant")
        rec_step = c.execute("SELECT id FROM tasks WHERE parent_id=?", (rec,)).fetchone()[0]
        # a promise from the register
        c.execute("INSERT INTO loops (id, kind, title, counterpart, person_id, origin_at, status, fact_type, fact_id, created_at) "
                  "VALUES (40, 'promise', 'Send Milo the ORC one-pager', 'Milo Marsh', 2, ?, 'open', 'commitment', 900, ?)", (ago(2), ago(2)))
        pr = tasks.create(c, {"title": "Send Milo the ORC one-pager", "kind": "do", "loop_id": 40}, status="suggested", origin="register")
        # another suggestion: a chase
        nx = tasks.create(c, {"title": "contoso's answer", "subtasks": [{"title": "Ask Reese for contoso's answer", "kind": "chase"}]},
                          status="suggested", origin="assistant")
        nx_step = c.execute("SELECT id FROM tasks WHERE parent_id=?", (nx,)).fetchone()[0]
        # a Teams message owed an answer
        c.execute("INSERT INTO items (id, source_id, external_id, kind, ts, pulled_at, subject) VALUES (9, 'teams', 'c9', 'chat', ?, ?, 'x')", (ago(1), ago(1)))
        c.execute("INSERT INTO chat_messages (item_id, source_id, external_id, conversation_name, author, sent_at, body_text) "
                  "VALUES (9, 'teams', 'c9', 'Gray Selby', 'Gray Selby', ?, 'Can you review the slider?')", (ago(1),))
        c.execute("INSERT INTO loops (id, kind, title, counterpart, person_id, origin_at, status, fact_type, fact_id, created_at) "
                  "VALUES (41, 'reply', 'Answer Gray', 'Gray Selby', 1, ?, 'open', 'chat', 9, ?)", (ago(1), ago(1)))
        # an email waiting on a response, from the CEO, with a recommended reply ready
        c.execute("INSERT INTO items (id, source_id, external_id, kind, ts, pulled_at, subject) VALUES (11, 'outlook.inbox', 'm11', 'mail', ?, ?, 'Board')", (ago(1), ago(1)))
        c.execute("CREATE TABLE IF NOT EXISTS reply_predrafts (item_id INTEGER PRIMARY KEY, status TEXT NOT NULL, mode TEXT, created_at TEXT)")
        c.execute("INSERT INTO reply_predrafts (item_id, status, mode, created_at) VALUES (11, 'ok', 'reply', ?)", (ago(0),))
        c.commit()
        mail = {"id": 11, "subject": "Board", "from_name": "Milo Marsh", "from_address": "milo@example.com", "received_at": ago(1),
                "preview": "Can you send the product section?", "needs_reply": True, "answered": False, "reply_why": "asks you"}
        d = self.build([mail, {**mail, "id": 12, "needs_reply": False}])
        k = self.keys(d)
        self.assertEqual(k["reactive"]["emails"], ["e-11"])
        self.assertEqual(k["reactive"]["messages"], ["m-41"])
        self.assertEqual(k["reactive"]["followups"], [f"s-{fu_step}"])
        self.assertEqual(k["proactive"]["send"], [f"s-{rec_step}"])
        self.assertEqual(k["proactive"]["promises"], [f"s-{pr}"])
        self.assertEqual(k["proactive"]["next"], [f"s-{nx_step}"])
        every = [x for side in k.values() for rows in side.values() for x in rows]
        self.assertEqual(len(every), len(set(every)), "a thing shows in one section only")

        e = d["reactive"]["emails"][0]
        self.assertIn("CEO", e["tags"])
        self.assertIn("Draft ready", e["tags"])
        self.assertEqual(e["open"], "/inbox?open=11")
        f = d["reactive"]["followups"][0]
        self.assertEqual(f["meeting"]["title"], "Pricing with Gray")
        self.assertEqual(f["said"]["url"], "#/meetings/m-7?t=750")
        self.assertEqual(f["draft"], f"t-{fu_step}-0")   # its email opens in Drafts
        s = d["proactive"]["send"][0]
        self.assertEqual(s["who"], "Quinn Irving")         # recipients as names
        self.assertEqual(s["draft"], f"t-{rec_step}-0")
        p = d["proactive"]["promises"][0]
        self.assertEqual(p["who"], "Milo Marsh")
        self.assertEqual(d["reactive"]["messages"][0]["open"], "/messages?open=9")
        self.assertEqual(d["counts"], {"reactive": 3, "proactive": 3})

    def test_someone_elses_step_and_closed_steps_are_left_out(self):
        c = self.con
        t = tasks.create(c, {"title": "Budget", "subtasks": [{"title": "Gray sends the headcount", "owner": "Gray Selby"},
                                                             {"title": "Agree the budget", "kind": "decide"}]}, status="suggested", origin="assistant")
        mine = c.execute("SELECT id FROM tasks WHERE parent_id=? AND owner IS NULL", (t,)).fetchone()[0]
        done = tasks.create(c, {"title": "Old", "subtasks": [{"title": "Already done"}]}, status="open", origin="sam")
        tasks.set_status(c, c.execute("SELECT id FROM tasks WHERE parent_id=?", (done,)).fetchone()[0], "done")
        d = self.build()
        self.assertEqual([r["key"] for r in d["proactive"]["next"]], [f"s-{mine}"])

    def test_a_long_overdue_suggestion_sinks_below_a_current_one(self):
        c = self.con
        old = tasks.create(c, {"title": "Board slides", "initiative": 1, "subtasks": [{"title": "Build the board slides", "due": day(-20)}]},
                           status="suggested", origin="assistant")
        new = tasks.create(c, {"title": "Company 982 demo", "subtasks": [{"title": "Agree the demo lead", "due": day(1)}]}, status="suggested", origin="assistant")
        c.execute("UPDATE tasks SET created_at=? WHERE id=? OR parent_id=?", (ago(12), old, old))
        c.commit()
        rows = self.build()["proactive"]["next"]
        self.assertEqual([r["title"] for r in rows], ["Agree the demo lead", "Build the board slides"])
        self.assertIn("Due tomorrow", rows[0]["tags"])
        self.assertTrue(any(t.startswith("Was due") for t in rows[1]["tags"]))
        self.assertFalse(rows[1]["hot"])
        self.assertTrue(rows[0]["hot"])

    def test_building_the_page_writes_nothing(self):
        tasks.create(self.con, {"title": "Something", "subtasks": [{"title": "Do it"}]}, status="suggested", origin="assistant")
        tasks.create(self.con, {"title": "Snoozed", "subtasks": [{"title": "Later"}]}, status="open", origin="sam")
        self.con.execute("UPDATE tasks SET status='snoozed', snooze_until=? WHERE title='Snoozed'", (ago(1),))   # a due snooze is not written back
        self.con.commit()
        before, mtime = self.con.total_changes, os.path.getmtime(self.path)
        self.build()
        self.assertEqual(self.con.total_changes, before)
        self.assertEqual(os.path.getmtime(self.path), mtime)


if __name__ == "__main__":
    unittest.main()
