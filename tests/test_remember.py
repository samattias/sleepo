"""What SleePO remembers from what Sam tells it (assist/remember.py; Sam, 28 Oct 2026): only his own words, every memory
quoting them, a newer statement replacing an older one, memories about other people expiring with RETENTION_DAYS, and the
prompt block putting the people involved first. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, remember


class Remember(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = (remember.DIR, remember.HEARD, remember.STATE)
        remember.DIR, remember.HEARD, remember.STATE = t, t / "heard.jsonl", t / "remember.json"
        self.con = c = db.connect(t / "t.db")
        db.migrate(c)
        c.execute("INSERT INTO people(id, name, is_me) VALUES (1, 'Sam Doe', 1)")
        c.execute("INSERT INTO people(id, name) VALUES (4, 'Glen Yardley'), (5, 'Gray Selby')")
        c.executemany("INSERT INTO people_aliases VALUES (?, ?)", [("glen yardley", 4), ("glen.yardley@acme.example", 4), ("gray selby", 5)])
        c.commit()

    def tearDown(self):
        remember.DIR, remember.HEARD, remember.STATE = self.saved
        self.con.close()
        self.tmp.cleanup()

    def words(self, *texts):
        return [{"at": f"2026-10-28T10:0{i}:00Z", "source": "revise", "text": t, "ref": "item:1", "label": "revising a reply"}
                for i, t in enumerate(texts)]

    def test_heard_skips_quick_asks_and_keeps_instructions(self):
        remember.heard("revise", "Shorter")
        remember.heard("revise", "Warmer.")
        remember.heard("revise", "Never copy Glen on contoso pricing threads", "item:9", "revising a reply")
        lines = [json.loads(x) for x in remember.HEARD.read_text().splitlines()]
        self.assertEqual([x["text"] for x in lines], ["Never copy Glen on contoso pricing threads"])
        self.assertEqual(oct(remember.HEARD.stat().st_mode & 0o777), "0o600")

    def test_a_memory_must_quote_sams_words(self):
        w = self.words("From now on never copy Glen Yardley on contoso pricing threads")
        n = remember.apply(self.con, [
            {"op": "add", "text": "Never copy Glen on contoso pricing threads.", "kind": "preference", "scope": ["drafts"],
             "about": ["Glen Yardley"], "quote": "never copy Glen Yardley on contoso pricing threads", "from": 0},
            {"op": "add", "text": "Sam hates long emails.", "kind": "preference", "scope": ["drafts"], "about": [],
             "quote": "I hate long emails", "from": 0},   # not in his words: dropped
        ], w)
        self.assertEqual((n["added"], n["dropped"]), (1, 1))
        m = remember.listing(self.con)["memories"][0]
        self.assertEqual((m["people"], m["scope"], m["source"]), (["Glen Yardley"], ["drafts"], "revise"))
        self.assertIsNotNone(m["expires_at"])   # names someone else: follows RETENTION_DAYS

    def test_own_way_of_working_has_no_expiry(self):
        remember.apply(self.con, [{"op": "add", "text": "Briefs lead with money.", "kind": "preference", "scope": ["briefs"],
                                   "about": [], "quote": "lead with money", "from": 0}], self.words("Please lead with money in briefs"))
        self.assertIsNone(remember.listing(self.con)["memories"][0]["expires_at"])

    def test_a_newer_statement_replaces_the_older_one(self):
        remember.apply(self.con, [{"op": "add", "text": "The work trip is 1 to 5 Nov.", "kind": "fact", "scope": ["all"], "about": [],
                                   "quote": "work trip is 1-5 Nov", "from": 0}], self.words("the work trip is 1-5 Nov"))
        old = remember.listing(self.con)["memories"][0]["id"]
        n = remember.apply(self.con, [{"op": "replace", "id": f"M{old}", "text": "The work trip is 1 to 6 Nov.", "kind": "fact",
                                       "scope": ["all"], "about": [], "quote": "1-6 Nov", "from": 0}], self.words("it's now 1-6 Nov"))
        self.assertEqual(n["replaced"], 1)
        ms = remember.listing(self.con)["memories"]
        self.assertEqual([m["text"] for m in ms], ["The work trip is 1 to 6 Nov."])
        self.assertEqual(self.con.execute("SELECT status, replaced_by FROM memories WHERE id=?", (old,)).fetchone()[0], "replaced")

    def test_block_puts_the_people_involved_first_and_respects_scope(self):
        a = remember.add(self.con, "Keep Glen's updates to three bullets.", "preference", [4], ["drafts"])
        b = remember.add(self.con, "Sign emails -Sam.", "preference", [], ["drafts"])
        remember.add(self.con, "Gray prefers written agendas.", "preference", [5], ["briefs"])
        remember.add(self.con, "Lead briefs with the outcome.", "preference", [], ["briefs"])
        blk = remember.block(self.con, "drafts", "update for Glen", [4])
        self.assertLess(blk.index(f"[M{a}]"), blk.index(f"[M{b}]"))
        self.assertNotIn("Gray", blk)          # another scope
        self.assertNotIn("Lead briefs", blk)
        self.assertNotIn("Glen", remember.block(self.con, "drafts", "pricing sheet", [5]))   # about someone not involved
        self.assertEqual(remember.block(self.con, "chat", "anything"), "")

    def test_reads_never_write_and_unchanged_edits_write_nothing(self):
        mid = remember.add(self.con, "Lead briefs with the outcome.", "preference", [], ["briefs"])
        before = self.con.total_changes
        remember.block(self.con, "briefs", "outcome")
        remember.listing(self.con)
        self.assertFalse(remember.update(self.con, mid, {"text": "Lead briefs with the outcome."}))
        self.assertEqual(self.con.total_changes, before)
        self.assertTrue(remember.update(self.con, mid, {"text": "Lead briefs with the decision needed."}))

    def test_expired_and_deleted_memories_go(self):
        mid = remember.add(self.con, "Glen is on leave until 3 Nov.", "fact", [4], ["all"])
        gone = remember.add(self.con, "Old preference.", "preference", [], ["all"])
        past = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.con.execute("UPDATE memories SET expires_at=? WHERE id=?", (past, mid))
        remember.delete(self.con, gone)
        self.assertEqual(remember.listing(self.con)["memories"], [])   # expired is hidden at once, deleted is not listed
        self.con.execute("UPDATE memories SET updated_at=? WHERE id=?", (past, gone))
        remember.purge(self.con)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)

    def test_learn_reads_only_new_words_and_records_progress(self):
        remember.heard("notes", "Always open Milo's briefs with the money story", "event:X", "notes for a meeting brief")
        seen = []

        def model(prompt):
            seen.append(prompt)
            return json.dumps([{"op": "add", "text": "Open Milo's briefs with the money story.", "kind": "preference",
                                "scope": ["briefs"], "about": [], "quote": "open Milo's briefs with the money story", "from": 0}])
        res = remember.learn(self.con, run_model=model)
        self.assertEqual((res["heard"], res["added"]), (1, 1))
        self.assertIn("money story", seen[0])
        self.assertEqual(remember.learn(self.con, run_model=model), {"heard": 0})   # nothing new: no model call
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
