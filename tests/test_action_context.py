"""Actions that show what they answer and act with context (assist/action_context.py): an action's sources resolved for the
page, the context pack Claude gets, and the Cowork hand-off (working copies, never the original).
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import urllib.parse
from pathlib import Path

from assist import action_context, claude_open, todo
from test_open_items import Base, ago

SAM = "sam.doe@acme.example"


class ActionContext(Base):
    def setUp(self):
        super().setUp()
        c = self.con
        c.execute("UPDATE people SET title='VP Development', manager_id=2 WHERE id=6")
        c.execute("UPDATE people SET is_me=1, title='Chief Product Officer' WHERE id=2")
        self.ask = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Org plan for 2026", 3, conv="c-org")
        c.execute("UPDATE mail_messages SET body_text=?, from_name='Rowan Lowell' WHERE item_id=?",
                  ("Hi Sam,\nCan you send me the proposed team structure and the budget for the new role?\n\n[Employee photo]<https://x>\nRowan Lowell\n"
                   "This email and any files transmitted with it are confidential", self.ask))
        self.reply = self.mail("sentitems", SAM, ["rowan.lowell@acme.example"], "RE: Org plan for 2026", 2, conv="1193")   # Apple Mail thread id
        c.execute("UPDATE mail_messages SET body_text='I will take you through it on Friday.' WHERE item_id=?", (self.reply,))
        cur = c.execute("INSERT INTO commitments (kind, title, counterparty, status, created_at) VALUES ('owed_by_me', 'Take Rowan through the 2026 org plan', 'Rowan Lowell', 'open', ?)",
                        (ago(2),))
        c.execute("INSERT INTO fact_sources (fact_type, fact_id, item_id) VALUES ('commitment', ?, ?)", (cur.lastrowid, self.reply))
        self.lid = self.loop("promise", "Take Rowan through the 2026 org plan", days=2, person=1, fact_id=cur.lastrowid)
        c.execute("UPDATE loops SET links_json=? WHERE id=?", (json.dumps([{"label": "Mail", "url": f"#/mail?open={self.reply}", "item_id": self.reply}]), self.lid))
        self.actions = [{"type": "create", "label": "Build the org deck", "app": "cowork", "format": "pptx", "title": "2026 org plan",
                         "audience": "Rowan", "outline": ["Today's structure", "Proposed structure", "Budget for the role"], "prompt": "A short walk-through."},
                        {"type": "email", "label": "Reply to Rowan", "reply_to": f"G{self.ask}", "intent": "Confirm Friday", "body": "Hi Rowan, Friday works. -Sam"}]
        c.execute("INSERT INTO todo (id, rank, priority, category, title, why, sources_json, actions_json, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  ("t1", 1, "today", "content", "Build the 2026 org plan for Rowan", "Rowan asked on Monday.",
                   json.dumps([{"ref": f"L{self.lid}", "label": "Open item", "url": "#/loops", "loop_id": self.lid, "closes": True},
                               {"ref": f"E{self.ask}", "label": "Mail", "url": "#", "item_id": self.ask, "closes": False}]),
                   json.dumps(self.actions), "open", ago(0), ago(0)))
        c.commit()

    def row(self):
        return self.con.execute("SELECT * FROM todo WHERE id='t1'").fetchone()

    def test_sources_show_the_email_and_lead_with_what_it_answers(self):
        src = action_context.sources(self.con, self.row())
        self.assertEqual([s["kind"] for s in src], ["item", "email"])
        item, email = src
        self.assertEqual(item["emails"][0], self.ask)   # the source is Sam's own reply: the request he answered comes first
        self.assertEqual(item["email"]["from"]["name"], "Rowan Lowell")
        self.assertIn("proposed team structure", email["text"])
        self.assertNotIn("Employee photo", email["text"])   # the signature block is cut
        self.assertEqual(email["graph_id"], f"G{self.ask}")

    def test_pack_carries_the_request_the_org_and_no_signatures(self):
        md, docs = action_context.pack(self.con, self.row(), self.actions[0])
        self.assertIn("A PowerPoint deck: “2026 org plan”, for Rowan.", md)
        self.assertIn("Can you send me the proposed team structure", md)   # the request, found through the item's source
        self.assertIn("Gray Selby · VP Development", md)                   # Sam's organisation
        self.assertNotIn("files transmitted with it", md)
        self.assertIn("3. Budget for the role", md)

    def test_cowork_gets_a_context_file_and_a_copy_never_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "Org Proposal.pptx"
            original.write_bytes(b"deck")
            self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('local', 'local', 'l')")
            self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at, subject) VALUES (900, 'local', ?, 'doc', ?, ?, 'Org Proposal.pptx')",
                             (f"file:{original}", ago(5), ago(5)))
            acts = json.loads(self.row()["actions_json"])
            acts[0]["doc"] = "lf-900"
            self.con.execute("UPDATE todo SET actions_json=? WHERE id='t1'", (json.dumps(acts),))
            self.con.commit()
            opened = []
            ws_root, run = claude_open.WORKSPACE, claude_open.subprocess.run
            claude_open.WORKSPACE, claude_open.subprocess.run = Path(tmp) / "ws", lambda args, **k: opened.append(args)
            try:
                res = action_context.act(self.con, "t1", 0)
            finally:
                claude_open.WORKSPACE, claude_open.subprocess.run = ws_root, run
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(opened[0][1]).query)
            self.assertTrue(Path(res["context"]).read_text().startswith("# Context for “2026 org plan”"))
            self.assertNotEqual(Path(q["file"][0]), original)                  # a working copy is attached
            self.assertEqual(Path(q["file"][0]).read_bytes(), b"deck")
            self.assertEqual(res["start_from"], "Org Proposal.pptx")
            self.assertIn("Save it in this folder as “2026 org plan.pptx”", q["q"][0])
            self.assertIn("SleePO context.md", q["q"][0])
            with self.assertRaises(ValueError):   # an email step is not opened in Claude
                action_context.act(self.con, "t1", 1)

    def test_new_action_fields_are_kept_clean(self):
        acts = todo._clean_actions([{"type": "create", "label": "Deck", "format": "keynote", "outline": "not a list", "doc": "lf-999", "title": ""},
                                    {"type": "create", "label": "Doc", "format": "docx", "outline": ["A", "", "B"], "doc": "lf-900"},
                                    {"type": "email", "label": "Reply", "reply_to": "x", "intent": "Say yes"}], known_docs={"lf-900"})
        self.assertNotIn("format", acts[0]); self.assertNotIn("outline", acts[0]); self.assertNotIn("doc", acts[0]); self.assertNotIn("title", acts[0])
        self.assertEqual((acts[1]["format"], acts[1]["outline"], acts[1]["doc"]), ("docx", ["A", "B"], "lf-900"))
        self.assertEqual(acts[2]["intent"], "Say yes")
