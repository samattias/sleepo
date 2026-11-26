"""Reply drafts saved into Outlook (assist/outlook_drafts.py): the email is found by its Message-ID, the reply is made by
Graph in the thread with the text above the quote, a second save updates the same draft over the same quote, a forward
needs a recipient, and nothing is ever sent. Graph is mocked.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import sqlite3
import unittest
from unittest import mock

from assist import outlook_drafts as od


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE mail_messages (item_id INTEGER, graph_id TEXT, subject TEXT)")
    con.execute("INSERT INTO mail_messages VALUES (7, 'am:CAJNYnkX5v=j9k@mail.gmail.com', 'Pricing')")
    from assist.migrations import m016_outlook_drafts
    m016_outlook_drafts.up(con)
    return con


QUOTE = "<html><body><div id='divRplyFwdMsg'>From: Quinn</div></body></html>"


class Graph:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, tok, body=None, params=None):
        self.calls.append((method, path, body, params))
        if method == "GET" and path == "/me/messages":
            return {"value": [{"id": "MSG1", "webLink": "https://outlook/orig"}]} if params["$filter"].endswith("'<CAJNYnkX5v=j9k@mail.gmail.com>'") else {"value": []}
        if method == "POST":
            return {"id": "DRAFT1", "body": {"content": QUOTE}, "ccRecipients": [{"emailAddress": {"address": "a@x.com"}}], "webLink": "https://outlook/draft"}
        if method == "GET":
            return {"id": "DRAFT1", "isDraft": True, "webLink": "https://outlook/draft"}
        return {"webLink": "https://outlook/draft"}


class Save(unittest.TestCase):
    def setUp(self):
        self.g = Graph()
        self.p = [mock.patch.object(od, "token", lambda: "t"), mock.patch.object(od, "_call", self.g)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_reply_is_made_in_the_thread_with_the_text_above_the_quote(self):
        con = _db()
        out = od.save(con, 7, "Hi Quinn,\n\nYes & agreed.\n\n-Sam", "reply")
        self.assertEqual(out, {"web_link": "https://outlook/draft", "updated": False})
        post = [c for c in self.g.calls if c[0] == "POST"][0]
        self.assertEqual(post[1], "/me/messages/MSG1/createReply")
        patch = [c for c in self.g.calls if c[0] == "PATCH"][0][2]["body"]["content"]
        self.assertLess(patch.index("Yes &amp; agreed."), patch.index("From: Quinn"))   # escaped, and above the quote
        self.assertFalse([c for c in self.g.calls if "send" in c[1].lower()])

    def test_a_second_save_updates_the_same_draft(self):
        con = _db()
        od.save(con, 7, "First", "reply")
        self.g.calls.clear()
        out = od.save(con, 7, "Second", "reply")
        self.assertTrue(out["updated"])
        self.assertFalse([c for c in self.g.calls if c[0] == "POST"])
        body = [c for c in self.g.calls if c[0] == "PATCH"][0][2]["body"]["content"]
        self.assertIn("Second", body)
        self.assertNotIn("First", body)
        self.assertIn("From: Quinn", body)

    def test_reply_all_adds_people_to_cc_and_forward_needs_a_recipient(self):
        con = _db()
        od.save(con, 7, "x", "replyall", ["rowan.lowell@acme.example", "not an address"])
        patch = [c for c in self.g.calls if c[0] == "PATCH"][0][2]
        self.assertEqual([r["emailAddress"]["address"] for r in patch["ccRecipients"]], ["a@x.com", "rowan.lowell@acme.example"])
        with self.assertRaises(ValueError):
            od.save(con, 7, "x", "forward", [])

    def test_message_ids(self):
        self.assertEqual(od.message_ids("am:abc@x"), ["<abc@x>", "abc@x"])
        self.assertEqual(od.to_html("a\nb\n\nc"), "<p>a<br>b</p><p>c</p>")


if __name__ == "__main__":
    unittest.main()
