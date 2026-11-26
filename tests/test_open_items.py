"""Open items and Actions agree (assist/loops.py, assist/todo.py), replies have one definition (assist/replies.py), and
people are matched by identity (assist/relevance.py). Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, loops, relevance, replies, todo


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        c = self.con
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox', 'outlook', 'i'), ('outlook.sent', 'outlook', 's')")
        c.executemany("INSERT INTO people(id, name) VALUES (?, ?)",
                      [(1, "Rowan Lowell"), (2, "Sam Doe"), (3, "Pat Noel"), (4, "Glen Yardley"), (5, "Hollis Collins"), (6, "Gray Selby")])
        c.executemany("INSERT INTO people_aliases VALUES (?, ?)",
                      [("rowan.lowell@acme.example", 1), ("rowan", 1), ("pat", 3), ("pat lee", 3), ("glen", 4), ("gray", 6)])
        c.commit()
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def loop(self, kind, title, days=3, person=None, fact_type="commitment", fact_id=None, status="open"):
        self.n += 1
        cur = self.con.execute("INSERT INTO loops (kind, title, person_id, origin_at, status, fact_type, fact_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                               (kind, title, person, ago(days), status, fact_type, fact_id or 1000 + self.n, ago(days)))
        self.con.commit()
        return cur.lastrowid

    def mail(self, folder, frm, to, subject, days, conv=None, name=None):
        self.n += 1
        i = self.n + 500
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (?,?,?,?,?,?)",
                         (i, "outlook.sent" if folder == "sentitems" else "outlook.inbox", f"x{i}", "mail", ago(days), ago(days)))
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, conversation_id, from_name, from_address, to_json, cc_json, subject, "
                         "received_at, sent_at, body_text, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (i, f"G{i}", folder, conv or f"conv-{subject}", name or frm.split("@")[0], frm, json.dumps([{"address": a} for a in to]), "[]",
                          subject, ago(days), ago(days), "body", ago(0)))
        self.con.commit()
        return i


class DueDates(unittest.TestCase):
    def test_named_date_after_the_start_is_the_due_date(self):
        self.assertEqual(loops.due_in_text("Reconcile the timeline before 21:00 Tue 6 Oct", "2026-10-05T10:00:00Z"), "2026-10-06")
        self.assertEqual(loops.due_in_text("contoso LIVE (5 Nov): storyline; Japanese translation due 18 Oct", "2026-10-06"), "2026-10-18")
        self.assertEqual(loops.due_in_text("Prepare the plan for the 1:1 Fri 9 Oct 13:00", "2026-10-07"), "2026-10-09")

    def test_dates_that_are_not_deadlines_are_ignored(self):
        self.assertIsNone(loops.due_in_text("Record the outcome of Mon 5 Oct noon", "2026-10-06"))    # before it started
        self.assertIsNone(loops.due_in_text("Gray asked twice (27 & 30 Aug)", "2026-08-27"))         # no deadline word
        self.assertIsNone(loops.due_in_text("Book flights (arrive Mon 18 Jan)", "2026-10-09"))         # day-month in the past this year


class Duplicates(Base):
    def test_newer_repeat_is_flagged_and_can_be_kept_apart(self):
        a = self.loop("promise", "Send Milo the Q4 roadmap review, checked with Rowan and Gray", days=5)
        b = self.loop("promise", "Send Milo the Q4 roadmap review (checked with Gray and Rowan)", days=4)
        c = self.loop("promise", "Book flights for the SKO in Tampa", days=4)
        loops.flag(self.con)
        rows = {r["id"]: r for r in self.con.execute("SELECT id, suggestion, dup_of FROM loops")}
        self.assertEqual((rows[b]["suggestion"], rows[b]["dup_of"]), ("duplicate", a))
        self.assertIsNone(rows[a]["suggestion"])
        self.assertIsNone(rows[c]["suggestion"])
        loops.mark_distinct(self.con, b)
        self.assertIsNone(self.con.execute("SELECT suggestion FROM loops WHERE id=?", (b,)).fetchone()[0])
        loops.flag(self.con)
        self.assertIsNone(self.con.execute("SELECT suggestion FROM loops WHERE id=?", (b,)).fetchone()[0])

    def test_dropping_one_clears_the_others_flag(self):
        a = self.loop("decision", "Log decision on usage and entitlement visibility (DEV-59719)", days=5)
        b = self.loop("promise", "Log decision in DEV-59719 (usage and entitlement visibility)", days=4)
        loops.flag(self.con)
        self.assertEqual(self.con.execute("SELECT suggestion FROM loops WHERE id=?", (b,)).fetchone()[0], "duplicate")
        loops.set_status(self.con, a, "dropped")
        self.assertIsNone(self.con.execute("SELECT suggestion FROM loops WHERE id=?", (b,)).fetchone()[0])

    def test_different_people_or_sides_are_not_duplicates(self):
        self.loop("waiting", "Gray to send the 2027 budget draft", person=6)
        self.loop("promise", "Send the 2027 budget draft", person=None)              # Sam owes vs Gray owes
        self.loop("waiting", "Rowan to send the 2027 budget draft", person=1)           # another person
        loops.flag(self.con)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM loops WHERE suggestion='duplicate'").fetchone()[0], 0)

    def test_decisions_are_retired_a_decision_loop_still_opens_and_closes(self):
        # decisions were retired (Sam, 26 Oct 2026): a bundle's decisions are dropped and counted, and an open item made from
        # one before still changes status without anything underneath
        from assist import ingest
        _run, counts = ingest.ingest_bundle(self.con, {"agent": "test", "decisions": [{"text": "GitLab renewal", "status": "pending"}]})
        self.assertEqual(counts.get("decisions_dropped"), 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)
        lid = self.loop("decision", "GitLab renewal", fact_type="decision", fact_id=7)
        loops.set_status(self.con, lid, "dropped")
        loops.set_status(self.con, lid, "open")
        self.assertEqual(self.con.execute("SELECT status FROM loops WHERE id=?", (lid,)).fetchone()[0], "open")


class ActionsAndOpenItems(Base):
    def action(self, title, category, sources, status="open"):
        tid = db.fingerprint(title)
        self.con.execute("INSERT INTO todo (id, rank, priority, category, title, sources_json, actions_json, status, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?)", (tid, 1, "today", category, title, json.dumps(sources), "[]", status, ago(0), ago(0)))
        self.con.commit()
        return tid

    def status(self, lid):
        return self.con.execute("SELECT status FROM loops WHERE id=?", (lid,)).fetchone()[0]

    def test_done_closes_what_sam_owes_and_rests_what_he_chased(self):
        promise = self.loop("promise", "Send Quinn the remaining budget asks")
        decision = self.loop("decision", "Consolidate the budgets into one P&L")
        waiting = self.loop("waiting", "Isla to send support budget numbers")
        mail = self.mail("inbox", "quinn@acme.example", ["sam.doe@acme.example"], "Budget", 2)
        reply = self.loop("reply", "Reply to Quinn: Budget", fact_type="mail", fact_id=mail)
        background = self.loop("decision", "Pick the 2027 support tooling vendor")
        tid = self.action("Send Quinn the asks and answer the P&L offer", "chase",
                          [{"ref": f"L{promise}", "loop_id": promise, "closes": True}, {"ref": f"L{decision}", "loop_id": decision, "closes": True},
                           {"ref": f"L{waiting}", "loop_id": waiting, "closes": True}, {"ref": f"E{mail}", "item_id": mail, "closes": True},
                           {"ref": f"L{background}", "loop_id": background, "closes": False}])
        todo.set_status(self.con, tid, "done")
        self.assertEqual([self.status(x) for x in (promise, decision, reply, waiting, background)], ["done", "done", "done", "snoozed", "open"])
        ref = json.loads(self.con.execute("SELECT close_ref FROM loops WHERE id=?", (promise,)).fetchone()[0])
        self.assertIn(tid, ref["url"])
        todo.set_status(self.con, tid, "open")   # reopening the action reopens what it closed
        self.assertEqual([self.status(x) for x in (promise, decision, reply)], ["open", "open", "open"])

    def test_older_actions_close_only_the_obvious(self):
        """Actions stored before "closes" existed: the reply they answer and items worded like them, never background."""
        mail = self.mail("inbox", "blake@acme.example", ["sam.doe@acme.example"], "Partner meeting request", 2)
        reply = self.loop("reply", "Reply to Blake: Partner meeting request", fact_type="mail", fact_id=mail)
        same = self.loop("promise", "Ask Milo whether he has seen the Q4 pricing deck")
        background = self.loop("decision", "Agree the partner contract addendum")
        a = self.action("Reply to Blake and Milo on the partner meeting request", "reply",
                        [{"ref": f"E{mail}", "item_id": mail}, {"ref": f"L{background}", "loop_id": background}])
        b = self.action("Ask Milo whether he has seen the Q4 pricing deck", "chase", [{"ref": f"L{same}", "loop_id": same}])
        todo.set_status(self.con, a, "done")
        todo.set_status(self.con, b, "done")
        self.assertEqual([self.status(x) for x in (reply, same, background)], ["done", "done", "open"])

    def test_prep_and_dismiss_close_nothing(self):
        decision = self.loop("decision", "GitLab renewal: renew, renegotiate or change")
        prep = self.action("Prep the CFT and put GitLab on it", "prep", [{"ref": f"L{decision}", "loop_id": decision}])
        todo.set_status(self.con, prep, "done")
        other = self.action("Decide the GitLab renewal", "decide", [{"ref": f"L{decision}", "loop_id": decision}])
        todo.set_status(self.con, other, "dismissed")
        self.assertEqual(self.status(decision), "open")

    def test_action_drops_off_when_its_items_close_elsewhere(self):
        lid = self.loop("promise", "Review Harper's Use Case Explorer")
        tid = self.action("Review Harper's PLT Use Case Explorer", "check", [{"ref": f"L{lid}", "loop_id": lid}])
        loops.set_status(self.con, lid, "done")
        items = {x["id"]: x["status"] for x in todo.listing(self.con)["items"]}
        self.assertNotIn(tid, items)   # superseded: hidden

    def test_newer_message_in_thread_keeps_the_action(self):
        mail = self.mail("inbox", "rowan.lowell@acme.example", ["sam.doe@acme.example"], "Roadmap", 2)
        lid = self.loop("reply", "Reply to Rowan: Roadmap", fact_type="mail", fact_id=mail)
        self.con.execute("UPDATE loops SET status='done', closed_by='auto:thread' WHERE id=?", (lid,))
        tid = self.action("Reply to Rowan on the roadmap", "reply", [{"ref": f"E{mail}", "item_id": mail}])
        self.assertIn(tid, {x["id"] for x in todo.listing(self.con)["items"]})

    def test_reworded_reproposal_of_a_dismissed_action_stays_hidden(self):
        lid = self.loop("promise", "Answer Arden's six PLT questions")
        old = self.action("Answer Arden's PLT questions", "reply", [{"ref": f"L{lid}", "loop_id": lid}])
        todo.set_status(self.con, old, "dismissed")
        refs = {f"L{lid}": {"label": "Open item", "url": "#/loops", "loop_id": lid}}
        todo.store(self.con, [{"title": "Reply to Arden on the six PLT pricing questions", "refs": [f"L{lid}"], "actions": []}], refs)
        new = db.fingerprint("Reply to Arden on the six PLT pricing questions")
        self.assertEqual(self.con.execute("SELECT status FROM todo WHERE id=?", (new,)).fetchone()[0], "superseded")
        todo.store(self.con, [{"title": "Reply to Arden on the six PLT pricing questions", "refs": [f"L{lid}"], "actions": []}], refs)
        self.assertEqual(self.con.execute("SELECT status FROM todo WHERE id=?", (new,)).fetchone()[0], "superseded")   # and the next run


class RepliesAndPeople(Base):
    def test_outside_address_never_matches_a_colleague_by_first_name(self):
        self.assertIsNone(relevance.resolve(self.con, "pat@vendor.example"))
        self.assertEqual(relevance.resolve(self.con, "rowan.lowell@acme.example")["name"], "Rowan Lowell")
        self.assertEqual(relevance.resolve(self.con, "gray@acme.example")["name"], "Gray Selby")
        self.assertIsNone(relevance.resolve(self.con, "glen@acme.example"))    # two Daniels: do not guess

    def test_one_definition_of_needs_reply(self):
        self.mail("inbox", "rowan.lowell@acme.example", ["sam.doe@acme.example"], "Roadmap sign-off", 1)
        self.mail("inbox", "pat@vendor.example", ["sam.doe@acme.example"], "Gift card offer", 1, name="Pat Morgan")
        self.mail("inbox", "rowan.lowell@acme.example", ["sam.doe@acme.example"], "Voice Mail (4 minutes and 59 seconds)", 1)
        got = {m["subject"]: m["needs_reply"] for m in replies.inbox(self.con)}
        self.assertEqual(got, {"Roadmap sign-off": True, "Gift card offer": False, "Voice Mail (4 minutes and 59 seconds)": False})

    def test_reply_loop_closes_when_sam_answered_after_the_window(self):
        old = self.mail("inbox", "rowan.lowell@acme.example", ["sam.doe@acme.example"], "Governance", 20, conv="c-gov")
        self.mail("sentitems", "sam.doe@acme.example", ["rowan.lowell@acme.example"], "Re: Governance", 19, conv="c-gov")
        lid = self.loop("reply", "Reply to Rowan: Governance", days=20, fact_type="mail", fact_id=old)
        loops.sync(self.con, log=lambda *_: None)
        row = self.con.execute("SELECT status, closed_by FROM loops WHERE id=?", (lid,)).fetchone()
        self.assertEqual((row["status"], row["closed_by"]), ("done", "auto:sent"))


if __name__ == "__main__":
    unittest.main()
