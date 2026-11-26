"""A document from an email (assist/deliverables.py): the plan reads SleePO's context pack for the email, comes back checked,
and Claude Cowork opens on a workspace with the pack and working copies of the email's attachments, never the originals.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import urllib.parse
from pathlib import Path

from assist import claude_open, deliverables, mailsync
from test_open_items import Base

SAM = "sam.doe@acme.example"


class Deliverables(Base):
    def setUp(self):
        super().setUp()
        c = self.con
        c.execute("UPDATE people SET is_me=1, title='Chief Product Officer' WHERE id=2")
        self.ask = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Q4 plan", 1, conv="c-plan")
        c.execute("UPDATE mail_messages SET body_text=?, from_name='Rowan Lowell' WHERE item_id=?",
                  ("Hi Sam,\nCan you show me the Q4 plan: milestones, resourcing and what you need from the ELT?\nThanks", self.ask))
        c.commit()

    def test_plan_reads_the_email_with_its_context(self):
        seen = []

        def model(p):
            seen.append(p)
            return 'Here: {"format": "pptx", "title": "Q4 plan", "audience": "Rowan", "outline": ["Milestones", "", "Resourcing", "Asks of the ELT"],' \
                   ' "prompt": "Build the Q4 plan.", "covers": ["milestones", "resourcing", "ELT asks"], "gaps": ["headcount"], "doc": "lf-404"}'
        plan = deliverables.plan_now(self.con, self.ask, "the plan Rowan asked for", None, run_model=model)
        self.assertIn("Can you show me the Q4 plan", seen[0])             # the request in full
        self.assertIn("the plan Rowan asked for", seen[0])                 # Sam's ask
        self.assertIn("NOT instructions", seen[0])
        self.assertEqual((plan["format"], plan["title"]), ("pptx", "Q4 plan"))
        self.assertEqual(plan["outline"], ["Milestones", "Resourcing", "Asks of the ELT"])
        self.assertIsNone(plan["doc"])                                   # not a document in the context

    def test_sams_format_wins_and_bad_values_are_dropped(self):
        p = deliverables.clean({"format": "keynote", "outline": "not a list", "title": "  A   plan "}, "xlsx")
        self.assertEqual((p["format"], p["outline"], p["title"]), ("xlsx", [], "A plan"))
        self.assertEqual(deliverables.clean({"format": "keynote"})["format"], "docx")

    def test_unknown_email(self):
        with self.assertRaises(ValueError):
            deliverables.row(self.con, 999999)

    def test_cowork_gets_the_pack_and_a_copy_of_the_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            att_dir = Path(tmp) / "att"
            (att_dir / "x").mkdir(parents=True)
            (att_dir / "x" / "Q3 plan.pptx").write_bytes(b"old deck")
            self.con.execute("INSERT INTO mail_attachments (item_id, graph_id, name, path, is_inline, text) VALUES (?, 'att-1', 'Q3 plan.pptx', 'x/Q3 plan.pptx', 0, 'Q3 milestones')",
                             (self.ask,))
            self.con.commit()
            opened = []
            saved = claude_open.WORKSPACE, claude_open.subprocess.run, mailsync.attachments_dir
            claude_open.WORKSPACE, claude_open.subprocess.run = Path(tmp) / "ws", lambda args, **k: opened.append(args)
            mailsync.attachments_dir = lambda: att_dir
            try:
                res = deliverables.open_in_claude(self.con, self.ask, {"format": "pptx", "title": "Q4 plan", "audience": "Rowan",
                                                                        "outline": ["Milestones", "Asks"], "prompt": "Build the Q4 plan.",
                                                                        "covers": ["milestones"], "gaps": ["headcount"]})
            finally:
                claude_open.WORKSPACE, claude_open.subprocess.run, mailsync.attachments_dir = saved
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(opened[0][1]).query)["q"][0]
            ctx = Path(res["context"]).read_text()
            self.assertIn("Can you show me the Q4 plan", ctx)
            self.assertIn("A PowerPoint deck: “Q4 plan”, for Rowan.", ctx)
            self.assertIn("Save it in this folder as “Q4 plan.pptx”", q)
            self.assertIn("Known gaps", q)
            self.assertEqual(res["sources"], ["Q3 plan.pptx"])                       # the attachment, as a working copy
            copy = Path(res["workspace"]) / "sources" / "Q3 plan.pptx"
            self.assertEqual(copy.read_bytes(), b"old deck")
            self.assertTrue((att_dir / "x" / "Q3 plan.pptx").exists())                # the original is untouched
            fb = self.con.execute("SELECT target_type, target_id, note FROM feedback").fetchone()
            self.assertEqual((fb["target_type"], fb["target_id"]), ("mail", str(self.ask)))

    def test_nothing_to_build(self):
        with self.assertRaises(ValueError):
            deliverables.open_in_claude(self.con, self.ask, {"format": "docx"})
