"""Reviewing a file shared in Teams (assist/file_review.py): the deck's text by slide in the deck's own order, edits made in
the real file without touching the formatting around them (also across runs and with SharePoint's stray spaces), a review
whose unknown citations are removed and whose edits must be in the file, and the whole review with the model stubbed; a
message opened in Ask SleePO (assist/message_chat.py) and a review the chat starts.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from assist import chatsync, db, file_review as fr, links
from assist import chat

NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


def slide(*paras):
    body = "".join("<a:p>" + "".join(f'<a:r><a:rPr b="{i % 2}"/><a:t>{t}</a:t></a:r>' for i, t in enumerate(runs)) + "</a:p>" for runs in paras)
    return f'<?xml version="1.0"?><p:sld {NS} mc:Ignorable="p14"><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'


def deck(path, slides, order=None):
    """A minimal .pptx: slideN.xml files, shown in `order` (the presentation's own list)."""
    order = order or list(range(1, len(slides) + 1))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", f'<p:presentation {NS} xmlns:r="r"><p:sldIdLst>'
                   + "".join(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in order) + "</p:sldIdLst></p:presentation>")
        z.writestr("ppt/_rels/presentation.xml.rels", "<Relationships>" + "".join(
            f'<Relationship Id="rId{n}" Type="slide" Target="slides/slide{n}.xml"/>' for n in range(1, len(slides) + 1)) + "</Relationships>")
        for n, s in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{n}.xml", s)


class OfficeText(unittest.TestCase):
    def setUp(self):
        _t = mock.patch.object(chat, "summarize_later", lambda tid: None)   # no real Claude call to name a conversation
        _t.start()
        self.addCleanup(_t.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_slides_follow_the_decks_order(self):
        deck(self.d / "d.pptx", [slide(["Appendix"]), slide(["Overview"])], order=[2, 1])
        self.assertEqual([s["paras"] for s in fr.read_file(self.d / "d.pptx")], [["Overview"], ["Appendix"]])

    def test_an_edit_changes_only_its_words_and_keeps_the_runs(self):
        deck(self.d / "d.pptx", [slide(["Q2 2026 delivered ", "ARR of $15.8M", " against budget"], ["Ending ARR $15.8M"]), slide(["ARR of $15.8M"])])
        applied, failed = fr.apply_edits(self.d / "d.pptx", self.d / "out" / "d2.pptx", [
            {"id": "c1", "find": "delivered ARR of $15.8M", "replace": "delivered ARR of $16.1M", "where": "Slide 1 · Overview"},
            {"id": "c2", "find": "ARR of $15.8M", "replace": "ARR of $16.1M", "where": "Slide 2"},    # the slide named first
            {"id": "c3", "find": "Marg ie Capital", "replace": "x", "where": ""}])                 # not in the file
        self.assertEqual((applied, failed), ({"c1": "slide 1", "c2": "slide 2"}, ["c3"]))
        out = fr.read_file(self.d / "out" / "d2.pptx")
        self.assertEqual(out[0]["paras"], ["Q2 2026 delivered ARR of $16.1M against budget", "Ending ARR $15.8M"])
        self.assertEqual(out[1]["paras"], ["ARR of $16.1M"])
        with zipfile.ZipFile(self.d / "out" / "d2.pptx") as z:
            x = z.read("ppt/slides/slide1.xml").decode()
            self.assertIn('mc:Ignorable="p14"', x)                  # namespaces and declarations kept as they were
            self.assertIn('<a:rPr b="1"/><a:t>ARR of $16.1M</a:t>', x)   # the bold run holds the new figure
            self.assertIn('<a:rPr b="0"/><a:t>Q2 2026 delivered </a:t>', x)   # untouched
            self.assertEqual(z.read("[Content_Types].xml"), b"<Types/>")

    def test_sharepoint_spacing_and_quotes_still_find_the_words(self):
        self.assertTrue(fr.found("©2025 Marg ie Capital", "©2025 Margie Capital, LLC"))
        self.assertTrue(fr.found("the “new” SKUs", 'the "new" SKUs'))
        self.assertFalse(fr.found("Margie Capital", "©2025 Margie Capital, LLC"))

    def test_word_keeps_the_spaces_at_a_runs_edge(self):
        doc = ('<w:document xmlns:w="w"><w:body><w:p w:rsidR="1"><w:r><w:t>Revenue grew </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>12%</w:t></w:r></w:p>'
               '<w:p/><w:p><w:pPr/><w:r><w:t>Next</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(self.d / "r.docx", "w") as z:
            z.writestr("word/document.xml", doc)
        applied, _ = fr.apply_edits(self.d / "r.docx", self.d / "r2.docx", [{"id": "c1", "find": "grew 12%", "replace": "grew 14%", "where": ""}])
        self.assertEqual(applied, {"c1": "the document"})
        self.assertEqual(fr.read_file(self.d / "r2.docx")[0]["paras"], ["Revenue grew 14%", "Next"])
        with zipfile.ZipFile(self.d / "r2.docx") as z:
            x = z.read("word/document.xml").decode()
            self.assertIn('<w:t>Revenue grew </w:t>', x)                  # untouched: only the differing digit changed
            self.assertIn('<w:rPr><w:b/></w:rPr><w:t>14%</w:t>', x)      # still bold
        applied, _ = fr.apply_edits(self.d / "r.docx", self.d / "r3.docx", [{"id": "c1", "find": "grew 12%", "replace": "grew by 12%", "where": ""}])
        with zipfile.ZipFile(self.d / "r3.docx") as z:   # an insertion at a run's edge keeps the run's spaces
            self.assertIn('<w:t xml:space="preserve">Revenue grew by </w:t>', z.read("word/document.xml").decode())


class Review(unittest.TestCase):
    def setUp(self):
        _t = mock.patch.object(chat, "summarize_later", lambda tid: None)   # no real Claude call to name a conversation
        _t.start()
        self.addCleanup(_t.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.con = db.connect(self.d / "t.db")
        self.addCleanup(self.con.close)
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('teams', 'teams', 't')")
        for target, value in ((links, "DOWNLOADS"), (fr, "JOB_DIR")):
            p = mock.patch.object(target, value, self.d / value.lower())
            p.start()
            self.addCleanup(p.stop)
        (self.d / "downloads").mkdir()
        deck(self.d / "downloads" / "Q2 report.pptx", [slide(["Operational initiatives"]), slide(["R&D: ", "COPILOT early access in Q3"])])
        iid = chatsync.store_record(self.con, {"source_id": "teams", "external_id": "m1", "conversation_name": "Chat with Tatum", "conversation_kind": "dm",
                                               "conversation_id": "19:x", "ts": "2026-10-28T17:37:12Z", "author": "Tatum Easton",
                                               "body_text": "can you review this deck and update slide 2 as needed?",
                                               "attachments": [{"name": "Q2 report.pptx", "url": "https://x-my.sharepoint.com/personal/j/Documents/Q2%20report.pptx"}]})
        self.att = self.con.execute("SELECT id FROM chat_attachments WHERE item_id=?", (iid,)).fetchone()[0]
        self.con.commit()

    def test_clean_keeps_known_citations_and_edits_that_are_in_the_file(self):
        rv = fr.clean({"verdict": "Nearly ready [S1] [S9].", "comments": [
            {"where": "Slide 2", "kind": "update", "what": "COPILOT shipped in October [S1].", "why": "The release note [S1] [S7].", "confidence": "confirmed",
             "find": "COPILOT early access in Q3", "replace": "COPILOT generally available since October"},
            {"where": "Slide 1", "kind": "fix", "what": "Wrong title.", "confidence": "sure", "find": "Not in the deck", "replace": "New title"}]},
            {"S1": {"kind": "email"}}, "Operational initiatives\nR&D: COPILOT early access in Q3")
        self.assertEqual(rv["verdict"], "Nearly ready [S1].")
        a, b = rv["comments"]
        self.assertEqual((a["why"], a["find"], a["replace"]), ("The release note [S1].", "COPILOT early access in Q3", "COPILOT generally available since October"))
        self.assertEqual((a["before"], a["after"]), ("R&D: ", ""))   # the words around it, in its own paragraph
        self.assertEqual((b["find"], b["suggested"], b["confidence"]), ("", "New title", "unverified"))

    def test_review_then_the_updated_deck_and_the_reply_brief(self):
        def model(prompt, purpose):
            if purpose == "review-plan":
                self.assertIn("update slide 2", prompt)
                return json.dumps({"focus": "Update slide 2", "claims": [{"where": "Slide 2", "claim": "COPILOT early access", "search": "COPILOT release"}], "data": []})
            self.assertIn("## Slide 2\nR&D: COPILOT early access in Q3", prompt)   # the file's own text, by slide
            return json.dumps({"verdict": "Slide 2 is out of date.", "comments": [
                {"where": "Slide 2 · R&D", "kind": "update", "what": "COPILOT is generally available now.", "why": "", "confidence": "likely",
                 "find": "COPILOT early access in Q3", "replace": "COPILOT generally available since October"}],
                "questions": ["Confirm the GA date"], "reply": ["Slide 2 updated for COPILOT GA"]})
        with mock.patch.object(fr, "gather", return_value=("", {})):
            rec = fr.write_now(self.con, self.att, "", run_model=model)
        self.assertEqual((rec["source"], rec["decisions"]), ("file", {"c1": True}))
        fr.save(self.att, rec)
        with mock.patch("assist.claude_open.workspace", return_value=self.d / "ws"):
            out = fr.make_file(self.con, self.att)
        self.assertEqual((out["name"], out["applied"]), ("Q2 report - SA edits.pptx", {"c1": "slide 2"}))
        self.assertEqual(fr.read_file(Path(out["path"]))[1]["paras"], ["R&D: COPILOT generally available since October"])
        brief = fr.reply_brief(fr.latest(self.att))
        self.assertIn("updated version is attached (Q2 report - SA edits.pptx); it changes: Slide 2 · R&D.", brief)
        self.assertIn("Points to make: (1) Slide 2 updated for COPILOT GA", brief)
        self.assertNotIn("Confirm the GA date", brief)   # Sam's own to-check list is not for the colleague
        self.assertEqual(fr.summaries([self.att, 999]), {self.att: {"comments": 1, "edits": 1, "made": 1, "created_at": rec["created_at"],
                                                                    "verdict": "Slide 2 is out of date."}})
        st = fr.state(self.con, self.att)
        self.assertEqual((st["file"]["where"], st["review"]["output"]["name"]), ("Downloads", "Q2 report - SA edits.pptx"))

    def test_edits_from_the_chat_join_the_review(self):
        ids = fr.add_edits(self.con, self.att, [{"where": "Slide 2", "what": "Shorter", "find": "COPILOT early access in Q3", "replace": "COPILOT early access"},
                                               {"where": "Slide 1", "what": "Retitle", "find": "Not in the deck", "replace": "Operations"}])
        rec = fr.latest(self.att)
        a, b = rec["review"]["comments"]
        self.assertEqual((a["id"], a["find"], a["before"], rec["decisions"]), (ids[0], "COPILOT early access in Q3", "R&D: ", {ids[0]: True}))
        self.assertEqual((b["find"], b["suggested"]), ("", "Operations"))   # its words are not in the file: Sam puts it in himself
        self.assertEqual(fr.add_edits(self.con, self.att, [{"find": "COPILOT early access in Q3", "replace": "COPILOT early access"}]), [ids[0]])   # the same edit once
        text = fr.as_text(self.con, self.att)
        self.assertIn(f"- {ids[0]} · Slide 2 · update · confirmed [kept]: Shorter", text)
        self.assertIn("## The file's text (by slide)\n## Slide 1\nOperational initiatives", text)

    def test_the_review_lives_in_its_own_chat_conversation(self):
        from assist import chat
        with mock.patch.object(chat, "seed", return_value="t1") as seed, mock.patch.object(chat, "thread", return_value={"id": "t1", "turns": [{"text": f"```review {self.att}\n```"}]}), \
                mock.patch.object(fr, "start", return_value="j1") as start:
            first = fr.start_chat(self.con, self.att)
            again = fr.start_chat(self.con, self.att)
        self.assertEqual((first, seed.call_count, start.call_count), ({"thread": "t1", "job": "j1", "new": True}, 1, 2))
        self.assertEqual(again["thread"], "t1")
        self.assertIn(f"```review {self.att}\n```", seed.call_args[0][2])   # the first answer is the review card
        self.assertIn(f"ask-review {self.att}", seed.call_args[0][3])

    def test_a_review_block_in_a_chat_answer_starts_the_review(self):
        """Sam asks for a review in the chat: the ```review block starts it once, with its focus, in that conversation."""
        other = chatsync.store_record(self.con, {"source_id": "teams", "external_id": "m2", "conversation_name": "Chat with Tatum", "conversation_kind": "dm",
                                                 "conversation_id": "19:x", "ts": "2026-10-28T18:00:00Z", "author": "Tatum Easton", "body_text": "and this one",
                                                 "attachments": [{"name": "Unread.pptx", "url": "https://x-my.sharepoint.com/personal/j/Documents/Unread.pptx"}]})
        unread = self.con.execute("SELECT id FROM chat_attachments WHERE item_id=?", (other,)).fetchone()[0]
        answer = f"On it.\n\n```review {self.att}\nCheck the Q2 numbers\n```\n\n```review {unread}\n```"
        with mock.patch.object(fr.JOBS, "start", return_value="j1") as start:
            self.assertEqual(fr.from_chat(self.con, "t9", answer, "review the deck"), ["j1"])   # the file SleePO cannot read is left
            self.assertEqual(start.call_args[0][0], {"attachment_id": self.att, "ask": "Check the Q2 numbers", "chat_thread": "t9"})
            fr.save(self.att, {"attachment_id": self.att, "review": {"verdict": "ok", "comments": []}})
            self.assertEqual(fr.from_chat(self.con, "t9", f"```review {self.att}\n```", "show me"), [])   # it has a review: the card shows it
            self.assertEqual(fr.from_chat(self.con, "t9", f"```review {self.att} new\n```", "review it again for tone"), ["j1"])
            self.assertEqual(start.call_args[0][0]["ask"], "review it again for tone")   # no focus line: his question


class MessageInChat(unittest.TestCase):
    """Review beside a bubble in Messages opens the message in Ask SleePO with its files and context, waiting for Sam
    (assist/message_chat.py)."""
    def setUp(self):
        _t = mock.patch.object(chat, "summarize_later", lambda tid: None)   # no real Claude call to name a conversation
        _t.start()
        self.addCleanup(_t.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.con = db.connect(self.d / "t.db")
        self.addCleanup(self.con.close)
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('teams', 'teams', 't')")
        p = mock.patch.object(fr, "JOB_DIR", self.d / "reviews")
        p.start()
        self.addCleanup(p.stop)
        rec = {"source_id": "teams", "conversation_name": "Chat with Tatum", "conversation_kind": "dm", "conversation_id": "19:x", "author": "Tatum Easton"}
        chatsync.store_record(self.con, {**rec, "external_id": "m0", "ts": "2026-10-28T17:30:00Z", "body_text": "Morning Sam, the Q2 deck is nearly done"})
        self.iid = chatsync.store_record(self.con, {**rec, "external_id": "m1", "ts": "2026-10-28T17:37:12Z", "body_text": "can you review this deck and update slide 2?",
                                                    "attachments": [{"name": "Q2 report.pptx", "url": "https://x-my.sharepoint.com/personal/j/Documents/Q2%20report.pptx"}]})
        self.att = self.con.execute("SELECT id FROM chat_attachments WHERE item_id=?", (self.iid,)).fetchone()[0]
        self.con.commit()

    def test_the_message_opens_with_its_files_and_waits_for_sam(self):
        from assist import chat, message_chat
        with mock.patch.object(chat, "seed", return_value="t1") as seed:
            self.assertEqual(message_chat.start(self.con, self.iid), {"thread": "t1", "new": True})
        title, question, answer, context, files = seed.call_args[0]
        self.assertIsNone(question)   # nothing asked yet: the message is the first answer, then the box waits
        self.assertTrue(answer.startswith(f"```message {self.iid}\n```\n\nI have Tatum's message and the deck"))
        self.assertIn('["Review the deck and suggest changes", "Draft a reply to Tatum", "What does Tatum need from me?"]', answer)
        self.assertIn(f"“Q2 report.pptx”: attachment {self.att}; SleePO has not read it", context)
        self.assertIn('"{workspace}/Message context.md"', context)
        self.assertIn("can you review this deck and update slide 2?", context)
        self.assertIn("Morning Sam, the Q2 deck is nearly done", files["Message context.md"])   # the conversation around it
        self.assertEqual(title, "Tatum Easton: can you review this deck and update slide 2?")
        card = message_chat.card(self.con, self.iid)
        self.assertEqual((card["author"], [(a["id"], a["reviewable"], a["review"]) for a in card["attachments"]]), ("Tatum Easton", [(self.att, True, None)]))

    def test_a_message_reopens_its_conversation(self):
        from assist import chat, message_chat
        self.con.execute("INSERT INTO chat_threads (id, title, created_at, updated_at) VALUES ('t7', 'x', '2026-10-29', '2026-10-29')")
        self.con.execute("INSERT INTO chat_turns (thread_id, role, text, created_at) VALUES ('t7', 'assistant', ?, '2026-10-29')", (f"```message {self.iid}\n```\n\nI have",))
        with mock.patch.object(chat, "thread", return_value={"id": "t7"}), mock.patch.object(chat, "seed") as seed:
            self.assertEqual(message_chat.start(self.con, self.iid), {"thread": "t7", "new": False})
        seed.assert_not_called()
        self.assertIsNone(message_chat.existing(self.con, self.iid + 1))


if __name__ == "__main__":
    unittest.main()
