"""Revising a draft (assist/revise.py, Sam 28 Oct 2026: revisions read unnatural or changed nothing): the request comes last
in the prompt with the rules, Sam's own wording is found and kept, an empty or style request that changed nothing is caught
and run once more, and the reply writer uses it.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import unittest
from unittest import mock

from assist import replies, revise

DRAFT = "Hi Tatum,\n\nCan you please share the final list by Thursday? We need it for the email.\n\nThanks,\n\n-Sam"


class Revise(unittest.TestCase):
    def test_sams_own_wording_is_what_differs_from_sleepos_text(self):
        mine = DRAFT.replace("We need it for the email.", "Milo wants it before he sends.")
        self.assertEqual(revise.own_wording(mine, DRAFT), ["Milo wants it before he sends."])
        self.assertEqual(revise.own_wording(DRAFT, DRAFT), [])
        self.assertEqual(revise.own_wording(DRAFT, ""), [])

    def test_the_block_carries_the_draft_request_history_and_rules(self):
        b = revise.block(DRAFT.replace("We need", "Honestly we need"), "Warmer.", DRAFT, ["Shorter."])
        self.assertIn("<draft>\nHi Tatum", b)
        self.assertIn("# Sam's request now\nWarmer.", b)
        self.assertIn("- Shorter.", b)
        self.assertIn("Honestly we need it for the email.", b.split("# What he asked")[0].split("</draft>")[1])
        self.assertIn("changes the wording throughout", b)

    def test_unchanged_catches_no_change_but_not_a_small_factual_one(self):
        self.assertTrue(revise.unchanged(DRAFT, DRAFT + " ", "More direct."))
        self.assertTrue(revise.unchanged(DRAFT, DRAFT.replace("Can you please", "Could you please"), "Warmer."))
        self.assertFalse(revise.unchanged(DRAFT, DRAFT.replace("Thursday", "Friday"), "Make it Friday."))
        self.assertFalse(revise.unchanged(DRAFT, "", "Warmer."))

    def test_the_reply_writer_puts_the_request_last_and_reruns_a_revision_that_changed_nothing(self):
        with mock.patch.object(replies, "context", return_value=("EMAIL", {"conversation_id": "c"})), \
                mock.patch("assist.feedback.reply_lessons", return_value=""), \
                mock.patch("assist.relevance.company_facts", return_value=""), mock.patch("assist.relevance.free_slots", return_value=[]):
            p, _ = replies.prompt(None, 1, "Warmer.", current=DRAFT, base=DRAFT, history=["Shorter."])
        self.assertNotIn("# What Sam wants this reply to do", p)
        self.assertLess(p.index("<context>"), p.index("# Revise the current draft"))
        self.assertLess(p.index("# Sam's request now"), p.index("Write it now."))
        calls = []

        def run(text, cwd, purpose="replies", pics=None):
            calls.append((purpose, text.endswith(revise.NUDGE)))
            body = DRAFT if len(calls) == 1 else DRAFT.replace("Can you please share", "Thanks for this, Tatum. Could you share")
            return True, json.dumps({"subject": "Re: list", "body": body, "notes": "Warmed it."}), ""
        with mock.patch.object(replies, "_run", side_effect=run), mock.patch.object(replies, "_job_path") as jp, \
                mock.patch.object(replies, "_write") as w, mock.patch.object(replies, "JOB_DIR") as jd:
            jp.return_value.read_text.return_value = json.dumps({"revised": True, "current": DRAFT, "ask": "Warmer.", "kind": "chat"})
            (jd / "x.prompt").read_text.return_value = "PROMPT"
            jd.__truediv__.return_value.read_text.return_value = "PROMPT"
            replies.run_job("x", ".")
        self.assertEqual(calls, [("replies-revise", False), ("replies-revise", True)])
        out = w.call_args[0][1]
        self.assertIn("Thanks for this", out["body"])
        self.assertFalse(out["unchanged"])


if __name__ == "__main__":
    unittest.main()
