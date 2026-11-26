"""Emails in Ask SleePO (assist/chat.py): Sam's edits to an email the chat wrote are kept with the conversation, come back
with it, and go to the chat once, with his next question, so a revision starts from his version.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import chat, claude_open, db
from assist.promptkit import USER


class ChatDrafts(unittest.TestCase):
    def setUp(self):
        _t = mock.patch.object(chat, "summarize_later", lambda tid: None)   # no real Claude call to name a conversation
        _t.start()
        self.addCleanup(_t.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(self.tmp.name) / "t.db")})
        self.env.start()
        c = db.connect()
        db.migrate(c)
        chat.ensure_schema(c)
        c.close()
        self.saved = claude_open.WORKSPACE
        claude_open.WORKSPACE = Path(self.tmp.name) / "ws"
        answer = "```email\nTo: Gray Selby <gray.selby@acme.example>\nSubject: Team B budget\n\nHi Gray,\nCan you send it by Friday?\n-Sam\n```"
        self.tid = chat.seed("Email to Gray", "Draft an email to Gray", answer, "context")

    def tearDown(self):
        claude_open.WORKSPACE = self.saved
        self.env.stop()
        self.tmp.cleanup()

    def test_edits_are_kept_and_come_back_with_the_conversation(self):
        chat.save_draft(self.tid, "1:0", {"to": "Gray Selby <gray.selby@acme.example>", "subject": "Team B budget by Friday",
                                          "body": "Hi Gray,\nPlease send it by Friday.\n-Sam"})
        t = chat.thread(self.tid)
        self.assertEqual(t["drafts"]["1:0"]["subject"], "Team B budget by Friday")
        self.assertFalse(t["drafts"]["1:0"]["sent"])
        f = chat._drafts_file(self.tid)
        self.assertTrue(f.name.startswith("."))   # hidden: not listed as a file the chat made

    def test_edits_go_to_the_chat_once(self):
        chat.save_draft(self.tid, "1:0", {"to": "Gray Selby <gray.selby@acme.example>", "subject": "Team B budget", "body": "Hi Gray,\nPlease send it by Friday.\n-Sam"})
        chat.save_draft(self.tid, "3:0", {"mail": 42, "body": "Thanks, will do.\n-Sam"})
        note = chat._edits_note(self.tid)
        self.assertIn(f"{USER.first} edited these drafts", note)
        self.assertIn("```email\nTo: Gray Selby <gray.selby@acme.example>\nSubject: Team B budget\n\nHi Gray,\nPlease send it by Friday.", note)
        self.assertIn("```email 42\nThanks, will do.", note)   # a reply keeps its email id and no header lines
        self.assertEqual(chat._edits_note(self.tid), "")       # passed on once
        chat.save_draft(self.tid, "1:0", {"body": "Hi Gray,\nBy Friday please.\n-Sam"})
        self.assertIn("this draft", chat._edits_note(self.tid))   # a later edit goes again

    def test_a_teams_reply_goes_back_as_a_teams_block(self):
        # a reply in Teams the chat wrote (```teams <item id>), e.g. with a reviewed deck (assist/file_review.py)
        chat.save_draft(self.tid, "2:0", {"kind": "teams", "item": 12628, "body": "Hi Tatum, updated deck attached.\nSam"})
        self.assertIn("```teams 12628\nHi Tatum, updated deck attached.\nSam\n```", chat._edits_note(self.tid))

    def test_an_outlook_save_is_not_an_edit(self):
        chat.save_draft(self.tid, "1:0", {"outlook_id": "AAMk1", "outlook_link": "https://outlook.office.com/x", "edited": False})
        d = chat.drafts(self.tid)["1:0"]
        self.assertEqual(d["outlook_id"], "AAMk1")
        self.assertNotIn("edited_at", d)
        self.assertEqual(chat._edits_note(self.tid), "")

    def test_bad_key_or_conversation(self):
        with self.assertRaises(ValueError):
            chat.save_draft(self.tid, "../x", {"body": "x"})
        with self.assertRaises(LookupError):
            chat.save_draft("nope", "1:0", {"body": "x"})


if __name__ == "__main__":
    unittest.main()
