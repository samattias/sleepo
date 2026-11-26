"""Ask SleePO's chips open what they name and show it on hover (assist/page_context.py href, assist/chip_preview.py; Sam,
17 Nov 2026: "click on them and go back to the context or ... hover over them and see a snapshot of the context"). Temp
database; nothing runs Claude."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import chat, db, profile, chip_preview as C, page_context as P


class Chips(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(self.tmp.name) / "t.db")})
        self.env.start()
        self.con = db.connect()
        db.migrate(self.con)
        profile.save(self.con, full_name="Milo Rio", emails=["milo.ray@example.com"])
        profile.reload()
        self.con.execute("INSERT INTO initiatives (slug, name, weight, goal, updated_at) VALUES ('platform', 'Platform', 5, 'Three paying customers', ?)", (db.now(),))
        self.con.execute("INSERT INTO people (id, name, title, updated_at) VALUES (7, 'Jordan Noel', 'VP Sales', ?)", (db.now(),))
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.env.stop()
        profile.reload()
        self.tmp.cleanup()

    def say(self, n, at, who, text, conv="DM S. Jordan Noel"):
        iid, _ = db.upsert_item(self.con, "teams", f"msg:{n}", "message", at, subject=conv)
        self.con.execute("INSERT INTO chat_messages (item_id, source_id, external_id, conversation_id, conversation_name, conversation_kind, author, sent_at, body_text)"
                         " VALUES (?, 'teams', ?, 'c1', ?, 'dm', ?, ?, ?)", (iid, f"msg:{n}", conv, who, at, text))
        return iid

    def test_every_chip_opens_the_page_it_came_from(self):
        """The chip's address is the inverse of the one the floating button reads it from."""
        msg = self.say(1, "2026-11-16T10:00:00Z", "S. Jordan Noel", "Can you look at the deck?")
        task = self.con.execute("INSERT INTO tasks (title, status, created_at, updated_at) VALUES ('Price the PLT packs', 'open', ?, ?)", (db.now(), db.now())).lastrowid
        self.con.execute("INSERT INTO meetings (id, title, starts_at, status) VALUES (4, 'Product review', '2026-11-16T14:00:00Z', 'analysed')")
        db.upsert_item(self.con, "calendar", "evt+/1=", "event", "2026-11-18T15:00:00Z", subject="Pricing review", payload={"attendees": []})
        self.con.execute("INSERT INTO orgs (id, name, kind, relation) VALUES (3, 'Acme Corp', 'partner', 'partner')")
        self.con.commit()
        for kind, ref in (("message", str(msg)), ("initiative", "platform"), ("person", "7"), ("task", str(task)), ("meeting", "4"),
                          ("event", "evt+/1="), ("company", "3")):
            c = P.chip(self.con, kind, ref)
            self.assertTrue(c["href"].startswith("/"), kind)
            back = P.resolve(self.con, c["href"])
            self.assertEqual((back["kind"], back["ref"]), (kind, ref), c["href"])
        self.assertEqual(P.href("person", "7"), "/people/p-7")
        self.assertEqual(P.href("meeting", "4"), "/meetings?open=m-4")   # the meeting's panel on the calendar
        self.assertEqual(P.href("file", "/etc/passwd"), "")

    def test_a_conversation_shows_its_last_messages_once_each(self):
        self.say(1, "2026-11-16T09:00:00Z", "Milo Rio", "Yes, this evening")
        self.say(2, "2026-11-16T10:00:00Z", "S. Jordan Noel", "Great, thanks")
        self.say(3, "2026-11-16T10:00:01Z", "S. Jordan Noel", "Great, thanks...")   # the same message stored by two pulls
        last = self.say(4, "2026-11-16T11:00:00Z", "S. Jordan Noel", "Please review the deck")
        p = C.preview(self.con, "message", str(last))
        self.assertEqual([(x["who"], x["text"]) for x in p["lines"]],
                         [("You", "Yes, this evening"), ("Jordan", "Great, thanks"), ("Jordan", "Please review the deck")])
        self.assertEqual(p["kicker"], "Teams · direct message")
        self.assertEqual(p["lines_label"], "Latest messages")
        older = C.preview(self.con, "message", str(self.con.execute("SELECT item_id FROM chat_messages WHERE external_id='msg:1'").fetchone()[0]))
        self.assertIn(["Since then", "2 newer messages"], older["facts"])   # duplicates still count as stored: the card names newer ones

    def test_an_email_shows_its_thread_and_the_draft(self):
        from assist import reply_working
        iid, _ = db.upsert_item(self.con, "outlook.inbox", "mail:1", "mail", "2026-11-16T10:00:00Z", subject="Pricing")
        self.con.execute("INSERT INTO mail_messages (item_id, graph_id, folder, from_name, from_address, to_json, subject, received_at, body_text, synced_at) VALUES "
                         "(?, 'g1', 'inbox', 'Jordan Noel', 'jordan@acme.com', ?, 'Pricing', '2026-11-16T10:00:00Z', 'Can we agree the price by Friday?', '2026-11-16T10:00:00Z')",
                         (iid, json.dumps([{"name": "Milo Rio", "address": "milo.ray@example.com"}])))
        reply_working.put(self.con, iid, "Hi Jordan,\n\nYes, Friday works.\n\n-Milo", source="edit")
        p = C.preview(self.con, "email", str(iid))
        self.assertEqual((p["lines"][-1]["who"], p["lines"][-1]["text"]), ("Jordan", "Can we agree the price by Friday?"))
        self.assertIn("Friday works", p["draft_text"])
        self.assertIn(["From", "Jordan Noel"], p["facts"])
        self.assertEqual(p["href"], f"/inbox?open={iid}")

    def test_a_task_shows_its_steps(self):
        now = db.now()
        tid = self.con.execute("INSERT INTO tasks (title, done_when, status, area, created_at, updated_at) VALUES ('Hire a DACH AE', 'Marlow has names', 'open', 'team', ?, ?)",
                               (now, now)).lastrowid
        for i, (title, st) in enumerate((("Shortlist names", "done"), ("Send Marlow the list", "open"), ("Old idea", "deleted"))):
            self.con.execute("INSERT INTO tasks (parent_id, title, owner, status, position, created_at, updated_at) VALUES (?, ?, 'Milo Rio', ?, ?, ?, ?)",
                             (tid, title, st, i, now, now))
        self.con.commit()
        p = C.preview(self.con, "task", str(tid))
        self.assertEqual([(x["text"], x["done"]) for x in p["lines"]], [("Send Marlow the list", False), ("Shortlist names", True)])   # open steps first
        self.assertEqual(p["lines_label"], "Steps · 1 of 2 done")
        self.assertIn(["Done when", "Marlow has names"], p["facts"])
        self.assertEqual(p["kicker"], "Task · open")

    def test_an_initiative_a_person_and_a_meeting(self):
        self.con.execute("INSERT INTO initiative_updates (initiative_id, health, status_line, next, drafted_at, approved_at) "
                         "VALUES (1, 'on track', 'Two customers signed.', 'Sign the third', ?, ?)", (db.now(), db.now()))
        self.con.execute("INSERT INTO meetings (id, title, starts_at, status, note_item_id) VALUES (4, 'Product review', '2026-11-16T14:00:00Z', 'analysed', ?)",
                         (db.upsert_item(self.con, "granola", "n1", "note", "2026-11-16T14:00:00Z", subject="Product review", text="# Decisions\n\n- Ship in May\n")[0],))
        self.con.commit()
        ini = C.preview(self.con, "initiative", "platform")
        self.assertEqual((ini["text"], ini["kicker"]), ("Two customers signed.", "Initiative · on track"))
        self.assertIn(["Next", "Sign the third"], ini["facts"])
        self.assertIn(["Role", "VP Sales"], C.preview(self.con, "person", "7")["facts"])
        self.assertIn("Ship in May", C.preview(self.con, "meeting", "4")["md"])

    def test_nothing_held_nothing_shown_and_nothing_written(self):
        self.con.execute("INSERT INTO meetings (id, title, starts_at, status) VALUES (2, 'Private', '2026-11-16T15:00:00Z', 'personal')")
        self.con.commit()
        before = self.con.total_changes
        for kind, ref in (("meeting", "2"), ("person", "99"), ("task", "x"), ("file", "/etc/passwd"), ("initiative", "")):
            self.assertIsNone(C.preview(self.con, kind, ref), (kind, ref))
        for kind, ref in (("initiative", "platform"), ("person", "7")):
            self.assertIsNotNone(C.preview(self.con, kind, ref))
        self.assertEqual(self.con.total_changes, before)   # reads only

    def test_a_kept_chip_opens_its_page_or_says_it_is_gone(self):
        self.con.execute("INSERT INTO chat_threads (id, title, created_at, updated_at) VALUES ('t1', 'Prep', ?, ?)", (db.now(), db.now()))
        for who in ("7", "99"):
            kept = chat._keep_chip({**P.chip(self.con, "person", "7"), "ref": who})
            self.con.execute("INSERT INTO chat_turns (thread_id, role, text, ctx_json, created_at) VALUES ('t1', 'user', 'Prep me', ?, ?)",
                             (json.dumps(kept), db.now()))
        self.con.commit()
        turns = chat.thread("t1")["turns"]
        self.assertEqual((turns[0]["ctx"]["href"], turns[0]["ctx"]["gone"]), ("/people/p-7", False))
        self.assertEqual((turns[1]["ctx"]["href"], turns[1]["ctx"]["gone"]), ("", True))


if __name__ == "__main__":
    unittest.main()
