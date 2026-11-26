"""Mail and messages linked to Sam's tasks (assist/task_links.py): the whole thread of a task's source links by itself,
Sam unlinking sticks (no pass links it again), an unsure model match is a suggestion, closed tasks are not offered, and
for_task gives one row per thread, newest first.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import sqlite3
import unittest
from unittest import mock

from assist import task_links as TL


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE items (id INTEGER PRIMARY KEY, kind TEXT, ts TEXT, subject TEXT, text TEXT, from_name TEXT, url TEXT, noise INTEGER);
      CREATE TABLE mail_messages (item_id INTEGER, conversation_id TEXT, subject TEXT, from_address TEXT, to_json TEXT, cc_json TEXT,
                                  received_at TEXT, sent_at TEXT, graph_id TEXT, body_text TEXT);
      CREATE TABLE chat_messages (item_id INTEGER, body_text TEXT, conversation_name TEXT);
      CREATE TABLE meetings (id INTEGER, note_item_id INTEGER);
      CREATE TABLE loops (id INTEGER, fact_type TEXT, fact_id TEXT);
      CREATE TABLE mentions (ref_type TEXT, ref_id INTEGER, entity_type TEXT, entity_id INTEGER, confidence REAL, reason TEXT, source TEXT,
                             verdict TEXT, updated_at TEXT, role TEXT, PRIMARY KEY (ref_type, ref_id, entity_type, entity_id));
      CREATE TABLE tasks (id INTEGER PRIMARY KEY, parent_id INTEGER, title TEXT, done_when TEXT, status TEXT, sources_json TEXT,
                          actions_json TEXT, loop_id INTEGER, initiative_id INTEGER, area TEXT, updated_at TEXT);
      CREATE TABLE initiatives (id INTEGER, name TEXT);""")
    from assist.migrations import m018_task_link_checks
    m018_task_link_checks.up(con)
    milo = json.dumps([{"address": "sam.doe@acme.example"}])
    for iid, conv, subj, ts in [(1, "c1", "Re: Product Management Role", "2026-10-15T08:00:00Z"), (2, "c1", "Re: Product Management Role", "2026-10-16T12:00:00Z"),
                                (3, "c9", "2027 Dev", "2026-10-16T14:00:00Z"), (4, "c4", "Lunch", "2026-10-16T15:00:00Z")]:
        con.execute("INSERT INTO items VALUES (?, 'mail', ?, ?, '', 'Milo Marsh', '', 0)", (iid, ts, subj))
        con.execute("INSERT INTO mail_messages VALUES (?, ?, ?, 'milo.marsh@acme.example', ?, '[]', ?, NULL, ?, 'text')", (iid, conv, subj, milo, ts, f"am:m{iid}"))
    con.execute("INSERT INTO tasks VALUES (1, NULL, '2027 P&E budget', 'Milo has it', 'open', ?, '[]', NULL, 4, NULL, '2026-10-22')",
                (json.dumps([{"ref": "E2", "item_id": 2}]),))
    con.execute("INSERT INTO tasks VALUES (2, NULL, 'Old task', '', 'done', ?, '[]', NULL, NULL, 'admin', '2026-10-01')", (json.dumps([{"ref": "E4", "item_id": 4}]),))
    con.execute("INSERT INTO tasks VALUES (3, 1, 'Send to Quinn', '', 'open', '[]', ?, NULL, NULL, NULL, '2026-10-22')", (json.dumps([{"type": "email", "reply_to": "m3"}]),))
    return con


class Links(unittest.TestCase):
    def test_a_sources_whole_thread_and_a_steps_email_action_link_to_the_task(self):
        con = _db()
        TL.sync_threads(con, log=lambda *_: None)
        self.assertEqual([t["task_id"] for t in TL.for_item(con, 1)], [1])   # same conversation as the source (E2)
        self.assertEqual([t["task_id"] for t in TL.for_item(con, 3)], [1])   # a step's email action replies to it
        self.assertEqual(TL.for_item(con, 4), [])                            # its task is done, so not synced
        self.assertEqual([x["item_id"] for x in TL.for_task(con, 1)], [3, 2])  # one row per thread, newest first

    def test_unlinking_sticks_and_relinking_undoes_it(self):
        con = _db()
        TL.sync_threads(con, log=lambda *_: None)
        TL.set_link(con, 1, 1, False)
        TL.sync_threads(con, log=lambda *_: None)
        self.assertEqual(TL.for_item(con, 2), [])   # the whole thread stays unlinked
        TL.set_link(con, 2, 1, True)
        self.assertEqual([(t["task_id"], t["source"]) for t in TL.for_item(con, 1)], [(1, "sam")])

    def test_model_matches_below_sure_are_suggestions_and_weak_ones_are_dropped(self):
        con = _db()
        TL.link_thread(con, 4, 1, "model", 0.7, "Milo mentions the budget")
        got = TL.for_item(con, 4)
        self.assertTrue(got[0]["suggested"])
        self.assertEqual(TL.for_items(con, [4]), {})   # the list marks sure links only
        con2 = _db()
        view = {"tasks": [{"id": 1, "title": "2027 P&E budget"}], "suggestions": []}
        out = json.dumps([{"item": 3, "task": "T1", "confidence": 0.9, "why": "the 2027 dev deck"}, {"item": 4, "task": "T1", "confidence": 0.3}])
        with mock.patch("assist.tasks.listing", lambda *a, **k: view), mock.patch("assist.tasks.line", lambda t, ref: f"[{ref}] {t['title']}"), \
                mock.patch("assist.llm.run", lambda *a, **k: out), mock.patch.object(TL, "_candidates", lambda c, d, n: [
                    {"id": 3, "kind": "mail", "ts": "2026-10-16", "subject": "2027 Dev", "text": "", "from_name": "A", "mail_text": "deck", "chat_text": None, "conversation_name": None},
                    {"id": 4, "kind": "mail", "ts": "2026-10-16", "subject": "Lunch", "text": "", "from_name": "A", "mail_text": "lunch?", "chat_text": None, "conversation_name": None}]):
            self.assertEqual(TL.match(con2, ".", log=lambda *_: None), 1)
        self.assertEqual([t["task_id"] for t in TL.for_item(con2, 3)], [1])
        self.assertEqual(TL.for_item(con2, 4), [])
        self.assertEqual(con2.execute("SELECT COUNT(*) FROM task_link_checks").fetchone()[0], 2)   # both read once


if __name__ == "__main__":
    unittest.main()
