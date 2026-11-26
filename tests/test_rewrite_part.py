"""Rewrite part of a draft (assist/rewrite_part.py): only the selected part is marked for the model, the rest of the
draft goes as it stands, an empty selection is refused, and the new part keeps the selection's line breaks.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import tempfile
import unittest
from pathlib import Path

from assist import db, rewrite_part as rp

DRAFT = "Hi Gray,\n\nThanks for the budget lines. I think we should probably look at them together at some point.\n\nCan you send the Team B headcount by Friday?\n\n-Sam"


class RewritePart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_only_the_selection_is_marked(self):
        s = DRAFT.index("Thanks")
        e = DRAFT.index("\n\nCan")
        p = rp.prompt(self.con, "email", DRAFT, s, e, "make it a clear ask for Thursday")
        self.assertIn(rp.START + "Thanks for the budget lines.", p)
        self.assertIn("at some point." + rp.END + "\n\nCan you send", p)
        self.assertEqual(p.count(rp.START), 2)   # once in the rules, once in the draft
        self.assertIn("make it a clear ask for Thursday", p)

    def test_empty_or_blank_selection_is_refused(self):
        self.assertIsNone(rp.prompt(self.con, "email", DRAFT, 5, 5, ""))
        self.assertIsNone(rp.prompt(self.con, "email", DRAFT, 8, 10, ""))   # "\n\n"
        with self.assertRaises(ValueError):
            rp.start_job(self.con, "email", DRAFT, 0, 0, "")

    def test_clean_keeps_the_selection_line_breaks_and_drops_echoed_markers(self):
        self.assertEqual(rp.clean(rp.START + " Shorter. " + rp.END, "\n\nLong text.\n"), "\n\nShorter.\n")
        self.assertEqual(rp.clean("  ", "x"), "")


if __name__ == "__main__":
    unittest.main()
