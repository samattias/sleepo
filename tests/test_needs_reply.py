"""What waits on Sam: only mail and messages that ask him for something (assist/replies.py asked / chat_asked), threads
matched across Apple Mail and Microsoft 365 ids, and the register cleaned up from evidence (assist/loops.py: done actions
as evidence, reworded duplicates). Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import unittest

from assist import evals, loops, replies
from test_open_items import Base, ago

SAM = "sam.doe@acme.example"


def msg(subject="Topic", body="", to=(SAM,), cc=(), frm="Rowan Lowell"):
    return {"subject": subject, "body_text": body, "from_name": frm, "to_json": json.dumps([{"address": a} for a in to]),
            "cc_json": json.dumps([{"address": a} for a in cc])}


class Asked(unittest.TestCase):
    def test_asked_by_name_or_alone(self):
        self.assertTrue(replies.asked(msg(body="Hi Sam,\nCan you approve the roadmap?", to=(SAM, "a@acme.example", "b@acme.example")))[0])
        self.assertTrue(replies.asked(msg(body="Please review.", to=(SAM,)))[0])
        self.assertTrue(replies.asked(msg(body="Hey Milo, Sam,\nWorth a look before Friday?", to=("milo@acme.example", SAM)))[0])
        self.assertTrue(replies.asked(msg(body="Hi all,\nSam, can you confirm the SKU name by Thursday?", to=("a@acme.example",), cc=(SAM,)))[0])

    def test_group_copied_fyi_and_someone_else(self):
        five = (SAM, "a@acme.example", "b@acme.example", "c@acme.example", "d@acme.example")
        cases = {
            "group": msg(body="Team,\nAttached is the latest pipeline analysis. Let me know if you have questions.", to=five),
            "copied": msg(body="Hi,\nWhat is the billing strategy for API resources?", to=("a@acme.example",), cc=(SAM,)),
            "fyi": msg(body="FYI - I have asked lawyers for guidance; will keep you posted.", to=(SAM, "a@acme.example")),
            "someone else": msg(body="Hi Tatum,\nThe OPSDB ticket is created. Can you add the SKU?", to=("tatum@acme.example", SAM)),
            "bare forward": msg(subject="FW: Confidential - contract", body="\nFrom: Someone\nSent: today\n\nold text", to=(SAM,)),
            "bare forward, no blank line": msg(subject="FW: Confidential - contract", body="From: Someone\nSent: today\n\nold text", to=(SAM,)),
            "invite": msg(subject="2027 R&D Org", body="\n________________________________\nMicrosoft Teams meeting\nJoin: https://teams.microsoft.com/meet/1?p=x\nMeeting ID: 26 23",
                          to=(SAM,)),
            "thanks": msg(body="Thanks Sam, will do.", to=(SAM,)),
            "mention, not ask": msg(body="Hi Ellis,\nSam asked me to send you the slides. Could you check them?", to=("don@acme.example",), cc=(SAM,)),
        }
        for name, m in cases.items():
            with self.subTest(name):
                self.assertFalse(replies.asked(m)[0], replies.asked(m)[1])

    def test_a_short_back_and_forth_sam_is_in(self):
        m = msg(body="I'm OK with the end of October, but we should ask West to have Jory confirm in writing that he takes no PTO.",
                to=(SAM, "noel@acme.example"))
        self.assertFalse(replies.asked(m)[0])
        self.assertTrue(replies.asked(m, engaged=True)[0])

    def test_a_word_is_not_a_name(self):
        m = msg(body="Sorry, to be clear, we want both updates: the SKU rename and the description.", to=(SAM,))
        self.assertEqual(replies.asked(m), (True, "sent to you alone"))


class ChatAsked(unittest.TestCase):
    def chat(self, body, kind="group"):
        return replies.chat_asked({"body_text": body, "conversation_kind": kind})[0]

    def test_link_question_mark_is_not_a_question(self):
        self.assertFalse(self.chat("Here is an updated version https://x.sharepoint.com/:u:/g/file.html?e=aLzibI", kind="dm"))
        self.assertTrue(self.chat("Can you look at the updated version?", kind="dm"))

    def test_group_chat_must_ask_sam(self):
        self.assertFalse(self.chat("Hi Ellis-san,\nSam-san asked me to reach out about the session. Could you share the slides?"))
        self.assertFalse(self.chat("Hi Logan Ashby-san, (cc Sam-san, Glen-san)\nThank you. Is the deck OK now?"))
        self.assertFalse(self.chat("皆様\nThe deck is updated. Any comments?"))
        self.assertFalse(self.chat("Hi Ellis-san,\nI've included Sam-san, Glen-san and Blake-san in this thread. Could you share the slides?"))
        self.assertTrue(self.chat("Hi Sam,\nConnect above Modeller Live for the marketecture?"))
        self.assertTrue(self.chat("Updated the deck. @Sam can you check slide 4?"))


class Threads(Base):
    def mail(self, folder, frm, to, subject, days, conv=None, name=None, body="body", cc=()):
        i = super().mail(folder, frm, to, subject, days, conv, name)
        self.con.execute("UPDATE mail_messages SET body_text=?, cc_json=? WHERE item_id=?", (body, json.dumps([{"address": a} for a in cc]), i))
        self.con.commit()
        return i

    def test_reply_with_the_other_thread_id_counts(self):
        # mail before 9 Oct carries a Microsoft 365 conversation id, Sam's reply after it an Apple Mail one
        old = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Roadmap governance review", 5, conv="AAQk-1", body="Hi Sam,\nCan you sign off?")
        self.mail("sentitems", SAM, ["rowan.lowell@acme.example"], "RE: Roadmap governance review", 3, conv="1193")
        got = {m["id"]: m for m in replies.inbox(self.con)}
        self.assertTrue(got[old]["answered"])
        lid = self.loop("reply", "Reply to Rowan: Roadmap governance review", days=5, fact_type="mail", fact_id=old)
        loops.sync(self.con, log=lambda *_: None)
        self.assertEqual(tuple(self.con.execute("SELECT status, closed_by FROM loops WHERE id=?", (lid,)).fetchone()), ("done", "auto:sent"))

    def test_same_subject_with_other_people_is_another_thread(self):
        a = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Weekly product update", 3, conv="c1", body="Hi Sam,\nCan you review?")
        self.mail("sentitems", SAM, ["pat@vendor.example"], "Re: Weekly product update", 2, conv="c2")
        self.assertFalse({m["id"]: m for m in replies.inbox(self.con)}[a]["answered"])

    def test_newer_message_under_the_other_id_takes_over(self):
        a = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Copilot GA announcement", 4, conv="AAQk-2", body="Hi Sam,\nOK to announce?")
        b = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Re: Copilot GA announcement", 1, conv="2201", body="Hi Sam,\nAny view?")
        got = {m["id"]: m for m in replies.inbox(self.con)}
        self.assertFalse(got[a]["latest"])
        self.assertTrue(got[b]["needs_reply"])

    def test_conversation_view_holds_sams_replies_across_ids(self):
        # the Inbox's conversation: received and sent, under either id; same subject with other people is another thread
        a = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Roadmap governance review", 5, conv="AAQk-3", body="Hi Sam,\nCan you sign off?")
        s = self.mail("sentitems", SAM, ["rowan.lowell@acme.example"], "RE: Roadmap governance review", 3, conv="1193",
                      body="Yes, signed off.\n-Sam\n\nFrom: Rowan Lowell\nSent: Monday\nTo: Sam\nSubject: Roadmap governance review\n\nHi Sam,\nCan you sign off?")
        self.mail("sentitems", SAM, ["pat@vendor.example"], "Re: Roadmap governance review", 2, conv="c9")
        got = replies.thread(self.con, a)
        self.assertEqual([x["id"] for x in got], [a, s])
        self.assertTrue(got[1]["me"])
        self.assertTrue(got[1]["snippet"].startswith("Yes, signed off."))
        self.assertNotIn("Can you sign off", got[1]["snippet"])

    def test_conversation_view_shows_one_copy_of_mail_sam_sent_to_himself(self):
        a = self.mail("inbox", "rowan.lowell@acme.example", [SAM, "team@acme.example"], "Product roadmap and governance", 3, conv="c4")
        sent = self.mail("sentitems", SAM, ["team@acme.example"], "Re: Product roadmap and governance", 2, conv="c4")
        copy = self.mail("inbox", SAM, ["team@acme.example"], "Re: Product roadmap and governance", 2, conv="c4")
        self.con.execute("UPDATE mail_messages SET internet_message_id='<m1@x>' WHERE item_id IN (?, ?)", (sent, copy))
        self.con.commit()
        self.assertEqual([x["id"] for x in replies.thread(self.con, a)], [a, sent])
        self.assertEqual([x["id"] for x in replies.thread(self.con, copy)], [a, copy])   # the email being read stays

    def test_open_reply_to_group_mail_is_dropped_with_its_reason(self):
        m = self.mail("inbox", "rowan.lowell@acme.example", [SAM, "a@acme.example", "b@acme.example", "c@acme.example"], "Pipeline analysis", 2,
                      body="Team,\nAttached is the latest analysis.")
        lid = self.loop("reply", "Reply to Rowan: Pipeline analysis", days=2, fact_type="mail", fact_id=m)
        loops.sync(self.con, log=lambda *_: None)
        row = self.con.execute("SELECT status, closed_by, close_reason FROM loops WHERE id=?", (lid,)).fetchone()
        self.assertEqual((row["status"], row["closed_by"]), ("dropped", "auto:fyi"))
        self.assertIn("group mail", row["close_reason"])

    # Sam's own call in the Inbox (loops.mark_reply) wins over the rule, in the Inbox and the register alike
    def flags(self):
        return {m["id"]: m for m in replies.inbox(self.con)}

    def status(self, item):
        return tuple(self.con.execute("SELECT status, closed_by FROM loops WHERE fact_type='mail' AND fact_id=?", (item,)).fetchone())

    def test_sam_removes_an_email_from_needs_reply(self):
        m = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Roadmap sign-off", 1, body="Hi Sam,\nCan you sign off?")
        loops.sync(self.con, log=lambda *_: None)
        self.assertTrue(self.flags()[m]["needs_reply"])
        loops.mark_reply(self.con, m, False)
        self.assertFalse(self.flags()[m]["needs_reply"])
        self.assertEqual(self.flags()[m]["reply_why"], "you said no response is needed")
        loops.sync(self.con, log=lambda *_: None)
        self.assertEqual(self.status(m), ("dropped", "sam"))

    def test_sam_adds_an_email_the_rule_left_out(self):
        m = self.mail("inbox", "rowan.lowell@acme.example", [SAM, "a@acme.example", "b@acme.example", "c@acme.example"], "Pipeline analysis", 2,
                      body="Team,\nAttached is the latest analysis.")
        self.assertFalse(self.flags()[m]["needs_reply"])
        loops.mark_reply(self.con, m, True)
        self.assertEqual((self.flags()[m]["needs_reply"], self.flags()[m]["reply_why"]), (True, "you added it to Needs response"))
        loops.sync(self.con, log=lambda *_: None)   # not dropped as group mail
        self.assertEqual(self.status(m), ("open", None))
        self.mail("sentitems", SAM, ["rowan.lowell@acme.example"], "RE: Pipeline analysis", 1)
        loops.sync(self.con, log=lambda *_: None)   # his reply closes it
        self.assertEqual(self.status(m), ("done", "auto:sent"))

    def test_mail_the_rule_left_out_joins_needs_response_when_sleepo_says_so(self):
        # 22 Oct 2026: needs response, not needs reply; group mail can still need a forward to Sam's team
        m = self.mail("inbox", "rowan.lowell@acme.example", [SAM, "a@acme.example", "b@acme.example", "c@acme.example"], "Security advisory", 1,
                      body="Team,\nA critical PHP vulnerability was disclosed.")
        self.assertFalse(self.flags()[m]["needs_reply"])
        self.con.execute("INSERT INTO response_calls (item_id, response, recipients, why, created_at) VALUES (?, 'forward', '[]', 'forward to Gray: engineering should patch', '2026-10-22T09:00:00Z')", (m,))
        f = self.flags()[m]
        self.assertEqual((f["needs_reply"], f["reply_why"], f["response"]), (True, "SleePO: forward to Gray: engineering should patch", "forward"))
        loops.mark_reply(self.con, m, False)   # Sam's own call still wins
        self.assertFalse(self.flags()[m]["needs_reply"])

    def test_added_mail_older_than_the_window_still_waits(self):
        m = self.mail("inbox", "rowan.lowell@acme.example", [SAM, "a@acme.example", "b@acme.example", "c@acme.example"], "Old thread", 20, body="Team,\nNotes.")
        self.assertNotIn(m, self.flags())
        loops.mark_reply(self.con, m, True)
        self.assertTrue(self.flags()[m]["needs_reply"])
        loops.sync(self.con, log=lambda *_: None)
        self.assertEqual(self.status(m), ("open", None))
        loops.mark_reply(self.con, m, False)   # and removing it again takes it off
        self.assertNotIn(m, self.flags())
        self.assertEqual(self.status(m), ("dropped", "sam"))

    def test_added_mail_stays_when_the_window_holds_more_than_the_limit(self):
        # 28 Oct 2026: 359 emails in 14 days against a cap of 300 dropped what Sam had added from Needs response
        m = self.mail("inbox", "rowan.lowell@acme.example", [SAM, "a@acme.example", "b@acme.example", "c@acme.example"], "2027 Dev", 5, body="Team,\nNotes.")
        for i in range(4):
            self.mail("inbox", "rowan.lowell@acme.example", [SAM], f"Newer {i}", 1, body="Hi Sam,\nNotes.")
        loops.mark_reply(self.con, m, True)
        f = {x["id"]: x for x in replies.inbox(self.con, limit=3)}
        self.assertTrue(f[m]["needs_reply"])

    def test_reopening_a_dropped_fyi_keeps_it_open(self):
        m = self.mail("inbox", "rowan.lowell@acme.example", [SAM, "a@acme.example", "b@acme.example", "c@acme.example"], "Pricing notes", 2, body="Team,\nNotes.")
        lid = self.loop("reply", "Reply to Rowan: Pricing notes", days=2, fact_type="mail", fact_id=m)
        loops.sync(self.con, log=lambda *_: None)
        self.assertEqual(self.status(m), ("dropped", "auto:fyi"))
        loops.set_status(self.con, lid, "open")
        loops.sync(self.con, log=lambda *_: None)
        self.assertEqual(self.status(m), ("open", None))
        self.assertTrue(self.flags()[m]["needs_reply"])

    # eval-needs-reply scores the rule against those calls: removed but flagged is a false positive, added but left out a miss
    def sam_calls(self, days=20):
        return evals.eval_needs_reply(self.con, days=days, log=lambda *_: None, record=False)["sam_calls"]

    def test_eval_scores_the_rule_against_sams_calls(self):
        four = [SAM, "a@acme.example", "b@acme.example", "c@acme.example"]
        fp = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Roadmap sign-off", 2, body="Hi Sam,\nCan you sign off?")
        agreed = self.mail("inbox", "rowan.lowell@acme.example", ["pat@acme.example"], "Billing", 2, cc=[SAM], body="Hi,\nWhat is the billing strategy?")
        miss = self.mail("inbox", "rowan.lowell@acme.example", four, "Pipeline analysis", 3, body="Team,\nAttached is the latest analysis.")
        hit = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Copilot GA announcement", 3, body="Hi Sam,\nOK to announce?")
        old = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Price list", 4, body="Please review the price list.")
        done = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "SKU names", 4, body="Hi Sam,\nCan you confirm the SKU names?")
        far = self.mail("inbox", "rowan.lowell@acme.example", four, "Old notes", 30, body="Team,\nNotes.")
        for m in (fp, agreed):
            loops.mark_reply(self.con, m, False)
        for m in (miss, hit, far):
            loops.mark_reply(self.con, m, True)
        loops.set_status(self.con, self.loop("reply", "Reply to Rowan: Price list", fact_type="mail", fact_id=old), "dropped")   # in Open items
        loops.set_status(self.con, self.loop("reply", "Reply to Rowan: SKU names", fact_type="mail", fact_id=done), "done")   # dealt with: no label
        got = self.sam_calls()   # the 30-day-old email is outside the window
        self.assertEqual(got["removed"], {"n": 3, "in_inbox": 2, "in_open_items": 1, "rule_flagged": 2,
                                          "false_positives": {"addressed to you by name": 1, "sent to you alone": 1}})
        self.assertEqual(got["added"], {"n": 2, "rule_left_out": 1, "misses": {"group mail, not asked by name": 1}})

    def test_eval_counts_sams_later_call(self):
        four = [SAM, "a@acme.example", "b@acme.example", "c@acme.example"]
        a = self.mail("inbox", "rowan.lowell@acme.example", four, "Pricing notes", 2, body="Team,\nNotes.")
        b = self.mail("inbox", "rowan.lowell@acme.example", four, "Partner notes", 2, body="Team,\nNotes from the call.")
        c = self.mail("inbox", "rowan.lowell@acme.example", [SAM], "Roadmap sign-off", 2, body="Hi Sam,\nCan you sign off?")
        loops.mark_reply(self.con, a, True)
        loops.mark_reply(self.con, a, False)   # added, then removed
        lb = self.loop("reply", "Reply to Rowan: Partner notes", fact_type="mail", fact_id=b)
        loops.set_status(self.con, lb, "open")
        loops.set_status(self.con, lb, "dropped")   # reopened, then dropped in Open items
        lc = self.loop("reply", "Reply to Rowan: Roadmap sign-off", fact_type="mail", fact_id=c)
        loops.set_status(self.con, lc, "dropped")
        loops.set_status(self.con, lc, "open")   # dropped, then reopened
        self.mail("sentitems", SAM, ["rowan.lowell@acme.example"], "RE: Roadmap sign-off", 1)
        loops.sync(self.con, log=lambda *_: None)   # his reply closes it; still a mail he said needs a reply
        self.assertEqual(self.status(c), ("done", "auto:sent"))
        got = self.sam_calls()
        self.assertEqual((got["removed"]["n"], got["removed"]["in_inbox"], got["removed"]["in_open_items"], got["removed"]["rule_flagged"]), (2, 1, 1, 0))
        self.assertEqual((got["added"]["n"], got["added"]["rule_left_out"]), (1, 0))


class CleanUp(Base):
    def test_reworded_duplicates_from_the_model_are_flagged_not_merged(self):
        a = self.loop("promise", "Answer Arden's six PLT questions in the FAQ doc", days=8)
        b = self.loop("reply", "Reply to Arden Foster: PLT questions: technical/pricing model", days=7, fact_type="mail")
        c = self.loop("promise", "Prepare the work trip slides", days=6)
        loops.dedupe(self.con, log=lambda *_: None, run_model=lambda *_: json.dumps([{"keep": a, "same": [b], "why": "same questions"}]))
        rows = {r["id"]: r for r in self.con.execute("SELECT id, status, suggestion, dup_of FROM loops")}
        self.assertEqual((rows[b]["suggestion"], rows[b]["dup_of"]), ("duplicate", a))
        self.assertEqual(rows[b]["status"], "open")
        self.assertIsNone(rows[c]["suggestion"])
        loops.mark_distinct(self.con, b)   # Sam: not the same
        loops.flag(self.con)
        self.assertNotEqual(self.con.execute("SELECT suggestion FROM loops WHERE id=?", (b,)).fetchone()[0], "duplicate")

    def test_action_marked_done_is_evidence(self):
        lid = self.loop("promise", "Send Ellis Ingram the latest marketecture slide for the graphic designer", days=6)
        self.con.execute("INSERT INTO todo (id, title, why, status, category, sources_json, actions_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         ("t1", "Send Ellis the latest marketecture slide", "Ellis asked for it for the designer.", "done", "reply", "[]", "[]", ago(4), ago(4)))
        self.con.commit()
        rowid = self.con.execute("SELECT rowid FROM todo WHERE id='t1'").fetchone()[0]
        ev = loops._evidence(self.con, loops._row(self.con, self.con.execute("SELECT * FROM loops WHERE id=?", (lid,)).fetchone()))
        self.assertTrue(any(e.strip().startswith(f"[A{rowid}]") for e in ev))
        loops.review(self.con, log=lambda *_: None, run_model=lambda *_: json.dumps(
            [{"loop": lid, "verdict": "done", "confidence": 0.9, "evidence": f"A{rowid}", "note": f"Done in Actions (A{rowid})."}]))
        row = self.con.execute("SELECT status, closed_by, close_ref, close_reason FROM loops WHERE id=?", (lid,)).fetchone()
        self.assertEqual((row["status"], row["closed_by"]), ("done", "auto:review"))
        self.assertIn("#/actions?open=t1", row["close_ref"])
        self.assertNotIn("A" + str(rowid), row["close_reason"])


if __name__ == "__main__":
    unittest.main()
