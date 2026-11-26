"""What Ask SleePO's floating button starts a chat with (assist/page_context.py, 16 Nov 2026): the thing open on the page."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import chat, db, page_context as P


class PageContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(self.tmp.name) / "t.db")})
        self.env.start()
        self.con = db.connect()
        db.migrate(self.con)
        self.con.execute("INSERT INTO initiatives (slug, name, weight, goal, updated_at) VALUES ('platform', 'Platform', 5, 'Three paying customers', ?)", (db.now(),))
        self.con.execute("INSERT INTO people (id, name, title, updated_at) VALUES (7, 'Jordan Noel', 'VP Sales', ?)", (db.now(),))
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_the_open_thing_is_named_from_the_address(self):
        ini = P.resolve(self.con, "/initiatives/platform")
        self.assertEqual((ini["kind"], ini["ref"], ini["label"]), ("initiative", "platform", "Platform"))
        who = P.resolve(self.con, "/people/p-7?tab=open")
        self.assertEqual((who["kind"], who["label"], who["detail"]), ("person", "Jordan Noel", "VP Sales"))
        for path in ("/", "/tasks", "/messages", "/initiatives/nope", "/people/p-99", "/inbox?open=abc"):
            self.assertIsNone(P.resolve(self.con, path), path)

    def test_a_direct_message_is_named_by_the_person_with_the_app(self):
        iid, _ = db.upsert_item(self.con, "slack", "msg:1", "message", "2026-11-16T10:00:00Z", subject="DM Jordan Noel")
        self.con.execute("INSERT INTO chat_messages (item_id, source_id, external_id, conversation_name, conversation_kind, author, sent_at, body_text)"
                         " VALUES (?, 'slack', 'msg:1', 'DM Jordan Noel', 'dm', 'Jordan Noel', '2026-11-16T10:00:00Z', 'Can you look at the deck?')", (iid,))
        self.con.execute("INSERT INTO people_aliases (alias, person_id) VALUES ('jordan lee', 7)")
        c = P.resolve(self.con, f"/messages?open={iid}")
        self.assertEqual((c["label"], c["app"], c["who"]), ("Jordan Noel", "slack", "Jordan Noel"))
        self.assertIn("Can you look at the deck?", c["detail"])
        self.assertEqual(P.resolve(self.con, "/initiatives/platform")["who"], "")   # every chip has the picture fields

    def test_a_chip_is_built_from_what_the_page_names(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            fake = mock.patch.object(P, "pack", lambda con, ctx: f"# {ctx['label']}\n")
            with fake:
                ok = chat._page_chip(self.con, {"path": "/initiatives/platform", "context": {"kind": "initiative", "ref": "platform"}}, ws)
                self.assertEqual(ok["label"], "Platform")
                self.assertIn(str(ws), ok["note"])
                self.assertEqual((ws / P.FILE).read_text(), "# Platform\n")
                # a pill can name something the address does not hold: built from the database by kind and id
                self.assertEqual(chat._page_chip(self.con, {"path": "/tasks", "context": {"kind": "person", "ref": "7"}}, ws)["label"], "Jordan Noel")
                for want in ({"kind": "person", "ref": "99"}, {"kind": "file", "ref": "/etc/passwd"}, {"kind": "person"}, {"kind": "initiative", "ref": "x' OR 1=1"}):
                    self.assertIsNone(chat._page_chip(self.con, {"path": "/", "context": want}, ws), want)   # nothing SleePO holds: no chip
                self.assertIsNone(chat._page_chip(self.con, {"path": "/initiatives/platform"}, ws))   # the chip removed: a normal chat

    def test_a_conversation_chip_shows_its_latest_message(self):
        for n, (at, who, text) in enumerate([("2026-11-16T10:00:00Z", "Jordan Noel", "Can you look at the deck?"), ("2026-11-16T11:00:00Z", "Jordan Noel", "Any news?")]):
            iid, _ = db.upsert_item(self.con, "slack", f"msg:{n}", "message", at, subject="DM Jordan Noel")
            self.con.execute("INSERT INTO chat_messages (item_id, source_id, external_id, conversation_name, conversation_kind, author, sent_at, body_text)"
                             " VALUES (?, 'slack', ?, 'DM Jordan Noel', 'dm', ?, ?, ?)", (iid, f"msg:{n}", who, at, text))
            if n == 0:
                first = iid
        last = P.chip(self.con, "message", iid)
        self.assertEqual(last["sub"], "Slack · Latest from Jordan: “Any news?”")
        self.assertEqual(P.chip(self.con, "message", first)["sub"], "Slack · Message from Jordan: “Can you look at the deck?”")   # not the latest
        self.assertEqual(P.resolve(self.con, f"/messages?open={iid}"), last)   # the address and the page's name give the same chip

    def test_companies_documents_and_roadmap_items_have_chips(self):
        self.con.execute("INSERT INTO orgs (id, name, kind, relation) VALUES (3, 'Acme Corp', 'partner', 'partner')")
        doc, _ = db.upsert_item(self.con, "sharepoint", "sp:1", "doc", "2026-11-10T09:00:00Z", subject="Plan.docx", text="The plan in full.")
        from assist import roadmap
        roadmap.ensure_schema(self.con)
        self.con.execute("INSERT INTO roadmap_items (id, name_internal, status, start_q, end_q) VALUES ('AI-9', 'Smart editing', 'planned', 'Q1 2027', 'Q2 2027')")
        self.con.commit()
        co = P.resolve(self.con, "/companies/3")
        self.assertEqual((co["kind"], co["label"], co["sub"]), ("company", "Acme Corp", "Partner"))
        d = P.resolve(self.con, f"/documents?open=sp-{doc}")
        self.assertEqual((d["kind"], d["label"], d["sub"]), ("document", "Plan.docx", "SharePoint"))
        self.assertIn("The plan in full.", P._document_pack(self.con, f"sp-{doc}"))
        self.assertEqual(P.resolve(self.con, "/roadmap?item=AI-9")["sub"], "Roadmap · AI-9 · planned · Q1 2027 to Q2 2027")
        for kind, ref in (("company", "99"), ("document", f"kb-{doc}"), ("document", "sp-x"), ("document", "../etc"), ("roadmap", "nope")):
            self.assertIsNone(P.chip(self.con, kind, ref), (kind, ref))   # a SharePoint id is not a knowledge-base page

    def test_personal_meetings_have_no_chip(self):
        self.con.execute("INSERT INTO meetings (id, title, starts_at, status) VALUES (1, 'Product review', '2026-11-16T14:00:00Z', 'analysed'),"
                         " (2, 'Private', '2026-11-16T15:00:00Z', 'personal')")
        self.con.commit()
        self.assertEqual(P.chip(self.con, "meeting", "1")["label"], "Product review")
        self.assertIsNone(P.chip(self.con, "meeting", "2"))
        self.assertIsNone(P.resolve(self.con, "/meetings/m-2"))

    def test_the_chip_stays_with_the_question(self):
        self.con.execute("INSERT INTO chat_threads (id, title, created_at, updated_at) VALUES ('t1', 'Draft', ?, ?)", (db.now(), db.now()))
        kept = chat._keep_chip({**P.chip(self.con, "person", "7"), "note": "[...]", "name": "Person"})
        self.assertNotIn("avatar", kept)   # photos are read again, not stored
        self.con.execute("INSERT INTO chat_turns (thread_id, role, text, ctx_json, created_at) VALUES ('t1', 'user', 'Prep me', ?, ?)",
                         (json.dumps(kept), db.now()))
        self.con.execute("INSERT INTO chat_turns (thread_id, role, text, created_at) VALUES ('t1', 'assistant', 'Here', ?)", (db.now(),))
        self.con.commit()
        turns = chat.thread("t1")["turns"]
        self.assertEqual((turns[0]["ctx"]["kind"], turns[0]["ctx"]["label"], turns[0]["ctx"]["sub"]), ("person", "Jordan Noel", "VP Sales"))
        self.assertIsNone(turns[1]["ctx"])

    def test_an_email_carries_the_draft_being_written(self):
        from assist import reply_working
        iid, _ = db.upsert_item(self.con, "outlook.inbox", "mail:1", "mail", "2026-11-16T10:00:00Z", subject="Pricing")
        reply_working.put(self.con, iid, "Hi Ann,\n\nYes to the pricing.\n\n-Milo", source="edit")
        self.assertIn("Yes to the pricing", P._draft(self.con, iid))
        self.assertEqual(P._draft(self.con, iid + 1), "")
        # the chat is told which email it is, so its reply card can go back into the reply (Use in reply)
        self.assertIn(f"```email {iid}", P.note({"kind": "email", "ref": str(iid), "label": "Pricing", "detail": "From Ann"}))
        self.assertNotIn("```email", P.note({"kind": "initiative", "ref": "platform", "label": "Platform", "detail": ""}))
        # a Teams or Slack conversation's reply is a card in its own app, for its newest message
        self.assertIn("```slack 42", P.note({"kind": "message", "ref": "42", "app": "slack", "label": "Jordan Noel", "detail": ""}))
        self.assertIn("```teams 43", P.note({"kind": "message", "ref": "43", "app": "teams", "label": "Jordan Noel", "detail": ""}))


if __name__ == "__main__":
    unittest.main()
