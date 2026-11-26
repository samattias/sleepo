"""Teams and Slack reply drafts (assist/chat_reply.py): the prompt carries the conversation in order, Sam's chat voice for the
right app, his own chat messages as style, and no email sign-off. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import tempfile
import unittest
from pathlib import Path

from assist import chat_reply, db
from test_open_items import ago


class ChatReply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('teams', 'teams', 't'), ('slack', 'slack', 's')")
        self.con.execute("INSERT INTO people(id, name, title) VALUES (6, 'Gray Selby', 'VP Development')")
        self.con.execute("INSERT INTO people_aliases VALUES ('gray selby', 6)")
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def msg(self, source, frm, days, body=None, gist="a summary"):
        self.n += 1
        i = self.con.execute("INSERT INTO items (source_id, external_id, kind, ts, from_name, thread, text, pulled_at) VALUES (?,?,?,?,?,?,?,?)",
                             (source, f"x{self.n}", "chat", ago(days), frm, "DM Gray Selby", gist, ago(0))).lastrowid
        if body is not None:
            self.con.execute("INSERT INTO chat_messages (item_id, source_id, external_id, conversation_kind, author, sent_at, body_text) VALUES (?,?,?,?,?,?,?)",
                             (i, source, f"x{self.n}", "dm", frm, ago(days), body))
        self.con.commit()
        return i

    def test_prompt(self):
        a = self.msg("slack", "Gray Selby", 2, "can you review the AMA deck before Friday?")
        b = self.msg("slack", "Sam Doe", 1.5, "sure, will do tonight")
        c = self.msg("slack", "Gray Selby", 1, None, gist="Gray asks whether pricing is in scope")
        t = self.msg("teams", "Gray Selby", 1, "a Teams message, not this conversation")
        p, last = chat_reply.prompt(self.con, [a, b, c, t], "slack", "Say yes", None, 2)
        ctx = p.split("\n<context>\n")[1].split("\n</context>")[0]
        self.assertEqual(last, b)                                                     # the summary-only row is not a message
        self.assertLess(ctx.index("AMA deck"), ctx.index("will do tonight"))          # oldest first
        self.assertNotIn("pricing", ctx)                                              # raw messages only, no summaries
        self.assertNotIn("a Teams message", ctx)                                      # only the app replied in
        self.assertIn("Gray Selby · VP Development", ctx)
        self.assertIn("# How Sam writes in Slack", ctx)
        self.assertIn('no sign-off and no "-Sam"', p)
        self.assertIn("one or two short lines", p.lower())
        self.assertIn("Say yes", p)

    def test_nothing_to_reply_to(self):
        self.assertEqual(chat_reply.prompt(self.con, [999], "teams"), (None, None))
        with self.assertRaises(ValueError):
            chat_reply.start(self.con, [1], "email", "", ".")


if __name__ == "__main__":
    unittest.main()
