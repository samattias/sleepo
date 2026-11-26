"""Files shared in Teams chats (assist/chat_files.py): which ones are read (direct and group chats, a readable format, not held
yet, never one person's HR matters, three tries) and how what the run read is stored, so the attachment counts as read.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import chat_files, chatsync, db, links

DECK = "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/Microsoft%20Teams%20Chat%20Files/Q2%20report.pptx"


class ChatFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        self.addCleanup(self.con.close)
        db.migrate(self.con)
        p = mock.patch.object(chat_files, "TRIED", Path(self.tmp.name) / "chat_files.json")
        p.start()
        self.addCleanup(p.stop)
        for s in ("teams", "sharepoint"):
            self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES (?, ?, ?)", (s, s, s))
        self.n = 0

    def msg(self, name, url, body=None, kind="dm", author="Tatum Easton", ts=None):
        self.n += 1
        body = body or f"can you review {name}?"   # one text each: the same text in the same second is one message (chatsync)
        ts = ts or db.now()
        iid = chatsync.store_record(self.con, {"source_id": "teams", "external_id": f"m{self.n}", "conversation_name": "Chat", "conversation_kind": kind,
                                               "ts": ts, "author": author, "body_text": body, "attachments": [{"name": name, "url": url}]})
        return self.con.execute("SELECT id FROM chat_attachments WHERE item_id=?", (iid,)).fetchone()[0]

    def test_which_files_are_read(self):
        deck = self.msg("Q2 report.pptx", DECK)
        self.msg("notes.docx", "https://acmellc.sharepoint.com/sites/x/Shared%20Documents/notes.docx", kind="channel")   # a channel post
        self.msg("Dates d'arrêts maladie 2026.xlsx", "https://acmellc-my.sharepoint.com/personal/l/Documents/arrets.xlsx", kind="group")   # HR
        self.msg("plan.xlsx", "https://acmellc-my.sharepoint.com/personal/n/Documents/plan.xlsx", body="his salary change for 2026", kind="group")   # HR, by the message
        self.msg("photo.png", "https://acmellc-my.sharepoint.com/personal/n/Documents/photo.png")   # not a document
        self.msg("old.pptx", "https://acmellc-my.sharepoint.com/personal/n/Documents/old.pptx", ts="2026-01-02T10:00:00Z")   # too old
        self.assertEqual([c["attachment_id"] for c in chat_files.candidates(self.con)], [deck])
        chat_files.TRIED.write_text(json.dumps({DECK: 3}))   # three failed tries: left alone
        self.assertEqual(chat_files.candidates(self.con), [])

    def test_a_read_file_is_stored_and_counts_as_read(self):
        deck = self.msg("Q2 report.pptx", DECK)
        n = chat_files.store(self.con, [{"attachment_id": deck, "uri": "file:///b!d/01AB", "driveId": "b!d", "id": "01AB",
                                         "webUrl": "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/Microsoft Teams Chat Files/Q2 report.pptx",
                                         "lastModifiedDateTime": "2026-10-26T22:35:48Z", "text": "Quarterly operations report. " * 30}])
        self.assertEqual(n, 1)
        r = self.con.execute("SELECT subject, from_name, payload FROM items WHERE source_id='sharepoint' AND external_id='01AB'").fetchone()
        self.assertEqual((r["subject"], r["from_name"], json.loads(r["payload"])["uri"]), ("Q2 report.pptx", "Tatum Easton", "file:///b!d/01AB"))
        self.assertTrue(links.is_held(links.held(self.con), DECK))
        self.assertEqual(chat_files.candidates(self.con), [])

    def test_a_file_is_read_by_path_when_its_library_is_known(self):
        # another file of Tatum's OneDrive gives its driveId; a quoted file name finds nothing in search, plain words do
        self.con.execute("INSERT INTO items(source_id, external_id, kind, ts, pulled_at, subject, url, payload) VALUES ('sharepoint', 'x', 'doc', ?, ?, 'a.docx', ?, ?)",
                         (db.now(), db.now(), "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/Shared/a.docx?web=1", json.dumps({"driveId": "b!J"})))
        self.assertEqual(chat_files.path_uri(self.con, DECK), "file:///b!J/Microsoft Teams Chat Files/Q2 report.pptx")
        self.assertIsNone(chat_files.path_uri(self.con, "https://acmellc-my.sharepoint.com/personal/someone_else/Documents/b.pptx"))
        self.assertEqual(chat_files.search_words("Milo Marsh - CTS Contoso LIVE 2025 - Final v2.pptx"), "Milo Marsh CTS Contoso LIVE 2025 Final")


if __name__ == "__main__":
    unittest.main()
