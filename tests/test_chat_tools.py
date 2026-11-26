"""The chat's file tools (assist/chat_tools.py) and its workspace guard: Office files read with their numbers, files made only
inside the conversation's folder, originals never edited, paths outside the allowed places refused.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import os
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock
from pathlib import Path

from assist import chat, chat_tools, claude_open


class ChatTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.docs, self.space = root / "Documents", root / "SleePO Workspace"
        self.ws = self.space / "2026-10-14 chat test"
        for d in (self.docs, self.ws):
            d.mkdir(parents=True)
        self.saved = chat_tools.FILE_ROOTS, claude_open.WORKSPACE, os.environ.get("ASSIST_CHAT_WORKSPACE")
        chat_tools.FILE_ROOTS = [self.docs, self.space]
        claude_open.WORKSPACE = self.space
        os.environ["ASSIST_CHAT_WORKSPACE"] = str(self.ws)

    def tearDown(self):
        chat_tools.FILE_ROOTS, claude_open.WORKSPACE, env = self.saved
        if env is None:
            os.environ.pop("ASSIST_CHAT_WORKSPACE", None)
        else:
            os.environ["ASSIST_CHAT_WORKSPACE"] = env
        self.tmp.cleanup()

    def test_excel_round_trip_keeps_numbers(self):
        (self.ws / "deals.csv").write_text('Account,ACV\nKnapp,120000\n"Sun, Planning",45000.5\n')
        self.assertIn("Made", chat_tools.ask_make("deals.csv", "xlsx"))
        text = chat_tools.ask_file(str(self.ws / "deals.xlsx"))
        self.assertIn("Knapp\t120000", text)
        self.assertIn("Sun, Planning\t45000.5", text)

    def test_word_from_markdown(self):
        (self.ws / "memo.md").write_text("# Plan\n\nA **bold** point.\n\n- one\n- two\n\n| Region | ACV |\n|---|---|\n| EMEA | 537 |\n")
        self.assertIn("Made", chat_tools.ask_make("memo.md", "docx"))
        text = chat_tools.ask_file(str(self.ws / "memo.docx"))
        for want in ("Plan", "A bold point.", "one", "EMEA"):
            self.assertIn(want, text)
        self.assertFalse(list(self.ws.glob("*.tmp.html")))                  # the working HTML is removed

    def test_files_are_made_only_in_the_workspace(self):
        outside = self.docs / "notes.md"
        outside.write_text("# x")
        self.assertIn("inside the workspace", chat_tools.ask_make(str(outside), "docx"))
        self.assertFalse((self.docs / "notes.docx").exists())
        os.environ["ASSIST_CHAT_WORKSPACE"] = str(self.docs)                   # a folder that is not a SleePO workspace
        self.assertIn("no workspace", chat_tools.ask_make("notes.md", "docx"))
        os.environ["ASSIST_CHAT_WORKSPACE"] = str(self.space)                  # nor the workspace root itself
        self.assertIsNone(chat_tools.workspace())

    def test_copy_never_touches_the_original(self):
        src = self.docs / "JD.md"
        src.write_text("original")
        self.assertIn("Copied", chat_tools.ask_copy(str(src)))
        self.assertIn("Copied", chat_tools.ask_copy(str(src)))
        self.assertEqual(sorted(p.name for p in self.ws.iterdir()), ["JD (2).md", "JD.md"])
        self.assertEqual(src.read_text(), "original")

    def test_reading_is_limited_to_the_allowed_places(self):
        self.assertIn("outside", chat_tools.ask_file("/etc/hosts"))
        hr = self.docs / "HR investigation"
        hr.mkdir()
        (hr / "a.txt").write_text("x")
        self.assertIn("excluded", chat_tools.ask_file(str(hr / "a.txt")))
        (self.docs / "~$Plan.docx").write_text("lock")
        self.assertIn("lock file", chat_tools.ask_file(str(self.docs / "~$Plan.docx")))

    def test_made_files_and_hidden_blocks(self):
        t0 = time.time()
        (self.ws / "brief.docx").write_bytes(b"x")
        (self.ws / "~$brief.docx").write_bytes(b"x")
        (self.ws / "brief.tmp.html").write_text("x")
        self.assertEqual([f["name"] for f in chat._made(self.ws, t0)], ["brief.docx"])
        answer = "Done.\n\n```changes\n[{\"type\": \"loop\", \"id\": 1, \"status\": \"done\"}]\n```\n\n```followups\n[\"Next?\"]\n```\n"
        self.assertEqual(chat.FOLLOWUPS.sub("", answer).strip(), "Done.")


class ReadByLink(unittest.TestCase):
    """ask-read opens what search returns (17 Nov 2026: a product docs page, /explore/library/pd/docs/….md, could not be
    opened, only its last path part was looked up)."""

    def setUp(self):
        from assist import db
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.environ.get("ASSIST_DB")
        os.environ["ASSIST_DB"] = str(Path(self.tmp.name) / "t.db")
        con = db.connect()
        db.migrate(con)
        con.execute("INSERT INTO documents (id, section, title, path, body_md) VALUES (?,?,?,?,?)",
                    ("pd/docs/desktop-client/about-the-desktop-client.md", "Product docs", "About the desktop client",
                     "public-docs/docs/desktop-client/about-the-desktop-client.md", "# About the desktop client\n\nThe client models processes."))
        con.execute("INSERT INTO documents (id, section, title, path, body_md) VALUES (?,?,?,?,?)",
                    ("about-the-desktop-client.md", "Library", "Wrong one", "", "not this"))
        con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('acme-kb', 'acme-kb', 'Knowledge base')")
        con.execute("INSERT INTO items (id, source_id, external_id, kind, ts, pulled_at, subject, text) VALUES (?,?,?,?,?,?,?,?)",
                    (12, "acme-kb", "Products/Copilot.md", "doc", "2026-11-17T09:00:00Z", "2026-11-17T09:00:00Z", "Copilot", "Copilot drafts models."))
        con.commit()
        con.close()

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("ASSIST_DB", None)
        else:
            os.environ["ASSIST_DB"] = self.saved
        self.tmp.cleanup()

    def test_a_product_docs_page_opens_from_its_search_link(self):
        for ref in ("/explore/library/pd/docs/desktop-client/about-the-desktop-client.md",
                    "#/explore/library/pd/docs/desktop-client/about-the-desktop-client.md",
                    "pd/docs/desktop-client/about-the-desktop-client.md",
                    "/explore/library/pd%2Fdocs%2Fdesktop-client%2Fabout-the-desktop-client.md"):
            out = chat_tools.ask_read(ref)
            self.assertIn("The client models processes.", out, ref)

    def test_a_knowledge_base_note_opens_by_ref_or_link(self):
        for ref in ("kb-12", "doc:kb-12", "#doc:kb-12"):
            self.assertIn("Copilot drafts models.", chat_tools.ask_read(ref), ref)

    def test_an_unknown_reference_says_so(self):
        self.assertIn("Nothing found", chat_tools.ask_read("/explore/library/pd/docs/nope.md"))


if __name__ == "__main__":
    unittest.main()


class Handoff(unittest.TestCase):
    """Continue in Claude Desktop opens Cowork on the folder the conversation and its files are in (23 Nov 2026: it opened a
    second, empty folder named after the title, and Claude said it could not see conversation.md or the sources)."""

    def setUp(self):
        from assist import db, claude_open
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.environ.get("ASSIST_DB")
        os.environ["ASSIST_DB"] = str(Path(self.tmp.name) / "t.db")
        self.patch = mock.patch.object(claude_open, "WORKSPACE", Path(self.tmp.name) / "SleePO Workspace")
        self.patch.start()
        con = db.connect()
        db.migrate(con)
        con.close()

    def tearDown(self):
        self.patch.stop()
        if self.saved is None:
            os.environ.pop("ASSIST_DB", None)
        else:
            os.environ["ASSIST_DB"] = self.saved
        self.tmp.cleanup()

    def test_cowork_opens_on_the_conversations_own_folder(self):
        from assist import chat, claude_open
        c = chat._con()
        chat.ensure_schema(c)
        title = "Go through all of my documents and put together an inventory"
        c.execute("INSERT INTO chat_threads (id, title, created_at, updated_at) VALUES ('t1', ?, '2026-11-23T10:00:00Z', '2026-11-23T10:00:00Z')", (title,))
        ws = chat._workspace(c, "t1", title)
        (ws / "Data room inventory.xlsx").write_bytes(b"x")
        c.execute("INSERT INTO chat_turns (thread_id, role, text, created_at) VALUES ('t1', 'user', ?, '2026-11-23T10:00:00Z')", (title,))
        c.execute("INSERT INTO chat_turns (thread_id, role, text, made_json, created_at) VALUES ('t1', 'assistant', 'Here it is.', ?, '2026-11-23T10:01:00Z')",
                  ('[{"name": "Data room inventory.xlsx", "size": 1}]',))
        c.commit()
        c.close()
        opened = []
        with mock.patch.object(claude_open.subprocess, "run", lambda cmd, **k: opened.append(cmd[-1])):
            out = chat.handoff("t1", "Trim the decks")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(opened[0]).query)
        self.assertEqual(q["folder"], [str(ws)])                       # the folder the files are in, not a new one
        self.assertTrue((ws / "conversation.md").is_file())
        self.assertIn("Data room inventory.xlsx", q["q"][0])
        self.assertIn("Data room inventory.xlsx", out["files"])
        self.assertEqual([d.name for d in claude_open.WORKSPACE.iterdir()], [ws.name])   # no second, empty folder
