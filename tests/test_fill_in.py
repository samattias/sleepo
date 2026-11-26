"""Filling a draft's blanks by asking Sam (assist/fill_in.py): blanks are found as the editor highlights them, the model's
questions are kept only when well formed and tied to real blanks, and the fill prompt keeps the draft and skipped blanks.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import unittest

from assist import fill_in

DRAFT = "Hi Rowan,\n\nCan we do [FILL: day and time]? I will bring [FILL: which pricing sheet] and [FILL: day and time].\n\n-Sam"


class FillIn(unittest.TestCase):
    def test_blanks(self):
        self.assertEqual(fill_in.blanks(DRAFT), ["[FILL: day and time]", "[FILL: which pricing sheet]"])
        self.assertEqual(fill_in.blanks("No blanks here."), [])

    def test_clean(self):
        marks = fill_in.blanks(DRAFT)
        raw = [{"id": "q1", "header": "A very long header", "question": "When?", "multi": False,
                "options": [{"label": f"Opt {n}", "detail": "d"} for n in range(6)], "fills": ["[FILL: day and time]", "[FILL: invented]"]},
               {"question": "", "options": []},                      # no question: dropped
               "not a dict",
               {"id": "q2", "question": "Which sheet?", "multi": True, "options": [{"label": "v3"}, {"detail": "no label"}], "fills": []}]
        out = fill_in._clean(raw, marks)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["header"], "A very long ")                 # 12 characters
        self.assertEqual(len(out[0]["options"]), 4)
        self.assertEqual(out[0]["fills"], ["[FILL: day and time]"])        # only blanks that exist
        self.assertTrue(out[1]["multi"])
        self.assertEqual([o["label"] for o in out[1]["options"]], ["v3"])
        self.assertEqual(fill_in._clean([{"question": "Only one?", "fills": []}], ["[FILL: x]"])[0]["fills"], ["[FILL: x]"])

    def test_answers_prompt(self):
        p = fill_in.answers_prompt("chat", DRAFT, [
            {"question": "When?", "fills": ["[FILL: day and time]"], "answer": ["Tue 27 Oct, 14:00"]},
            {"question": "Which sheet?", "fills": ["[FILL: which pricing sheet]"], "answer": []}], app="slack")
        self.assertIn("Slack message", p)
        self.assertIn("Sam's answer: Tue 27 Oct, 14:00", p)
        self.assertIn("(no answer: leave these blanks exactly as they are)", p)
        self.assertIn(DRAFT.strip(), p)

    def test_chat_card_context(self):
        """A draft card in Ask SleePO: the questions read its conversation and the context files it was seeded with."""
        import sqlite3
        import tempfile
        from pathlib import Path
        from unittest import mock
        from assist import rewrite_part
        with tempfile.TemporaryDirectory() as d:
            Path(d, "Initiative context.md").write_text("Goal: ship the foundation")
            Path(d, ".email-drafts.json").write_text("{}")
            Path(d, "notes.md").write_text("not a context file")
            con = sqlite3.connect(":memory:")
            con.execute("CREATE TABLE chat_threads (id TEXT, workspace TEXT)")
            con.execute("INSERT INTO chat_threads VALUES ('t1', ?)", (d,))
            with mock.patch.object(rewrite_part, "_chat_turns", return_value="Sam: write to Rowan about the date"):
                ctx = fill_in._context(con, "email", None, tid="t1")
                self.assertIn("write to Rowan about the date", ctx)
                self.assertIn("# Initiative context\nGoal: ship the foundation", ctx)
                self.assertNotIn("not a context file", ctx)
            with mock.patch.object(rewrite_part, "_chat_turns", return_value=""):
                self.assertEqual(fill_in._context(con, "email", None), "")    # a new email outside a conversation: nothing to read
                with self.assertRaises(ValueError):
                    fill_in.start_questions(con, "email", DRAFT)

    def test_no_blanks_nothing_to_do(self):
        with self.assertRaises(ValueError):
            fill_in.start_answers("email", "Thanks, all clear.", [])


if __name__ == "__main__":
    unittest.main()
