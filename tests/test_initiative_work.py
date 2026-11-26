"""Working on an initiative or a topic from its page (assist/initiative_work.py; Sam, 29 Oct 2026): the pack carries the
initiative and puts the items Sam picked first; linked items read in place, never a personal meeting; each button is an Ask
SleePO conversation with the subject's context and the button's instruction; a decision is kept as a decide step under the
initiative (no decisions log); a draft made from a page before then still reads its initiative; reading writes nothing.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import db, initiative_work as w, new_mail, remember, tasks


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class InitiativeWork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)   # what Sam types goes to jobs/heard.jsonl: never the real one from a test
        self.heard = mock.patch.multiple(remember, DIR=t, HEARD=t / "heard.jsonl", STATE=t / "remember.json")
        self.heard.start()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        tasks.ensure_schema(c)
        new_mail.ensure_schema(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox', 'outlook', 'Inbox'), ('granola', 'granola', 'Granola')")
        c.execute("INSERT INTO people(id, name, is_me) VALUES (1, 'Sam Doe', 1)")
        c.execute("INSERT INTO people(id, name, title) VALUES (2, 'Finley Kirby', 'Sr Director of Development')")
        c.execute("INSERT INTO people_aliases(person_id, alias) VALUES (2, 'finley.kirby@acme.example')")
        c.execute("INSERT OR IGNORE INTO initiatives(slug, name, weight, active, goal) VALUES ('plt-nova', 'PLT / NOVA', 5, 1, 'Three paying design partnership customers')")
        c.execute("INSERT OR IGNORE INTO initiatives(slug, name, weight, active) VALUES ('gtm-marketing', 'GTM & partner enablement', 3, 1)")
        self.ini = c.execute("SELECT id FROM initiatives WHERE slug='plt-nova'").fetchone()[0]
        self.other = c.execute("SELECT id FROM initiatives WHERE slug='gtm-marketing'").fetchone()[0]
        self.mail = self.item("outlook.inbox", "mail", "NWT co-design proposal", "Finley Kirby", "Proposal by Monday 2 Nov; Connect POC about $30K.")
        c.execute("INSERT INTO mail_messages(item_id, graph_id, folder, from_name, from_address, to_json, cc_json, subject, body_text, received_at, synced_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (self.mail, "g1", "inbox", "Finley Kirby", "finley.kirby@acme.example",
                                                     json.dumps([{"name": "Sam Doe", "address": "sam.doe@acme.example"}]), "[]", "NWT co-design proposal",
                                                     "Sam, the proposal is due Monday 2 Nov. The Connect POC is about $30K.\n\nFrom: Sam\nolder quoted text", ago(1), ago(0)))
        self.meet = self.meeting("NOVA kickoff with Finley", "Kickoff from 1 November; demoable flow by end of November.")
        self.personal = self.meeting("Sam <> Robin sync", "Weekend plans", status="personal")
        for rt, rid in (("item", self.mail), ("meeting", self.meet), ("meeting", self.personal)):
            c.execute("INSERT INTO mentions(ref_type, ref_id, entity_type, entity_id, confidence, source, verdict) VALUES (?,?,'initiative',?,1.0,'claude','confirmed')",
                      (rt, rid, self.ini))
        c.commit()

    def tearDown(self):
        self.con.close()
        self.heard.stop()
        self.tmp.cleanup()

    def item(self, src, kind, subject, who, text):
        return self.con.execute("INSERT INTO items(source_id, external_id, kind, ts, subject, from_name, text, pulled_at) VALUES (?,?,?,?,?,?,?,?)",
                                (src, subject, kind, ago(1), subject, who, text, ago(0))).lastrowid

    def meeting(self, title, digest, status="analysed"):
        note = self.item("granola", "note", title, "", digest)
        return self.con.execute("INSERT INTO meetings (title, starts_at, ends_at, attendees, digest_md, status, note_item_id) VALUES (?,?,?,?,?,?,?)",
                                (title, ago(2), ago(2), json.dumps(["Finley Kirby", "Sam Doe"]), f"# {title}\n{digest}", status, note)).lastrowid

    def test_pack_carries_the_initiative_and_picked_items_first(self):
        md, refs, _ = w.pack(self.con, "plt-nova", [f"item:{self.mail}"])
        self.assertIn("# Initiative: PLT / NOVA", md)
        self.assertIn("Three paying design partnership customers", md)
        picked = md.index("What Sam is working from")
        self.assertLess(picked, md.index("Everything linked to the initiative"))
        self.assertIn("The Connect POC is about $30K", md[picked:])            # the picked email, in full
        self.assertIn("finley.kirby@acme.example", md)                             # people with addresses, for recipients
        self.assertNotIn("Weekend plans", md)                                     # a personal meeting never goes in
        self.assertTrue(all(v["ref_type"] in ("item", "meeting") for v in refs.values()))

    def test_read_in_place_and_never_a_personal_meeting(self):
        r = w.read(self.con, "item", self.mail)
        self.assertEqual(r["kind"], "mail")
        self.assertTrue(r["text"].startswith("Sam, the proposal is due Monday 2 Nov"))
        self.assertNotIn("older quoted text", r["text"])                          # Sam reads the email's own words
        self.assertEqual(r["open"], f"#/inbox?open={self.mail}")
        self.assertIn("demoable flow", w.read(self.con, "meeting", self.meet)["text"])
        self.assertIsNone(w.read(self.con, "meeting", self.personal))

    def test_reading_writes_nothing(self):
        before = self.con.total_changes
        w.pack(self.con, "plt-nova", [f"meeting:{self.meet}"])
        w.read(self.con, "item", self.mail)
        w.work(self.con, self.ini)
        self.assertEqual(self.con.total_changes, before)

    def test_a_draft_from_the_page_still_reads_its_initiative(self):
        did = new_mail.create(self.con, [], [], "", "", "Update Milo", initiative_id=self.ini, focus=[f"item:{self.mail}"])
        d = new_mail.row(self.con, did)
        ctx = new_mail.context(self.con, [], [], "", "Update Milo on the kickoff", ini=self.ini, focus=d["focus"])
        self.assertIn("The initiative this email is about", ctx)
        self.assertIn("The Connect POC is about $30K", ctx)
        self.assertEqual([x["id"] for x in w.work(self.con, self.ini)["drafts"]], [did])

    def test_a_decision_is_a_decide_step_under_the_initiative(self):
        r = w.record(self.con, "plt-nova", "Offer Adatum a time-bound seat?", "Time-bound seat", "Floor of $600K, IP stays with Acme",
                     refs={"S1": {"label": "NWT co-design proposal", "url": "#/inbox"}})
        task = self.con.execute("SELECT * FROM tasks WHERE id=?", (r["task_id"],)).fetchone()
        step = self.con.execute("SELECT * FROM tasks WHERE id=?", (r["step_id"],)).fetchone()
        self.assertEqual((task["initiative_id"], task["status"], step["parent_id"], step["kind"], step["status"]), (self.ini, "done", r["task_id"], "decide", "done"))
        self.assertIn("Floor of $600K", step["close_reason"])
        self.assertEqual(json.loads(step["sources_json"])[0]["label"], "NWT co-design proposal")
        self.assertFalse(db.has_table(self.con, "decisions") and self.con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])
        self.assertFalse(remember.HEARD.exists())       # the card's words are the model's: Sam's own are in the chat

    def test_decide_later_is_an_open_step_on_his_task(self):
        tid = tasks.create(self.con, {"title": "Design partnership terms agreed", "initiative_id": self.ini})
        r = w.record(self.con, "plt-nova", "Seat or licence for Adatum", decided=False, task_id=tid)
        self.assertEqual(r["task_id"], tid)
        self.assertEqual(self.con.execute("SELECT status, kind FROM tasks WHERE id=?", (r["step_id"],)).fetchone()[:], ("open", "decide"))
        other = tasks.create(self.con, {"title": "Copilot GA email", "initiative_id": self.other})
        with self.assertRaises(ValueError):
            w.record(self.con, "plt-nova", "Something", "A", task_id=other)
        with self.assertRaises(ValueError):
            w.record(self.con, "plt-nova", "Something")                         # a decision needs his call

    def topic(self):
        from assist import topics
        topics.ensure_schema(self.con)
        src = [{"kind": "mail", "label": "NWT co-design proposal", "ts": ago(1), "app": f"#/inbox?open={self.mail}", "clock": "", "who": ["Finley Kirby"],
                "said": [{"who": "Finley Kirby", "text": "The proposal is due Monday 2 Nov."}]},
               {"kind": "meeting", "label": "NOVA kickoff with Finley", "ts": ago(2), "app": f"#/meetings/m-{self.meet}?t=30", "clock": "00:30", "who": ["you"]},
               {"kind": "ask", "label": "where is NWT located?", "ts": ago(1), "app": "#/assistant", "clock": "", "who": ["you"]}]
        return self.con.execute("INSERT INTO topics (run_at, title, summary, ask, initiative_id, importance, raised_by, people_json, sources_json, meetings, mails, "
                                "chats, asks, days, last_ts, score, rank, status, updated_at) VALUES (?,?,?,?,?,?,?,?,?,1,1,0,1,2,?,5,1,'current',?)",
                                (ago(0), "NWT co-design partnership", "NWT wants to co-design; IT resists a paid POC.", "Send NWT the pilot commitments",
                                 self.ini, "high", "Finley Kirby", json.dumps(["Finley Kirby"]), json.dumps(src), ago(1), ago(0))).lastrowid

    def test_a_topic_page_works_from_the_topic(self):
        tid = self.topic()
        refs = w.topic_refs(__import__("assist.topics", fromlist=["x"]).one(self.con, tid))
        self.assertEqual([r["ref_key"] for r in refs], [f"item:{self.mail}", f"meeting:{self.meet}", None])
        md, prefs, _ = w.topic_pack(self.con, tid)
        self.assertIn("# Topic: NWT co-design partnership", md)
        self.assertIn("Open on Sam: Send NWT the pilot commitments", md)
        self.assertIn("Finley Kirby: The proposal is due Monday 2 Nov.", md)          # who said what
        self.assertIn("The Connect POC is about $30K", md)                           # the email, in full
        self.assertIn("The initiative it moves: PLT / NOVA", md)
        self.assertNotIn("Weekend plans", md)
        self.assertEqual(w.pack(self.con, f"topic:{tid}")[0], md)                      # the same pack through the subject

    def test_a_topic_page_shows_what_each_source_said_and_its_files(self):
        # Sam, 29 Oct 2026: "links to the latest emails or what that email said or messages or call ... a link to the actual deck"
        c = self.con
        deck = "https://acmellc.sharepoint.com/:p:/s/MarketingGlobal/cQrX?e=1"
        c.execute("UPDATE mail_messages SET body_text=?, received_at=? WHERE item_id=?",
                  ("Hi Milo and Sam,\nHere is the latest deck. \u200b[https://res-2.df.onecdn.static.microsoft/assets/pptx.svg]2006 contoso LIVE - "
                   f"Acme EN.pptx<{deck}>\nThe script follows.\n\nFrom: Sam\nolder quoted text", ago(0.5), self.mail))
        c.execute("INSERT INTO mail_attachments(item_id, graph_id, name, is_inline, path) VALUES (?, 'a1', 'Budget 2027.xlsx', 0, 'x/Budget 2027.xlsx'), "
                  "(?, 'a2', 'logo.png', 1, 'x/logo.png')", (self.mail, self.mail))
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('teams', 'teams', 'Teams')")
        chat = self.item("teams", "chat", "work trip", "Sage Gilmore", "")
        c.execute("INSERT INTO chat_messages(item_id, source_id, external_id, conversation_name, author, sent_at, body_text, links_json) VALUES (?,?,?,?,?,?,?,?)",
                  (chat, "teams", "m1", "work trip", "Sage Gilmore", ago(1.5),
                   "Ellis Ingram  I followed up with an email to Prescott-san based on our discussions Tuesday. We are excited about our joint presentatio\u2026  "
                   "Hi Ellis-san, thank you, we will share it with the contoso team.", "[]"))
        c.execute("INSERT INTO chat_attachments(item_id, name, url) VALUES (?, 'Japan schedule.xlsx', 'https://acmellc-my.sharepoint.com/personal/y/Japan%20schedule.xlsx')", (chat,))
        tid = self.topic()
        src = json.loads(c.execute("SELECT sources_json FROM topics WHERE id=?", (tid,)).fetchone()[0])
        src[1]["said"] = [{"who": "Finley Kirby", "text": "Kickoff from 1 November.", "clock": "00:30", "app": f"#/meetings/m-{self.meet}?t=30"}]
        src.insert(1, {"kind": "chat", "label": "work trip", "ts": ago(1.5), "app": f"#/messages?open={chat}", "clock": "", "who": ["Sage Gilmore"],
                       "said": [{"who": "Sage Gilmore", "text": "Ellis Ingram  I followed up…", "app": f"#/messages?open={chat}"}]})
        c.execute("UPDATE topics SET sources_json=? WHERE id=?", (json.dumps(src), tid))
        c.commit()
        from assist import topics
        refs = w.topic_refs(topics.one(c, tid))
        before = c.total_changes
        files = w.topic_latest(c, refs)
        self.assertEqual(c.total_changes, before)                                       # reading writes nothing
        self.assertEqual([(f["name"], f["url"]) for f in files],                        # the real files, newest first; no inline image
                         [("2006 contoso LIVE - Acme EN.pptx", deck), ("Budget 2027.xlsx", f"/api/mail/{self.mail}/attachments/1?download=1"),
                          ("Japan schedule.xlsx", "https://acmellc-my.sharepoint.com/personal/y/Japan%20schedule.xlsx")])
        mail = next(r for r in refs if r["kind"] == "mail")
        self.assertEqual(mail["lines"][0]["who"], "Finley Kirby")
        self.assertEqual(mail["lines"][0]["text"], "Here is the latest deck. 2006 contoso LIVE - Acme EN.pptx The script follows.")   # no addresses, no greeting
        self.assertEqual(len(mail["files"]), 2)
        chat_src = next(r for r in refs if r["kind"] == "chat")
        self.assertEqual(chat_src["lines"], [{"who": "Sage Gilmore", "text": "thank you, we will share it with the contoso team.",
                                             "app": f"#/messages?open={chat}"}])        # his words, not the message he quoted
        meet = next(r for r in refs if r["kind"] == "meeting")
        self.assertEqual((meet["lines"][0]["clock"], meet["lines"][0]["text"]), ("00:30", "Kickoff from 1 November."))
        self.assertEqual([r["kind"] for r in refs], ["mail", "ask", "chat", "meeting"])    # newest first: the thread's newest message counts
        text = w.read(c, "item", self.mail)["text"]                                      # read in place: the file by its name, no icon
        self.assertIn("Here is the latest deck. 2006 contoso LIVE - Acme EN.pptx\nThe script follows.", text)
        self.assertNotIn("https://", text)

    def test_work_from_a_topic_is_kept_with_the_topic(self):
        tid = self.topic()
        d = new_mail.row(self.con, new_mail.create(self.con, [], [], "", "", "", initiative_id=self.ini, topic_id=tid))
        ctx = new_mail.context(self.con, [], [], "", "Update NWT", ini=self.ini, topic=tid)
        self.assertIn("The topic this email is about", ctx)
        r = w.record(self.con, f"topic:{tid}", "Paid POC or free pilot for NWT?", "Free pilot", "Time-boxed to six weeks")
        task = self.con.execute("SELECT initiative_id, sources_json FROM tasks WHERE id=?", (r["task_id"],)).fetchone()
        self.assertEqual(task["initiative_id"], self.ini)
        self.assertIn(f"#/topics/{tid}", task["sources_json"])
        work = w.topic_work(self.con, tid)
        self.assertEqual(([x["id"] for x in work["drafts"]], [x["id"] for x in work["decisions"]]), ([d["id"]], [r["step_id"]]))
        with self.assertRaises(ValueError):
            w.subject(self.con, "topic:999999")

    def test_each_button_is_a_conversation_with_the_context_and_its_instruction(self):
        from assist import chat, claude_open
        tid = self.topic()
        self.con.commit()
        ws, saved = tempfile.TemporaryDirectory(), claude_open.WORKSPACE
        claude_open.WORKSPACE = Path(ws.name)
        seed = lambda t: self.con.execute("SELECT seed FROM chat_threads WHERE id=?", (t,)).fetchone()[0]
        try:
            with mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(self.tmp.name) / "t.db")}), mock.patch.object(chat, "summarize_later", lambda t: None):
                out = w.to_chat(self.con, f"topic:{tid}", [f"item:{self.mail}"], "email")
                self.assertEqual(out["hint"], w.HINT["email"])                                  # nothing is asked for Sam: it waits for him
                t = chat.thread(out["thread"])
                self.assertEqual([u["role"] for u in t["turns"]], ["user", "assistant"])
                self.assertIn("**Write an email.** Who is it for", t["turns"][1]["text"])     # the answer asks what he wants
                self.assertIn(json.dumps([w.NOW["email"]]), t["turns"][1]["text"])            # or leaves it to SleePO in one click
                self.assertIn("**On you:** Send NWT the pilot commitments", t["turns"][1]["text"])
                self.assertIn("Working from: NWT co-design proposal", t["turns"][1]["text"])
                self.assertIn("The Connect POC is about $30K", (Path(t["workspace"]) / "Topic context.md").read_text())
                self.assertIn("Sam pressed Write an email", seed(out["thread"]))               # the instruction rides with that question
                self.assertIn(str(Path(t["workspace"]) / "Topic context.md"), seed(out["thread"]))
                self.assertIn(f'"subject": "topic:{tid}"', seed(out["thread"]))               # a decision taken there files under the topic
                ask = w.to_chat(self.con, "plt-nova", [], "")                                 # Ask in chat: Sam asks himself
                self.assertEqual(ask["hint"], "")
                self.assertNotIn("What to do now", seed(ask["thread"]))
                doc = w.to_chat(self.con, "plt-nova", [], "document")
                self.assertIn("Sam pressed Create a document", seed(doc["thread"]))
                self.assertEqual([x["id"] for x in w.topic_work(self.con, tid)["chats"]], [out["thread"]])
                self.assertCountEqual([x["id"] for x in w.work(self.con, self.ini)["chats"]], [ask["thread"], doc["thread"]])
        finally:
            claude_open.WORKSPACE = saved
            ws.cleanup()


if __name__ == "__main__":
    unittest.main()
