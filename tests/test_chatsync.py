"""Teams and Slack messages (assist/chatsync.py): a message a later pull names under another id is the same message, not a
second copy. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import tempfile
import unittest
from pathlib import Path

from assist import chatsync, db


class StoreRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('slack', 'slack', 's')")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def rec(self, ext, body="can you review the deck?", ts="2026-10-07T16:37:27Z", author="Gray Selby"):
        return chatsync.store_record(self.con, {"source_id": "slack", "external_id": ext, "conversation_name": "DM Gray Selby",
                                                "conversation_kind": "dm", "ts": ts, "author": author, "body_text": body})

    def test_same_message_under_another_id(self):
        a = self.rec("slack:D5BFNA0NEDF:1791391047.389929")
        self.assertEqual(self.rec("D5BFNA0NEDF:1791391047.389929"), a)          # the prefix dropped
        self.assertEqual(self.rec("slack:dm-gray:20261007T163727"), a)           # a made-up id
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 1)

    def test_different_messages_stay_apart(self):
        a = self.rec("x1")
        self.assertNotEqual(self.rec("x2", body="and the pricing page"), a)              # same second, other text
        self.assertNotEqual(self.rec("x3", ts="2026-10-07T16:37:28Z"), a)                 # same text, another second
        self.assertNotEqual(self.rec("x4", author="Rowan Lowell"), a)                         # same text and second, another sender

    def test_a_repull_without_attachments_keeps_them(self):
        # Teams search returns no attachments; only reading the message does (29 Oct 2026)
        deck = {"name": "Q2 report.pptx", "content_type": "reference", "url": "https://acmellc-my.sharepoint.com/personal/j/Documents/Q2%20report.pptx"}
        a = chatsync.store_record(self.con, {"source_id": "slack", "external_id": "x1", "conversation_kind": "dm", "ts": "2026-10-28T17:37:12Z",
                                             "author": "Tatum Easton", "body_text": "can you review this deck?", "attachments": [deck]})
        self.rec("x1", author="Tatum Easton", ts="2026-10-28T17:37:12Z", body="can you review this deck?")
        self.assertEqual([r[0] for r in self.con.execute("SELECT name FROM chat_attachments WHERE item_id=?", (a,))], ["Q2 report.pptx"])


class Latest(unittest.TestCase):
    """Today's Messages widget (Sam, 30 Oct 2026): the conversations Sam reads, newest first, each with its newest message."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        for s in ("slack", "teams"):
            self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES (?, ?, ?)", (s, s, s))
        for i, n in ((6, "Gray Selby"), (7, "Kai Sutton")):
            self.con.execute("INSERT INTO people(id, name) VALUES (?, ?)", (i, n))
            self.con.execute("INSERT INTO people_aliases VALUES (?, ?)", (n.lower(), i))
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def msg(self, app, conv, name, kind, author, body, mins_ago, **extra):
        from datetime import datetime, timedelta, timezone
        self.n += 1
        ts = (datetime.now(timezone.utc) - timedelta(minutes=mins_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return chatsync.store_record(self.con, {"source_id": app, "external_id": f"{app}:{self.n}", "conversation_id": conv, "conversation_name": name,
                                                "conversation_kind": kind, "ts": ts, "author": author, "body_text": body, **extra})

    def test_conversations_newest_first_one_per_person(self):
        self.msg("teams", "t-gray", "1:1 chat Gray Selby", "dm", "Gray Selby", "can you look at the MCP pricing?", 300)
        gray = self.msg("slack", "s-gray", "DM Gray", "dm", "Sam Doe", "Hi Gray, yes, on it this afternoon.", 60)
        japan = self.msg("teams", "g-1", "work trip (group)", "group", "Kai Sutton",
                         "Ellis Ingram  I followed up with the venue…  The keynote deck is final: [deck](https://x.sharepoint.com/deck.pptx)", 30)
        self.msg("teams", "g-1", "Kai Sutton (group chat)", "group", "Kai Sutton", "See you in Lisbon", 600)
        self.msg("teams", "g-2", "Group chat (b29b96d0)", "group", "Orin Denton", "thanks", 120)
        self.msg("teams", "c-1", "Teams channel (Slack Bridge)", "channel", "Slack Bridge", "[slack] a build finished", 10)   # not followed
        self.msg("slack", "c-2", "#product-steering", "channel", "Rowan Lowell", "v16 compatibility", 200)                       # followed
        db.set_setting(self.con, "followed_channels", '["#product-steering"]')   # the user's followed channels (a setting; no default)
        self.msg("teams", "t-old", "DM Rowan", "dm", "Rowan Lowell", "last month", 60 * 24 * 10)                                     # out of the window
        before = self.con.total_changes
        xs = chatsync.latest(self.con, 7)
        self.assertEqual(self.con.total_changes, before)                                                                         # reads only
        self.assertEqual([x["title"] for x in xs], ["work trip", "Gray Selby", "Group chat with Glen", "#product-steering"])
        j, n = xs[0], xs[1]
        self.assertEqual((j["item_id"], j["count"], j["mine"]), (japan, 2, False))
        self.assertEqual(j["text"], "The keynote deck is final: deck")                     # the Teams quote and the address gone
        self.assertEqual((n["item_id"], n["apps"], n["count"], n["mine"]), (gray, ["slack", "teams"], 2, True))
        self.assertEqual(n["text"], "yes, on it this afternoon.")

    def test_one_title_per_chat_however_the_pulls_named_it(self):
        """Sam, 17 Nov 2026: one group chat stored under nine names showed as nine rows. The Messages page now keys group chats
        by id with one title: the topic in the newest name, else who writes in it (most active first), never an id fragment."""
        for i, n in ((8, "Harper Brook"), (9, "Rowan Lowell")):
            self.con.execute("INSERT INTO people(id, name) VALUES (?, ?)", (i, n))
        self.msg("teams", "g-6db", "Teams group chat 6db63e", "group", "Rowan Lowell", "fonts?", 300)
        self.msg("teams", "g-6db", "Rowan Lowell + 4 (group chat)", "group", "Harper Brook", "custom fonts work", 200)
        self.msg("teams", "g-6db", "Gray Selby chat", "group", "Gray Selby", "ok", 150)
        self.msg("teams", "g-6db", "Group chat: Harper Brook", "group", "Harper Brook", "shipped", 100)
        self.msg("teams", "g-copilot", "Group chat (Copilot+)", "group", "Gray Selby", "old name", 90)
        self.msg("teams", "g-copilot", "Group chat: Copilot+ (Gray Selby, Kai Sutton)", "group", "Kai Sutton", "pricing", 80)
        self.msg("teams", "19:meeting_MThlNjBkMWQ@example.org", "Meeting chat MThlNjBk", "group", "Butler, Tom", "slides", 70)
        self.msg("teams", "g-new", "Group chat with Milo Marsh", "group", "Milo Marsh", "Dear Team", 5)
        before = self.con.total_changes
        t = chatsync.chat_titles(self.con, ["g-6db", "g-copilot", "19:meeting_MThlNjBkMWQ@example.org", "g-new", None])
        self.assertEqual(self.con.total_changes, before)                                                                         # reads only
        self.assertEqual(t, {"g-6db": "Harper, Gray, Rowan", "g-copilot": "Copilot+", "19:meeting_MThlNjBkMWQ@example.org": "Meeting chat · Tom",
                             "g-new": "Group chat · Milo"})   # a tie: the latest first; one person so far is still a group chat


if __name__ == "__main__":
    unittest.main()
