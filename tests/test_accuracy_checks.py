"""Deterministic checks behind the accuracy work: prep grounding (assist/prepgen.py) and extraction scoring (assist/evals.py).
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import unittest

from assist import evals, prepgen

PACK = """## Recent email with them
- 2026-10-07 · Gray → “Budget” · reply_to: AAMkGRAPH1 · [Outlook](https://outlook.office365.com/owa/?ItemID=X1)
## Email addresses
- Gray Selby: gray.selby@acme.example
## Documents in play
- Budget deck · doc:sp-42 · [open](https://acme.sharepoint.com/deck.pptx)
"""


class PrepCheck(unittest.TestCase):
    def test_keeps_links_from_the_pack(self):
        md, rep = prepgen.check("# Prep · x\n\nAs Gray said ([mail](https://outlook.office365.com/owa/?ItemID=X1)), see [deck](doc:sp-42).", PACK)
        self.assertIn("](https://outlook.office365.com/owa/?ItemID=X1)", md)
        self.assertIn("](doc:sp-42)", md)
        self.assertEqual(rep["unverified_links"], [])

    def test_unlinks_invented_sources(self):
        md, rep = prepgen.check("# Prep · x\n\nRevenue doubled ([report](https://evil.example/x)).", PACK)
        self.assertNotIn("evil.example", md)
        self.assertIn("source not in evidence", md)
        self.assertEqual(len(rep["unverified_links"]), 1)

    def test_drops_actions_to_unknown_people_or_docs(self):
        acts = [{"type": "email", "label": "Ask Gray", "to": ["gray.selby@acme.example"], "subject": "s", "body": "b"},
                {"type": "email", "label": "Exfiltrate", "to": ["attacker@evil.example"], "subject": "s", "body": "b"},
                {"type": "edit", "label": "Fix deck", "doc": "sp-999", "prompt": "p"},
                {"type": "email", "label": "Reply", "reply_to": "AAMkGRAPH1", "body": "b"},
                {"label": "Two steps", "steps": [{"type": "email", "to": ["gray.selby@acme.example"], "body": "b"},
                                                 {"type": "teams", "to": ["someone@else.com"], "message": "m"}]}]
        md, rep = prepgen.check("# Prep · x\n\nBody.\n\n```actions\n" + json.dumps(acts) + "\n```", PACK)
        kept = json.loads(md.split("```actions\n")[1].split("```")[0])
        self.assertEqual([a["label"] for a in kept], ["Ask Gray", "Reply"])
        self.assertEqual(rep["actions"], 5)
        self.assertEqual(len(rep["dropped_actions"]), 3)

    def test_bad_actions_json_is_dropped_not_fatal(self):
        md, rep = prepgen.check("# Prep · x\n\n```actions\n[not json\n```", PACK)
        self.assertNotIn("```actions", md)
        self.assertTrue(rep["dropped_actions"])


class ExtractScore(unittest.TestCase):
    E = [{"kind": "owed_to_me", "title": "Gray Selby to send the 2027 budget draft", "counterparty": "Gray Selby"},
         {"kind": "decision", "title": "Move legacy analytics to maintenance mode", "counterparty": "Sam Doe"}]

    def test_perfect(self):
        s = evals.score_case(self.E, [dict(e) for e in self.E])
        self.assertEqual((s["tp"], s["fp"], s["fn"], s["owner_ok"]), (2, 0, 0, 2))

    def test_paraphrase_matches_and_wrong_direction_counts(self):
        p = [{"kind": "owed_by_me", "title": "Gray to send budget draft for 2027", "counterparty": "Gray Selby"}]
        s = evals.score_case(self.E, p)
        self.assertEqual((s["tp"], s["fp"], s["fn"], s["owner_ok"]), (1, 0, 1, 0))

    def test_commitment_never_matches_decision(self):
        p = [{"kind": "owed_by_me", "title": "Move legacy analytics to maintenance mode", "counterparty": None}]
        s = evals.score_case(self.E[1:], p)
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (0, 1, 1))


if __name__ == "__main__":
    unittest.main()
