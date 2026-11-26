"""Links in an email (assist/links.py): found in Outlook's `label<url>` text, signatures left out, matched to documents SleePO
holds, named as not read when it cannot open them, and a file Sam adds stands in for the link. Then the hand-offs of a reply
draft and a document plan to the chat (replies.to_chat, deliverables.to_chat). The chat store is mocked.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from assist import chat, chatsync, db, deliverables, links, replies
from assist.routes import mail as mail_routes
from test_open_items import Base, ago

SAM = "sam.doe@acme.example"
BODY = ("Hi Milo-san, Sam-san,\n\nI have put together the page below.\n\n\u200b[https://res-2.df.onecdn.static.microsoft/files/fabric/html.svg]"
        "contoso-mart_timeline.html<https://acmellc.sharepoint.com/:u:/s/Japan-GTM/IQDSdDN0mPdf?e=m6f6Oo>\u200b\n\n"
        "The deck: Q4_plan.pptx<https://acmellc.sharepoint.com/sites/Japan-GTM/Shared%20Documents/Partner/Q4_plan.pptx?web=1>\n"
        "Folder: \u200bMCP<https://acmellc.sharepoint.com/:f:/s/Japan-GTM/IgB_ODoDBKff?e=1lRZKk>\n\nBest regards,\nKai\n\n"
        "[Employee photo]<https://acme.example/>\n[Linkedin Icon]<https://company556.com/company/acme/>\n"
        "[Photo]<https://www.acme.example/agentic-process-foundation/>\nkai.sutton@acme.example<mailto:>")
PAGE = "<html><head><style>p{}</style></head><body><h1>contoso timeline</h1><p>8 Oct: alignment meeting</p>" \
       "<p>Waiting on Acme: ORC definition &amp; IP boundary</p><script>x()</script></body></html>"


class Find(unittest.TestCase):
    def test_documents_are_found_and_signatures_left_out(self):
        got = links.find(BODY)
        self.assertEqual([(x["name"], x["kind"], x["share"]) for x in got],
                         [("contoso-mart_timeline.html", "sharepoint", "file"), ("Q4_plan.pptx", "sharepoint", ""), ("MCP", "sharepoint", "folder")])

    def test_a_file_name_with_spaces_is_named_in_full(self):
        # Outlook writes "[icon]2006 contoso LIVE - Acme EN.pptx<link>": the name is the whole label, not "EN.pptx" (29 Oct 2026)
        got = links.find("Hi Sam, \u200b[https://res-2.df.onecdn.static.microsoft/assets/pptx.svg]2006 contoso LIVE - Acme EN.pptx"
                         "<https://acmellc.sharepoint.com/:p:/s/MarketingGlobal/cQrX?e=1> The script: speaker script v2.docx"
                         "<https://acmellc.sharepoint.com/:w:/s/MarketingGlobal/cQqR?e=2> and here<https://acmellc.sharepoint.com/:p:/r/sites/"
                         "Japan-GTM/_layouts/15/Doc.aspx?sourcedoc=%7BC1%7D&file=Combined_Offering.pptx&action=edit>")
        self.assertEqual([x["name"] for x in got], ["2006 contoso LIVE - Acme EN.pptx", "speaker script v2.docx", "Combined_Offering.pptx"])

    def test_safe_links_are_unwrapped(self):
        got = links.find("See https://eur01.safelinks.protection.outlook.com/?url=https%3A%2F%2Facme.atlassian.net%2Fbrowse%2FPLT-77&data=x")
        self.assertEqual((got[0]["url"], got[0]["kind"]), ("https://acme.atlassian.net/browse/PLT-77", "jira"))


class Linked(Base):
    def setUp(self):
        _t = mock.patch.object(chat, "summarize_later", lambda tid: None)   # no real Claude call to name a conversation
        _t.start()
        self.addCleanup(_t.stop)
        super().setUp()
        self.dl = tempfile.TemporaryDirectory()   # never the real ~/Downloads
        self.addCleanup(self.dl.cleanup)
        p = mock.patch.object(links, "DOWNLOADS", Path(self.dl.name))
        p.start()
        self.addCleanup(p.stop)
        c = self.con
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('sharepoint', 'sharepoint', 'sp')")
        self.mid = self.mail("inbox", "kai.sutton@acme.example", [SAM], "contoso: open items", 1)
        c.execute("UPDATE mail_messages SET body_text=?, from_name='Kai Sutton', to_json=? WHERE item_id=?",
                  (BODY, json.dumps([{"name": "Sam Doe", "address": SAM}]), self.mid))
        c.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at, subject, url, text) VALUES (900, 'sharepoint', 'sp1', 'document', ?, ?, ?, ?, ?)",
                  (ago(3), ago(3), "Q4_plan.pptx", "https://acmellc.sharepoint.com/sites/Japan-GTM/Shared Documents/Partner/Q4_plan.pptx", "Q4 plan. " * 80))
        c.commit()

    def test_files_shared_in_teams_are_read_like_email_links(self):
        # the chat pull reads an attached OneDrive file into a SharePoint item; the attachment matches it by address (29 Oct 2026)
        c = self.con
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('teams', 'teams', 't')")
        c.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at, subject, url, text) VALUES (901, 'sharepoint', 'sp2', 'doc', ?, ?, ?, ?, ?)",
                  (ago(1), ago(1), "Q2 report.pptx", "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/Microsoft%20Teams%20Chat%20Files/Q2%20report.pptx?web=1",
                   "Quarterly operations report. " * 30))
        old = chatsync.store_record(c, {"source_id": "teams", "external_id": "m1", "conversation_name": "Chat with Tatum", "conversation_kind": "dm",
                                        "ts": ago(30), "author": "Tatum Easton", "body_text": "the plan: [Q4_plan.pptx](https://acmellc.sharepoint.com/sites/Japan-GTM/Shared%20Documents/Partner/Q4_plan.pptx?web=1)"})
        new = chatsync.store_record(c, {"source_id": "teams", "external_id": "m2", "conversation_name": "Chat with Tatum", "conversation_kind": "dm",
                                        "ts": ago(1), "author": "Tatum Easton", "body_text": "can you review this deck and update slide 2?",
                                        "attachments": [{"name": "Q2 report.pptx", "content_type": "reference",
                                                         "url": "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/Microsoft%20Teams%20Chat%20Files/Q2%20report.pptx"},
                                                        {"name": "notes.docx", "content_type": "reference", "url": "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/notes.docx"}]})
        c.commit()
        got = {x["name"]: x for x in links.for_chat(c, [old, new])}
        self.assertEqual((got["Q2 report.pptx"]["doc"], got["Q2 report.pptx"]["readable"], got["Q2 report.pptx"]["this_email"]), ("sp-901", True, True))
        self.assertEqual((got["Q4_plan.pptx"]["doc"], got["Q4_plan.pptx"]["this_email"]), ("sp-900", False))   # a link in the text, earlier
        self.assertFalse(got["notes.docx"]["readable"])
        text = "\n".join(links.context_lines(list(got.values()), noun="message"))
        self.assertIn("# Linked document (in this message): Q2 report.pptx", text)
        self.assertIn("# Linked document (earlier in the conversation): Q4_plan.pptx", text)
        self.assertIn("- notes.docx · in this message", text)
        h = links.held(c)
        self.assertTrue(links.is_held(h, "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/Microsoft%20Teams%20Chat%20Files/Q2%20report.pptx"))
        self.assertFalse(links.is_held(h, "https://acmellc-my.sharepoint.com/personal/alex_example_com/Documents/notes.docx"))

    def test_held_documents_are_read_and_the_others_named(self):
        got = {x["name"]: x for x in links.for_email(self.con, self.mid)}
        self.assertEqual((got["Q4_plan.pptx"]["doc"], got["Q4_plan.pptx"]["readable"]), ("sp-900", True))
        self.assertFalse(got["contoso-mart_timeline.html"]["readable"])
        ctx, _ = replies.context(self.con, self.mid)
        self.assertIn("# Linked document (in this email): Q4_plan.pptx", ctx)
        self.assertIn("- contoso-mart_timeline.html (file) · in this email", ctx)
        listed = {a["name"]: a for a in replies.attachments(self.con, self.mid)}
        self.assertEqual((listed["Q4_plan.pptx"]["doc"], listed["contoso-mart_timeline.html"]["readable"]), ("sp-900", False))

    def test_a_file_sam_adds_stands_in_for_the_link(self):
        aid = links.add_file(self.con, self.mid, "contoso-mart_timeline.html", PAGE.encode())
        got = {x["name"]: x for x in links.for_email(self.con, self.mid)}
        self.assertEqual((got["contoso-mart_timeline.html"]["doc"], got["contoso-mart_timeline.html"]["readable"]), (f"ma-{aid}", True))
        ctx, _ = replies.context(self.con, self.mid)
        self.assertIn("Waiting on Acme: ORC definition & IP boundary", ctx)
        self.assertNotIn("x()", ctx)
        self.assertNotIn("- contoso-mart_timeline.html (file)", ctx)   # read, so no longer listed as not opened
        self.assertIn("- MCP (folder)", ctx)
        added = [a for a in replies.attachments(self.con, self.mid) if a.get("added")]
        self.assertEqual([a["name"] for a in added], ["contoso-mart_timeline.html"])
        self.assertEqual(links.remove_file(self.con, self.mid, aid), 1)
        self.assertFalse({x["name"]: x for x in links.for_email(self.con, self.mid)}["contoso-mart_timeline.html"]["readable"])

    def test_a_linked_file_sam_downloaded_is_read_from_downloads(self):
        (Path(self.dl.name) / "contoso-mart_timeline (2).html").write_text(PAGE)
        (Path(self.dl.name) / "other.html").write_text(PAGE)
        old = Path(self.dl.name) / "Q9.pdf"
        got = {x["name"]: x for x in links.for_email(self.con, self.mid)}
        self.assertEqual((got["contoso-mart_timeline.html"]["readable"], got["contoso-mart_timeline.html"]["where"]), (True, "Downloads"))
        self.assertIn("Waiting on Acme", got["contoso-mart_timeline.html"]["text"])
        f = Path(self.dl.name) / "contoso-mart_timeline (2).html"   # older than 30 days: not used
        os.utime(f, (time.time() - 40 * 86400, time.time() - 40 * 86400))
        self.assertFalse({x["name"]: x for x in links.for_email(self.con, self.mid)}["contoso-mart_timeline.html"]["readable"])
        self.assertFalse(old.exists())

    def test_unreadable_files_are_refused(self):
        with self.assertRaises(ValueError):
            links.add_file(self.con, self.mid, "photo.heic", b"x")
        with self.assertRaises(ValueError):
            links.add_file(self.con, self.mid, "empty.html", b"<html></html>")

    def test_add_file_endpoint_takes_base64_json(self):
        req = mock.Mock(headers={"content-type": "application/json"})
        with mock.patch.object(mail_routes, "con", lambda: db.connect(Path(self.tmp.name) / "t.db")):
            r = mail_routes.api_mail_add_file(self.mid, mail_routes.AddedFile(name="t.html", data=base64.b64encode(PAGE.encode()).decode()), req)
        self.assertTrue(r["ok"])

    def test_a_draft_continues_in_the_chat_with_its_context(self):
        seen = {}
        with mock.patch.object(chat, "seed", lambda *a, **k: seen.update(args=a) or "t1"):
            tid = replies.to_chat(self.con, self.mid, "Hi Kai,\n\nThanks.\n\n-Sam", "Check the timeline", "Thank him", "reply", 2)
        title, question, answer, seed, files = seen["args"]
        self.assertEqual(tid, "t1")
        self.assertTrue(title.startswith("Reply: contoso"))
        self.assertIn(f"```email {self.mid}\nHi Kai,", answer)
        self.assertIn("```followups", answer)
        self.assertIn("{workspace}/Reply context.md", seed)
        self.assertIn("contoso-mart_timeline.html", files["Reply context.md"])
        self.assertNotIn("Return ONLY a JSON", files["Reply context.md"])

    def test_a_plan_continues_in_the_chat_with_its_pack(self):
        seen = {}
        plan = {"format": "pptx", "title": "contoso response", "audience": "Kai", "outline": ["Where we are", "What we owe"],
                "prompt": "Build it.", "covers": ["gaps"], "gaps": ["IP position"], "doc": None}
        with mock.patch.object(chat, "seed", lambda *a, **k: seen.update(args=a) or "t2"):
            deliverables.to_chat(self.con, self.mid, plan, "Keep it short")
        title, question, answer, seed, files = seen["args"]
        self.assertEqual(title, "Document: contoso response")
        self.assertIn("1. Where we are", answer)
        self.assertIn("{workspace}/Document context.md", seed)
        self.assertIn("contoso-mart_timeline.html", files["Document context.md"])


if __name__ == "__main__":
    unittest.main()
