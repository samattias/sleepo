"""The Inbox's Drafts folder (assist/new_mail.py, applemail.drafts; Sam, 26 Oct 2026): Outlook's drafts read from Apple
Mail's store, new emails written in SleePO (kept, revised with a redline, marked sent when Sam sends them), replies in
progress, and recommended new emails, which are email actions on task steps, never a list of their own.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import applemail, db, new_mail, reply_working, tasks, todo


def ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


EMLX_NEW = "To: Quinn Irving <quinn.irving@acme.example>\nSubject: 2027 budget\nMessage-ID: <d1@x>\n\nQuinn,\n\nHere is the template.\n\n-Sam\n"
EMLX_REPLY = ("To: Rowan Lowell <rowan.lowell@acme.example>\nSubject: RE: Roadmap\nMessage-ID: <d2@x>\nIn-Reply-To: <orig@x>\n\n"
              "Rowan, agreed.\n\n-Sam\n\nFrom: Rowan Lowell\nSent: Monday\nSubject: Roadmap\n\nCan we lock the Q4 list this week?\n")


def emlx(text):
    raw = text.encode()
    return str(len(raw)).encode() + b"\n" + raw + b"<?xml version=\"1.0\"?><plist></plist>"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.con = db.connect(d / "t.db")
        db.migrate(self.con)
        c = self.con
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox', 'outlook', 'i'), ('outlook.sent', 'outlook', 's')")
        c.executemany("INSERT INTO people(id, name, title) VALUES (?, ?, ?)", [(1, "Rowan Lowell", "Director of PM"), (3, "Quinn Irving", "Finance Director")])
        c.executemany("INSERT INTO people_aliases VALUES (?, ?)", [("rowan lowell", 1), ("rowan.lowell@acme.example", 1), ("quinn irving", 3), ("quinn.irving@acme.example", 3)])
        c.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def mail(self, iid, folder, subject, to, at, frm="rowan.lowell@acme.example", imid=None, conv=None):
        src = "outlook.sent" if folder == "sentitems" else "outlook.inbox"
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, pulled_at) VALUES (?,?,?,?,?,?,?)",
                         (iid, src, f"m{iid}", "mail", at, subject, at))
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, conversation_id, from_name, from_address, to_json, cc_json, subject, body_text, "
                         "internet_message_id, received_at, sent_at, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (iid, f"g{iid}", folder, conv, "x", "sam.doe@acme.example" if folder == "sentitems" else frm,
                          json.dumps([{"name": "", "address": a} for a in to]), "[]", subject, "text", imid,
                          at if folder == "inbox" else None, at if folder == "sentitems" else None, at))
        self.con.commit()


class OutlookDrafts(Base):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name) / "V10"
        (root / "MailData").mkdir(parents=True)
        msgs = root / "ACCT" / "Drafts.mbox" / "UUID" / "Data" / "Messages"
        msgs.mkdir(parents=True)
        (msgs / "11.emlx").write_bytes(emlx(EMLX_NEW))
        (msgs / "12.emlx").write_bytes(emlx(EMLX_REPLY))
        (msgs / "13.emlx").write_bytes(emlx(EMLX_NEW))
        self.ix = root / "MailData" / "Envelope Index"
        ix = sqlite3.connect(self.ix)
        ix.executescript("""CREATE TABLE mailboxes (ROWID INTEGER PRIMARY KEY, url TEXT);
            CREATE TABLE subjects (ROWID INTEGER PRIMARY KEY, subject TEXT);
            CREATE TABLE addresses (ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
            CREATE TABLE recipients (ROWID INTEGER PRIMARY KEY, message INTEGER, type INTEGER, address INTEGER, position INTEGER);
            CREATE TABLE messages (ROWID INTEGER PRIMARY KEY, mailbox INTEGER, subject INTEGER, subject_prefix TEXT, date_received INTEGER,
                                   date_sent INTEGER, remote_id TEXT, deleted INTEGER);
            INSERT INTO mailboxes VALUES (1, 'ews://x/Inbox'), (6, 'ews://x/Drafts');
            INSERT INTO subjects VALUES (1, '2027 budget'), (2, 'Roadmap');
            INSERT INTO addresses VALUES (1, 'quinn.irving@acme.example', 'Quinn Irving'), (2, 'rowan.lowell@acme.example', 'Rowan Lowell');
            INSERT INTO recipients VALUES (1, 11, 0, 1, 0), (2, 12, 0, 2, 0);""")
        now = int(datetime.now(timezone.utc).timestamp())
        ix.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                       [(11, 6, 1, "", now - 60, now - 60, "AAMk+a/b=", 0), (12, 6, 2, "RE: ", now - 30, now - 30, "AAMkB", 0),
                        (13, 6, 1, "", now - 10, now - 10, "AAMkC", 1), (14, 1, 1, "", now, now, "AAMkD", 0)])
        ix.commit()
        ix.close()
        self.mail(50, "inbox", "Roadmap", ["sam.doe@acme.example"], ago(30), imid="<orig@x>")

    def test_drafts_are_read_with_own_text_reply_link_and_outlook_link(self):
        with mock.patch.object(applemail, "index_path", lambda: str(self.ix)):
            ds = applemail.drafts(self.con)
        self.assertEqual([d["key"] for d in ds], ["am-12", "am-11"])   # newest first; deleted and Inbox mail left out
        reply, new = ds
        self.assertEqual(reply["subject"], "RE: Roadmap")
        self.assertEqual(reply["body"], "Rowan, agreed.\n\n-Sam")
        self.assertIn("lock the Q4 list", reply["quoted"])
        self.assertEqual(reply["reply_to_item"], 50)
        self.assertEqual(new["to"], [{"name": "Quinn Irving", "address": "quinn.irving@acme.example"}])
        self.assertIsNone(new["reply_to_item"])
        self.assertIn("ItemID=AAMk%2Ba%2Fb%3D", new["web_link"])

    def test_improve_a_reply_goes_to_its_composer_and_a_new_one_to_a_sleepo_copy(self):
        with mock.patch.object(applemail, "index_path", lambda: str(self.ix)):
            self.assertEqual(new_mail.from_mail(self.con, "am-12"), {"item_id": 50})
            self.assertEqual(reply_working.get(self.con, 50)["body"], "Rowan, agreed.\n\n-Sam")
            first = new_mail.from_mail(self.con, "am-11")
            self.assertEqual(new_mail.from_mail(self.con, "am-11"), first)   # once
            d = new_mail.row(self.con, first["draft"])
            self.assertEqual((d["origin"], d["to"], d["subject"]), ("mail", ["quinn.irving@acme.example"], "2027 budget"))
            # shown once: as the SleePO draft, linked to the Outlook one
            lst = new_mail.listing(self.con)
        self.assertEqual([m["key"] for m in lst["outlook"]], ["am-12"])
        self.assertTrue(lst["sleepo"][0]["in_outlook"].startswith("https://outlook.office365.com/owa/?ItemID="))


class SleepoDrafts(Base):
    def test_kept_edited_marked_sent_and_purged(self):
        did = new_mail.create(self.con, ["quinn.irving@acme.example"], [], "Q4 spend review", "Quinn, ...", "ask for the numbers")
        new_mail.update(self.con, did, {"body": "Quinn, can you send the Q4 numbers?\n\n-Sam", "cc": "rowan.lowell@acme.example; "})
        d = new_mail.row(self.con, did)
        self.assertEqual(d["cc"], ["rowan.lowell@acme.example"])
        with mock.patch.object(applemail, "drafts", lambda con, limit=60: []):
            self.assertEqual([x["id"] for x in new_mail.listing(self.con)["sleepo"]], [did])
            self.mail(60, "sentitems", "RE: Q4 spend review", ["quinn.irving@acme.example"], ago(0))   # sent after the draft was started
            self.con.execute("UPDATE mail_drafts SET created_at=? WHERE id=?", (ago(2), did))
            lst = new_mail.listing(self.con)
        self.assertEqual(lst["sleepo"], [])
        self.assertEqual(new_mail.row(self.con, did)["status"], "sent")
        self.con.execute("UPDATE mail_drafts SET updated_at=?", (ago(24 * (new_mail.RETENTION_DAYS + 1)),))
        new_mail.purge(self.con)
        self.assertIsNone(new_mail.row(self.con, did))

    def test_a_revision_keeps_the_old_text_for_the_redline_and_sams_subject(self):
        did = new_mail.create(self.con, ["quinn.irving@acme.example"], [], "Budget", "Quinn, first.\n\n-Sam")
        new_mail.save_result(self.con, {"draft": did, "revised": True, "subject": "Something else", "body": "Quinn, second.\n\n-Sam", "notes": "n"})
        d = new_mail.row(self.con, did)
        self.assertEqual((d["prev_body"], d["body"], d["subject"]), ("Quinn, first.\n\n-Sam", "Quinn, second.\n\n-Sam", "Budget"))
        # a first draft from nothing: no redline, the writer's subject and recipients when Sam gave none
        d2 = new_mail.create(self.con, [], [], "", "", "email Rowan about the roadmap")
        new_mail.save_result(self.con, {"draft": d2, "revised": False, "subject": "Q4 roadmap", "body": "Rowan, ...", "notes": "", "to": ["rowan.lowell@acme.example"]})
        d = new_mail.row(self.con, d2)
        self.assertEqual((d["prev_body"], d["subject"], d["to"], d["first_body"]), (None, "Q4 roadmap", ["rowan.lowell@acme.example"], "Rowan, ..."))

    def test_names_become_addresses(self):
        self.assertEqual(new_mail.addresses(self.con, ["Quinn Irving", "Rowan Lowell <rowan.lowell@acme.example>", "nobody known"]),
                         ["quinn.irving@acme.example", "rowan.lowell@acme.example", "nobody known"])

    def test_the_writer_reads_the_people_and_revises_the_current_text(self):
        self.mail(70, "inbox", "Pricing sheet", ["sam.doe@acme.example"], ago(5), frm="quinn.irving@acme.example")
        p, ctx = new_mail.prompt(self.con, ["quinn.irving@acme.example"], [], "Pricing", "ask for the sheet", current="Quinn, old text.\n\n-Sam")
        self.assertIn("Quinn Irving · Finance Director", ctx)
        self.assertIn("Pricing sheet", ctx)                 # recent mail with them
        self.assertIn("Quinn, old text.", p)                # the current draft is revised, not replaced
        self.assertIn("not a reply", p)
        p, ctx = new_mail.prompt(self.con, [], [], "", "Email Rowan Lowell about the Q4 list")
        self.assertIn("People named in Sam's request", ctx)
        self.assertIn("rowan.lowell@acme.example", ctx)


class Recommended(Base):
    def task(self, actions, status="suggested"):
        return tasks.create(self.con, {"title": "Close the 2027 budget", "subtasks": [{"title": "Email Quinn: send the template", "actions": actions}]}, status, "drafts")

    def test_new_email_actions_on_tasks_are_recommended_until_sent(self):
        new = {"type": "email", "label": "Email Quinn", "to": ["quinn.irving@acme.example"], "subject": "2027 template", "body": "Quinn, ..."}
        reply = {"type": "email", "label": "Reply to Rowan", "to": ["rowan.lowell@acme.example"], "subject": "Re: x", "body": "...", "reply_to": "g1"}
        tid = self.task([new, reply])
        rec = new_mail.recommended(self.con)
        self.assertEqual(len(rec), 1)
        r = rec[0]
        self.assertEqual((r["task_id"], r["task_title"], r["suggested"], r["action"]["subject"]), (tid, "Close the 2027 budget", True, "2027 template"))
        self.con.execute("UPDATE tasks SET created_at=?", (ago(3),))
        self.mail(80, "sentitems", "2027 template", ["quinn.irving@acme.example"], ago(1))
        self.assertEqual(new_mail.recommended(self.con), [])

    def test_revising_a_recommended_email_keeps_it_on_the_step(self):
        self.task([{"type": "email", "label": "Email Quinn", "to": ["quinn.irving@acme.example"], "subject": "Template", "body": "old"}])
        sid = new_mail.recommended(self.con)[0]["step_id"]
        new_mail.save_result(self.con, {"step": [sid, 0], "revised": True, "subject": "", "body": "new", "notes": "checked"})
        a = json.loads(self.con.execute("SELECT actions_json FROM tasks WHERE id=?", (sid,)).fetchone()[0])[0]
        self.assertEqual((a["body"], a["prev_body"], a["subject"]), ("new", "old", "Template"))

    def test_the_pass_stores_one_email_step_per_suggestion(self):
        out = [{"title": "Send Quinn the budget template", "why": "You promised it on Friday.", "area": "Admin & operations",
                "subtasks": [{"title": "Email Quinn: the template", "owner": "Quinn Irving",
                              "actions": [{"type": "teams", "label": "Ping Quinn", "message": "hi"},
                                          {"type": "email", "label": "Email Quinn", "to": ["quinn.irving@acme.example"], "subject": "Template", "body": "Quinn, here it is.\n\n-Sam"}]},
                             {"title": "Second step dropped", "actions": []}]},
               {"title": "No email here", "subtasks": [{"title": "Think", "actions": [{"type": "draft", "label": "Think", "prompt": "x"}]}]}]
        with mock.patch.object(todo, "context", lambda con: ("NOW: Monday.", {})):
            n = new_mail.recommend(self.con, log=lambda *_: None, run_model=lambda t: json.dumps(out))
        self.assertEqual(n, 1)
        rec = new_mail.recommended(self.con)
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0]["task_title"], rec[0]["suggested"], rec[0]["origin"]), ("Send Quinn the budget template", True, "drafts"))
        step = self.con.execute("SELECT owner, actions_json FROM tasks WHERE id=?", (rec[0]["step_id"],)).fetchone()
        self.assertIsNone(step["owner"])                          # Sam sends it
        self.assertEqual([a["type"] for a in json.loads(step["actions_json"])], ["email"])
        self.assertEqual(new_mail.recommend_status(self.con)["count"], 1)


    def test_most_important_first_and_no_calendar_clashes(self):
        self.con.execute("INSERT INTO people(id, name, title) VALUES (5, 'Milo Marsh', 'Chief Executive Officer')")
        low = {"type": "email", "label": "Email Quinn", "to": ["quinn.irving@acme.example"], "subject": "Template", "body": "Quinn, ...", "importance": "low"}
        ceo = {"type": "email", "label": "Email Milo", "to": ["milo.marsh@acme.example"], "subject": "Copilot cut-off", "body": "Milo, ..."}
        clash = {"type": "email", "label": "Email Rowan", "to": ["rowan.lowell@acme.example"], "subject": "Our 1:1 tomorrow",
                 "body": "Hi Rowan,\n\nOur 1:1 tomorrow clashes with the CFT meeting. Can we move it?\n\n-Sam"}
        self.task([low])
        tasks.create(self.con, {"title": "Copilot free access", "subtasks": [{"title": "Ask Milo for the date", "due": date.today().isoformat(), "actions": [ceo]}]}, "suggested", "drafts")
        tasks.create(self.con, {"title": "Our 1:1", "subtasks": [{"title": "Move the Rowan 1:1 off the CFT meeting", "actions": [clash]}]}, "suggested", "assistant")
        rec = new_mail.recommended(self.con)
        self.assertEqual([r["action"]["subject"] for r in rec], ["Copilot cut-off", "Template"])
        self.assertEqual(rec[0]["level"], "high")
        self.assertIn("the CEO", rec[0]["rank_why"])
        self.assertTrue(new_mail.is_clash({"subject": "Wednesday 1:1", "body": "Otherwise it runs into my 1:1 with Finley."}))
        self.assertFalse(new_mail.is_clash(ceo))
        out = [{"title": "Fix Tuesday", "subtasks": [{"title": "Email Rowan: move our 1:1", "actions": [clash]}]}]
        with mock.patch.object(todo, "context", lambda con: ("NOW: Monday.", {})):
            self.assertEqual(new_mail.recommend(self.con, log=lambda *_: None, run_model=lambda t: json.dumps(out)), 0)

    def test_removing_a_suggestion_dismisses_it_and_undo_brings_it_back(self):
        tid = self.task([{"type": "email", "label": "Email Quinn", "to": ["quinn.irving@acme.example"], "subject": "Template", "body": "x"}])
        sid = new_mail.recommended(self.con)[0]["step_id"]
        new_mail.exclude(self.con, sid, 0)
        self.assertEqual(new_mail.recommended(self.con), [])
        st = lambda i: self.con.execute("SELECT status FROM tasks WHERE id=?", (i,)).fetchone()[0]
        self.assertEqual((st(sid), st(tid)), ("dismissed", "dismissed"))   # the pass is told not to suggest it again
        self.assertIn("Template", new_mail._drafts_block(self.con))
        new_mail.exclude(self.con, sid, 0, undo=True)
        self.assertEqual((st(sid), st(tid)), ("suggested", "suggested"))
        self.assertEqual(len(new_mail.recommended(self.con)), 1)

    def test_removing_one_from_an_accepted_task_keeps_the_step(self):
        tid = self.task([{"type": "email", "label": "Email Quinn", "to": ["quinn.irving@acme.example"], "subject": "Template", "body": "x"}], status="open")
        sid = new_mail.recommended(self.con)[0]["step_id"]
        new_mail.exclude(self.con, sid, 0)
        self.assertEqual(new_mail.recommended(self.con), [])
        self.assertEqual(self.con.execute("SELECT status FROM tasks WHERE id=?", (sid,)).fetchone()[0], "open")


class InProgress(Base):
    def test_a_reply_in_progress_shows_until_sam_answers(self):
        self.mail(90, "inbox", "Roadmap", ["sam.doe@acme.example"], ago(5), conv="c1")
        reply_working.put(self.con, 90, "Rowan, yes.\n\n-Sam", "reply", "edit")
        self.assertEqual([r["item_id"] for r in new_mail._replies_in_progress(self.con)], [90])
        self.con.execute("UPDATE reply_working SET updated_at=?", (ago(2),))
        self.mail(91, "sentitems", "RE: Roadmap", ["rowan.lowell@acme.example"], ago(1), conv="c1")
        self.assertEqual(new_mail._replies_in_progress(self.con), [])


if __name__ == "__main__":
    unittest.main()
