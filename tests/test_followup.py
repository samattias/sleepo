"""Meeting follow-ups (assist/followup.py): every action stands on a real moment of the transcript, moments in the text become
links to that moment, open items must be in the pack, recipients must be in the pack, and meetings that are not over, personal
or have no transcript get none.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from assist import followup

TURNS = [{"t": 0, "end": 20, "clock": "14:00", "me": True, "speaker": None, "lines": ["Shall we start?"]},
         {"t": 30, "end": 30, "clock": "14:00", "me": False, "speaker": "Gray Selby", "lines": ["I'll share the slider."]},
         {"t": 300, "end": 310, "clock": "14:05", "me": True, "speaker": None, "lines": ["I'll send Oakley the pricing rules today."]}]
PACK = "- Gray Selby: gray.selby@acme.example\n[L42] PROMISE · Send Oakley the pricing rules\n"


def answer(actions, body="**Outcome:** agreed the rules [05:00] and the slider [00:31], not [42:00]."):
    return "# Follow-up · Test · Thu 15 Oct\n\n" + body + "\n\n```actions\n" + json.dumps(actions) + "\n```"


class Check(unittest.TestCase):
    def test_actions_need_a_real_moment_and_get_its_speaker(self):
        md, rep = followup.check(answer([
            {"type": "email", "label": "Send the rules", "why": "asked (doc:ma-1)", "to": ["gray.selby@acme.example"], "body": "x", "t": "05:02", "item": "L42"},
            {"type": "email", "label": "Invented", "why": "no moment", "to": ["gray.selby@acme.example"], "body": "x"},
            {"type": "email", "label": "Wrong time", "why": "?", "to": ["gray.selby@acme.example"], "body": "x", "t": "59:00"},
        ]), PACK, TURNS, 7)
        acts = json.loads(md.split("```actions\n")[1].split("```")[0])
        self.assertEqual([a["label"] for a in acts], ["Send the rules"])
        a = acts[0]
        self.assertEqual(a["said"]["t"], 300)
        self.assertTrue(a["said"]["me"])
        self.assertEqual(a["meeting"], "m-7")
        self.assertEqual(a["loop"], 42)
        self.assertNotIn("t", a)
        self.assertEqual(a["why"], "asked")
        self.assertEqual(rep["no_moment"], ["Invented", "Wrong time"])

    def test_an_open_item_not_in_the_pack_is_not_linked(self):
        md, _ = followup.check(answer([{"type": "draft", "label": "Think", "why": "w", "prompt": "p", "t": "00:30", "item": 999}]), PACK, TURNS, 7)
        self.assertNotIn('"loop"', md)
        self.assertIn("Gray Selby", md)

    def test_recipients_must_come_from_the_pack(self):
        md, rep = followup.check(answer([{"type": "email", "label": "Leak", "why": "w", "to": ["someone@else.com"], "body": "x", "t": "00:30"}]), PACK, TURNS, 7)
        self.assertNotIn("```actions", md)
        self.assertTrue(any("someone@else.com" in d for d in rep["dropped_actions"]))

    def test_moments_in_the_text_link_to_the_transcript(self):
        md, rep = followup.check(answer([]), PACK, TURNS, 7)
        self.assertIn("[05:00](#/meetings/m-7?t=300)", md)
        self.assertIn("[00:31](#/meetings/m-7?t=30)", md)   # a moment inside a turn links to the turn's start
        self.assertNotIn("42:00", md)                       # not a moment of this recording: dropped
        self.assertIn("not.", md)
        self.assertEqual((rep["moments"], rep["unverified_moments"]), (3, 1))

    def test_a_steps_action_takes_its_moment_from_a_step(self):
        md, _ = followup.check(answer([{"label": "Tell both", "why": "w", "steps": [
            {"type": "email", "to": ["gray.selby@acme.example"], "body": "a", "t": "00:35"},
            {"type": "teams", "to": ["gray.selby@acme.example"], "message": "b"}]}]), PACK, TURNS, 7)
        a = json.loads(md.split("```actions\n")[1].split("```")[0])[0]
        self.assertEqual(a["said"]["who"], "Gray Selby")
        self.assertNotIn("t", a["steps"][0])


class Turns(unittest.TestCase):
    def test_a_turn_lasts_until_the_next_one(self):
        self.assertIs(followup._turn_at(TURNS, 100), TURNS[1])   # in the gap after Gray's line, before Sam speaks at 300
        self.assertIs(followup._turn_at(TURNS, 295), TURNS[2])   # 5 s slack before a turn starts
        self.assertIsNone(followup._turn_at(TURNS, 600))          # more than two minutes after the last line
        self.assertIsNone(followup._turn_at(TURNS, None))


class Eligible(unittest.TestCase):
    def row(self, **k):
        now = datetime.now(timezone.utc)
        d = {"status": "digested", "title": "Pricing", "starts_at": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "ends_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        d.update(k)
        return d

    def test_rules(self):
        t = {"turns": TURNS}
        self.assertEqual(followup.eligible(None, 1, self.row(), t), (True, ""))
        self.assertFalse(followup.eligible(None, 1, self.row(status="personal"), t)[0])
        self.assertFalse(followup.eligible(None, 1, self.row(title="Sam <> Robin/Terry sync"), t)[0])
        later = (datetime.now(timezone.utc) + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(followup.eligible(None, 1, self.row(ends_at=later), t), (False, "not over yet"))
        self.assertEqual(followup.eligible(None, 1, self.row(), {"turns": []}), (False, "no transcript for this meeting"))


class Write(unittest.TestCase):
    def test_a_reply_that_is_not_a_follow_up_is_refused(self):
        with mock.patch.object(followup, "prompt", return_value=("p", PACK, TURNS)):
            with self.assertRaises(RuntimeError):
                followup.write(None, 7, run_model=lambda p: "Here are some thoughts.")


class Context(unittest.TestCase):
    """The pack builds for a meeting with people at a company (25 Nov 2026: a loop variable named `org` hid the org pack module,
    so from 16 Nov every follow-up failed with AttributeError and no meeting got one)."""
    def setUp(self):
        import os
        import tempfile
        from pathlib import Path
        from assist import db
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        saved = os.environ.get("ASSIST_DB")
        self.addCleanup(lambda: os.environ.pop("ASSIST_DB", None) if saved is None else os.environ.__setitem__("ASSIST_DB", saved))
        os.environ["ASSIST_DB"] = str(Path(self.tmp.name) / "t.db")
        self.con = db.connect()
        self.addCleanup(self.con.close)
        db.migrate(self.con)
        c = self.con
        now = datetime.now(timezone.utc)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('granola', 'granola', 'Granola')")
        c.execute("INSERT INTO items (source_id, external_id, kind, ts, pulled_at, subject, text) VALUES ('granola', 'n1', 'note', ?, ?, 'Pricing', '')",
                  (now.strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y-%m-%dT%H:%M:%SZ")))
        note = c.execute("SELECT id FROM items WHERE external_id='n1'").fetchone()[0]
        c.execute("INSERT INTO meetings (note_item_id, title, starts_at, ends_at, status) VALUES (?, 'Pricing', ?, ?, 'digested')",
                  (note, (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")))
        self.mid = c.execute("SELECT id FROM meetings").fetchone()[0]
        c.execute("INSERT INTO orgs (name, kind) VALUES ('Fabrikam', 'partner')")
        org_id = c.execute("SELECT id FROM orgs WHERE name='Fabrikam'").fetchone()[0]
        c.execute("INSERT INTO people (name, title, org_id) VALUES ('Blake Pemberton', 'CEO', ?)", (org_id,))
        c.execute("INSERT INTO people (name, title) VALUES ('Gray Selby', 'VP Development')")
        for name, addr in (("Blake Pemberton", "blake@fabrikam.example"), ("Gray Selby", "gray@example.com")):
            pid = c.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()[0]
            c.execute("INSERT INTO people_aliases (alias, person_id) VALUES (?, ?)", (addr, pid))
        c.commit()

    def test_the_pack_names_each_persons_company_and_address(self):
        people = self.con.execute("SELECT * FROM people ORDER BY org_id IS NULL, id").fetchall()   # the company's person first
        t = {"title": "Pricing", "turns": TURNS, "speakers": [{"name": "Gray Selby", "words": 120}], "attendees": [],
             "words": {"me": 300}}
        with mock.patch.object(followup, "_transcript", return_value=t), mock.patch.object(followup, "_people", return_value=people):
            pack, turns = followup.context(self.con, self.mid)
        self.assertIn("Blake Pemberton", pack)
        self.assertIn("Fabrikam", pack)
        self.assertIn("blake@fabrikam.example", pack)
        self.assertEqual(turns, TURNS)


if __name__ == "__main__":
    unittest.main()
