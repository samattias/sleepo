"""The soul pages reach the agents whole (assist/soul.py): headed sections, not the first N characters; a renamed section falls
back to the whole page; every section an agent is meant to carry exists in the live pages.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import re
import unittest
from unittest import mock

from assist import db, soul

PAGE = """---
title: Test
owner: Sam
---
# Test page

Intro line.

## Beliefs
- one

## How the assistant must apply this
**1. Rule one.**
- detail

## Still to add (Sam)
- later
"""


class Parse(unittest.TestCase):
    def test_sections_drop_frontmatter_and_title(self):
        s = soul.sections(PAGE)
        self.assertEqual([h for h, _ in s], ["", "Beliefs", "How the assistant must apply this", "Still to add (Sam)"])
        self.assertEqual(s[0][1], "Intro line.")
        self.assertNotIn("owner:", "".join(b for _, b in s))

    def test_page_skips_notes_to_sam(self):
        with mock.patch.object(soul, "_raw", return_value=PAGE):
            p = soul.page("company")
        self.assertIn("### Beliefs", p)
        self.assertIn("Rule one", p)
        self.assertNotIn("later", p)

    def test_missing_section_falls_back_to_whole_page(self):
        with mock.patch.object(soul, "_raw", return_value=PAGE):
            t, missing = soul.text("company", ["Renamed heading"])
        self.assertEqual(missing, ["Renamed heading"])
        self.assertIn("Rule one", t)
        self.assertIn("Beliefs", t)


class Live(unittest.TestCase):
    """Against the real pages in memory/context/: if Sam renames a heading an agent relies on, this says which."""

    def test_every_section_an_agent_carries_exists(self):
        for key, label, name, wanted, how in soul.USES:
            if how == "carried" and wanted:
                for w in wanted:
                    self.assertIsNotNone(soul.section(name, w), f"{label}: '{w}' not found in {soul.FILES[name]}")

    def test_actions_and_brief_get_every_rule(self):
        # The old prompts took the first 1,400-1,500 characters of soul.md and lost all eight rules.
        for agent in ("todo", "brief", "initiatives", "strategy"):
            b = soul.block(agent)
            for rule in ("Treat statements as claims", "Weigh the source", "Say how confident you are", "keep judgements private"):
                self.assertIn(rule, b, f"{agent} is missing '{rule}'")
            self.assertIn(soul.titles()["cpo"], b)
            self.assertNotIn("owner: Sam", b)
            self.assertNotIn("Still to add", b)

    def test_replies_and_cowork_carry_the_drafting_rules(self):
        self.assertIn(soul.titles()["cpo"], soul.block("replies"))
        self.assertTrue(soul.block("cowork").strip())
        self.assertNotIn("How SleePO applies this", soul.block("replies"))

    def test_nesting(self):
        b = soul.block("prep", level=1)
        self.assertTrue(b.startswith("# " + soul.TITLES["company"]))
        self.assertRegex(b, r"(?m)^## How the assistant must apply this")

    def test_agents_without_carried_text(self):
        self.assertEqual(soul.block("speakers"), "")
        self.assertEqual(soul.block("no-such-agent"), "")

    def test_uses_report(self):
        u = soul.uses()
        self.assertEqual(set(u), {"company", "cpo", "sleepo"})
        self.assertTrue(all(x["exists"] for x in u.values()))
        self.assertFalse([x for v in u.values() for x in v["used_by"] if x["missing"]])

    def test_prompts_read_the_souls_through_this_module(self):
        # One way in, so a prompt cannot go back to clipping the page. (The importer only files the pages in the library.)
        for p in sorted((db.APP / "assist").glob("*.py")):
            if p.name not in ("soul.py", "importer.py"):
                self.assertIsNone(re.search(r"context/(cpo-)?soul\.md|\"soul\.md\"", p.read_text()), f"{p.name} reads a soul page directly")


if __name__ == "__main__":
    unittest.main()
