"""Extraction reads everything since the mark (assist/loops.py extract): a normal day is one model call, more goes in
batches of whole items, what one run cannot read waits for the next with a gap, and a meeting is read again only when its
notes change. No model is called. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import db, loops, views  # noqa: F401  views reads db.ASSIST on import: load it before a test points that at a temp folder


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Model:
    """Stands in for _run_model: records each prompt and finds one promise in the first item of each batch."""
    def __init__(self, fail_on=None, find=True):
        self.prompts, self.fail_on, self.find = [], fail_on, find

    def __call__(self, prompt, cwd):
        self.prompts.append(prompt)
        if self.fail_on == len(self.prompts):
            raise RuntimeError("model timed out")
        ids = self.ids(prompt)
        if not self.find or not ids:
            return "{}"
        return json.dumps({"commitments": [{"kind": "owed_by_me", "title": f"Follow up on item {ids[0]}", "ref": f"S{ids[0]}"}], "decisions": []})

    @staticmethod
    def ids(prompt):
        return [int(x) for x in re.findall(r"^\[S(\d+)\]", prompt.split("# NEW MATERIAL", 1)[1], re.M)]

    def sent_ids(self):
        return [i for p in self.prompts for i in self.ids(p)]


class Extract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.con = db.connect(self.root / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox', 'outlook', 'i'), ('outlook.sent', 'outlook', 's'), "
                         "('teams', 'teams', 't'), ('granola', 'granola', 'g')")
        self.con.commit()
        self.patch = mock.patch.object(db, "ASSIST", self.root)   # bundles go to the temp folder, not Sam's inbox/queue
        self.patch.start()
        self.n = 0

    def tearDown(self):
        self.patch.stop()
        self.con.close()
        self.tmp.cleanup()

    def item(self, source, kind, days=0):
        self.n += 1
        i = 1000 + self.n
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (?,?,?,?,?,?)",
                         (i, source, f"x{i}", kind, ago(days), ago(0)))
        return i

    def chats(self, k, body="Can you send me the deck?"):
        out = []
        for _ in range(k):
            i = self.item("teams", "chat")
            self.con.execute("INSERT INTO chat_messages(item_id, source_id, external_id, conversation_name, conversation_kind, author, sent_at, body_text, fetched_at) "
                             "VALUES (?,?,?,?,?,?,?,?,?)", (i, "teams", f"x{i}", "Rowan Lowell", "dm", "Rowan Lowell", ago(0.5), f"{body} #{i}", ago(0)))
            out.append(i)
        self.con.commit()
        return out

    def mail(self, folder, days=0.5):
        i = self.item("outlook.sent" if folder == "sentitems" else "outlook.inbox", "sent" if folder == "sentitems" else "mail", days)
        frm, to = ("sam.doe@acme.example", "gray.selby@acme.example") if folder == "sentitems" else ("gray.selby@acme.example", "sam.doe@acme.example")
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, conversation_id, from_name, from_address, to_json, cc_json, subject, "
                         "received_at, sent_at, body_text, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (i, f"G{i}", folder, f"c{i}", frm.split("@")[0], frm, json.dumps([{"name": to.split("@")[0], "address": to}]), "[]", f"Budget {i}",
                          ago(days), ago(days), "I will send the budget draft on Friday.", ago(0)))
        self.con.commit()
        return i

    def meeting(self, days=0.5):
        i = self.item("granola", "note", days)
        self.con.execute("UPDATE items SET text='Sam to send the PLT pricing draft to Oakley.' WHERE id=?", (i,))
        self.con.execute("INSERT INTO meetings(note_item_id, title, starts_at, status) VALUES (?,?,?,?)", (i, "Pricing sync", ago(days), "pending"))
        self.con.commit()
        return i

    def restamp(self, item_id, text=None):
        """What every calendar import does to every meeting (meeting_people re-links people), optionally with new notes."""
        self.con.execute("UPDATE items SET pulled_at=?, text=COALESCE(?, text) WHERE id=?", (ago(0), text, item_id))
        self.con.commit()

    def setting(self, key):
        r = self.con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def gaps(self):
        return [r[0] for r in self.con.execute("SELECT value FROM settings WHERE key LIKE 'gap:%'")]

    def set_mark(self, iso):
        self.con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('loops:extract_mark', ?)", (iso,))
        self.con.commit()

    def extract(self, model, **kw):
        return loops.extract(self.con, log=lambda *_: None, run_model=model, **kw)

    def test_normal_day_is_one_call(self):
        self.set_mark(ago(1))
        items = [self.meeting(), self.mail("sentitems"), self.mail("sentitems"), self.mail("inbox")] + self.chats(3)
        model = Model()
        res = self.extract(model)
        self.assertEqual(len(model.prompts), 1)
        self.assertEqual(sorted(model.sent_ids()), sorted(items))
        self.assertEqual((res["batches"], res["remaining"], res["commitments"]), (1, 0, 1))
        self.assertGreater(self.setting("loops:extract_mark"), ago(0.01))   # moved to the start of this run
        self.assertIsNone(self.setting("loops:extract_done"))
        self.assertEqual(self.gaps(), [])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM commitments WHERE origin='Extracted'").fetchone()[0], 1)

    def test_source_over_its_limit_goes_in_batches_each_item_once(self):
        self.set_mark(ago(1))
        items = self.chats(150)   # 120 per call
        model = Model()
        res = self.extract(model)
        self.assertEqual(len(model.prompts), 2)
        sent = model.sent_ids()
        self.assertEqual(len(sent), len(set(sent)))
        self.assertEqual(sorted(sent), sorted(items))
        self.assertEqual((res["batches"], res["remaining"], res["commitments"]), (2, 0, 2))
        self.assertIn(f"Follow up on item {items[0]}", model.prompts[1].split("# NEW MATERIAL")[0])   # batch 2 knows what batch 1 found
        self.assertGreater(self.setting("loops:extract_mark"), ago(0.01))
        self.assertEqual(self.gaps(), [])

    def test_prompt_cap_splits_between_whole_items(self):
        self.set_mark(ago(1))
        body = "Please review the roadmap. " * 20                               # about 560 characters each
        items = self.chats(6, body=body)
        cap = len(loops.extract_prompt(self.con, [], [])) + 1300            # room for two of them per call
        model = Model(find=False)
        with mock.patch.object(loops, "EXTRACT_CHARS", cap):
            res = self.extract(model)
        self.assertEqual(len(model.prompts), 3)
        self.assertTrue(all(len(p) <= cap for p in model.prompts))
        self.assertEqual(sorted(model.sent_ids()), sorted(items))
        for i in items:   # every item arrives whole, in exactly one prompt
            self.assertEqual(sum(f"{body.strip()} #{i}" in p for p in model.prompts), 1)
        self.assertEqual(res["remaining"], 0)

    def test_batch_maximum_holds_the_mark_and_the_next_run_continues(self):
        mark = ago(5)
        self.set_mark(mark)
        items = self.chats(130)
        first = Model()
        res = self.extract(first, max_batches=1)
        self.assertEqual((len(first.prompts), res["remaining"]), (1, 10))
        self.assertEqual(self.setting("loops:extract_mark"), mark)                       # not moved past unread material
        self.assertEqual(len(json.loads(self.setting("loops:extract_done"))), 120)
        gaps = self.gaps()
        self.assertEqual(len(gaps), 1)
        self.assertIn("10 items", gaps[0])
        second = Model()
        res = self.extract(second)
        self.assertEqual(len(second.prompts), 1)
        self.assertEqual(sorted(first.sent_ids() + second.sent_ids()), sorted(items))      # the rest, and nothing twice
        self.assertEqual(res["remaining"], 0)
        self.assertGreater(self.setting("loops:extract_mark"), ago(0.01))
        self.assertIsNone(self.setting("loops:extract_done"))
        self.assertEqual(self.gaps(), [])                                                  # caught up: the gap is cleared

    def test_failed_call_keeps_what_was_read_and_retries_the_rest(self):
        items = self.chats(150)                                                            # no mark yet: the window is the last 36 hours
        res = self.extract(Model(fail_on=2))
        self.assertIn("error", res)
        self.assertEqual((res["batches"], res["remaining"], res["commitments"]), (1, 30, 1))
        self.assertLess(self.setting("loops:extract_mark"), ago(1.4))                      # held at the window's start, not now
        self.assertTrue(any("model call failed" in g for g in self.gaps()))
        retry = Model()
        res = self.extract(retry)
        self.assertEqual(sorted(retry.sent_ids()), sorted(items[120:]))
        self.assertNotIn("error", res)
        self.assertEqual(self.gaps(), [])

    def test_mail_from_days_away_is_read(self):
        self.set_mark(ago(6))
        old = self.mail("inbox", days=5)   # received while away, synced when the refresh came back
        model = Model()
        self.extract(model)
        self.assertEqual(model.sent_ids(), [old])

    def test_short_window_does_not_move_a_held_mark(self):
        mark = ago(5)
        self.set_mark(mark)
        self.chats(3)
        self.extract(Model(), hours=1)
        self.assertEqual(self.setting("loops:extract_mark"), mark)

    def test_restamped_meeting_is_read_again_only_when_its_notes_change(self):
        self.set_mark(ago(1))
        mid = self.meeting()
        self.extract(Model())
        self.restamp(mid)                                   # re-linked by an import, same notes
        again = Model()
        res = self.extract(again)
        self.assertEqual((again.prompts, res["remaining"]), ([], 0))
        self.assertEqual(self.gaps(), [])
        self.restamp(mid, text="Sam to send the PLT pricing draft to Oakley by Friday; Gray to confirm capacity.")
        changed = Model()
        self.extract(changed)
        self.assertEqual(changed.sent_ids(), [mid])

    def test_first_run_with_the_record_counts_older_meetings_as_read(self):
        self.set_mark(ago(1))
        old, new = self.meeting(days=10), self.meeting()    # both stamped now, as after any calendar import
        model = Model()
        self.extract(model)
        self.assertEqual(model.sent_ids(), [new])
        self.assertEqual(set(json.loads(self.setting("loops:extract_meetings"))), {str(old), str(new)})


if __name__ == "__main__":
    unittest.main()
