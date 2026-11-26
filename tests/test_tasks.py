"""Tasks (assist/tasks.py): initiative → task → sub-task → action. Sub-tasks go one level deep, the list holds only what Sam
accepted, a step's close carries to its open item and back, the register's new items become suggestions that expire after
30 days, the start-clean cutover archives what was open, and the Next view ranks by the scoring frame.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, loops, tasks


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        tasks.ensure_schema(self.con)
        c = self.con
        c.executemany("INSERT INTO people(id, name, title) VALUES (?, ?, ?)",
                      [(1, "Rowan Lowell", "Director of Product Management"), (2, "Milo Marsh", "CEO"), (3, "Quinn Irving", "Finance Director")])
        c.executemany("INSERT INTO people_aliases VALUES (?, ?)", [("rowan", 1), ("rowan lowell", 1), ("quinn", 3), ("quinn irving", 3)])
        c.executemany("INSERT INTO initiatives(id, slug, name, weight, active) VALUES (?,?,?,?,1)",
                      [(1, "plt", "PLT / NOVA", 5), (2, "roadmap", "Roadmap & Q4 delivery", 3)])
        c.execute("INSERT INTO initiatives(id, slug, name, weight, active, merged_into) VALUES (3, 'old', 'Budget & finance', 4, 0, 1)")
        c.commit()
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def loop(self, kind, title, days=1, person=None, status="open"):
        self.n += 1
        cur = self.con.execute("INSERT INTO loops (kind, title, person_id, origin_at, status, fact_type, fact_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                               (kind, title, person, ago(days), status, "decision" if kind == "decision" else "commitment", 1000 + self.n, ago(days)))
        self.con.commit()
        return cur.lastrowid

    def get(self, tid):
        return self.con.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()


class Hierarchy(Base):
    def test_a_task_with_steps_and_one_level_only(self):
        t = tasks.create(self.con, {"title": "2027 budget approved", "done_when": "Milo signs it off", "initiative": "plt / nova",
                                    "subtasks": [{"title": "Fill Quinn's template"}, {"title": "Send the numbers", "owner": "Quinn Irving"}]})
        steps = self.con.execute("SELECT * FROM tasks WHERE parent_id=? ORDER BY position", (t,)).fetchall()
        self.assertEqual([s["title"] for s in steps], ["Fill Quinn's template", "Send the numbers"])
        self.assertIsNone(steps[0]["owner"])
        self.assertEqual((steps[1]["owner"], steps[1]["owner_person_id"], steps[1]["kind"]), ("Quinn Irving", 3, "chase"))
        self.assertEqual(self.get(t)["initiative_id"], 1)
        with self.assertRaises(ValueError):
            tasks.create(self.con, {"title": "deeper"}, parent_id=steps[0]["id"])

    def test_a_merged_initiative_resolves_to_where_it_went(self):
        t = tasks.create(self.con, {"title": "x", "initiative": "Budget & finance"})
        self.assertEqual(self.get(t)["initiative_id"], 1)

    def test_moving_a_step_and_promoting_it(self):
        a = tasks.create(self.con, {"title": "Task A", "initiative": 2, "subtasks": [{"title": "Step"}]})
        b = tasks.create(self.con, {"title": "Task B"})
        step = self.con.execute("SELECT id FROM tasks WHERE parent_id=?", (a,)).fetchone()["id"]
        with self.assertRaises(ValueError):   # a task with steps cannot become a step
            tasks.update(self.con, a, {"parent_id": b})
        tasks.update(self.con, b, {"parent_id": a})
        self.assertEqual(self.get(b)["parent_id"], a)
        tasks.update(self.con, step, {"parent_id": None})
        self.assertIsNone(self.get(step)["parent_id"])
        self.assertEqual(self.get(step)["initiative_id"], 2)


class Areas(Base):
    def test_day_to_day_work_goes_under_an_area_never_both(self):
        t = tasks.create(self.con, {"title": "Check PHP exposure", "area": "Admin & operations"})
        r = self.get(t)
        self.assertEqual((r["area"], r["initiative_id"]), ("admin", None))
        u = tasks.create(self.con, {"title": "PLT scope", "initiative": "PLT / NOVA", "area": "admin"})
        self.assertEqual((self.get(u)["area"], self.get(u)["initiative_id"]), (None, 1))   # an initiative wins
        tasks.update(self.con, u, {"area": "team"})
        self.assertEqual((self.get(u)["area"], self.get(u)["initiative_id"]), ("team", None))
        tasks.update(self.con, u, {"initiative_id": 2})
        self.assertEqual((self.get(u)["area"], self.get(u)["initiative_id"]), (None, 2))

    def test_an_area_named_as_the_initiative_is_read_as_meant(self):
        t = tasks.create(self.con, {"title": "Spend review", "initiative": "Admin & operations"})
        self.assertEqual(self.get(t)["area"], "admin")
        p = tasks.clean_proposal(self.con, {"title": "x", "initiative": None, "area": "team & people"}, {}, [])
        self.assertEqual((p["area"], p["initiative_id"]), ("team", None))

    def test_bets_rank_above_day_to_day_work_and_a_step_keeps_its_area(self):
        admin = tasks.create(self.con, {"title": "Spend review", "area": "admin", "subtasks": [{"title": "Pull the numbers"}]})
        bet = tasks.create(self.con, {"title": "Roadmap intake", "initiative": 2})
        data = tasks.listing(self.con)
        by = {t["id"]: t for t in data["tasks"]}
        self.assertGreater(by[bet]["score"], by[admin]["score"])
        self.assertEqual(by[admin]["area_name"], "Admin & operations")
        self.assertEqual([a["key"] for a in data["areas"]][:2], ["admin", "team"])
        step = self.con.execute("SELECT id FROM tasks WHERE parent_id=?", (admin,)).fetchone()["id"]
        tasks.update(self.con, step, {"parent_id": None})
        self.assertEqual(self.get(step)["area"], "admin")


class DeleteAndDocuments(Base):
    def test_delete_hides_a_step_drops_its_item_and_undo_brings_both_back(self):
        lid = self.loop("promise", "Send the deck")
        t = tasks.create(self.con, {"title": "T", "subtasks": [{"title": "Send the deck", "loop_id": lid}, {"title": "Keep"}]})
        s = self.con.execute("SELECT id FROM tasks WHERE parent_id=? AND title='Send the deck'", (t,)).fetchone()["id"]
        tasks.set_status(self.con, s, "deleted")
        x = next(x for x in tasks.listing(self.con)["tasks"] if x["id"] == t)
        self.assertEqual([y["title"] for y in x["subtasks"]], ["Keep"])
        self.assertEqual(self.con.execute("SELECT status FROM loops WHERE id=?", (lid,)).fetchone()["status"], "dropped")
        tasks.set_status(self.con, s, "open")
        self.assertEqual(self.con.execute("SELECT status FROM loops WHERE id=?", (lid,)).fetchone()["status"], "open")
        tasks.set_status(self.con, t, "deleted")
        self.assertEqual(tasks.listing(self.con)["tasks"], [])
        tasks.set_status(self.con, t, "open")
        x = next(x for x in tasks.listing(self.con)["tasks"] if x["id"] == t)
        self.assertEqual(len(x["subtasks"]), 2)

    def test_versions_of_one_file_are_one_family(self):
        f = tasks.family
        self.assertEqual(f("PE_2026-27_Target_Organisation_v14_AW_review_3.pptx"), f("PE_2026-27_Target_Organisation_v12.pptx"))
        self.assertEqual(f("P&E 2027 Budget - Sam Doe v2.xlsx"), f("P&E 2027 Budget - Sam Doe v3.xlsx"))
        self.assertNotEqual(f("P&E 2027 Org Proposal.pptx"), f("P&E 2027 Budget.xlsx"))

    def test_pin_and_hide_documents(self):
        t = tasks.create(self.con, {"title": "Budget", "subtasks": [{"title": "Fill it"}]})
        s = self.con.execute("SELECT id FROM tasks WHERE parent_id=?", (t,)).fetchone()["id"]
        tasks.set_document(self.con, s, "lf-12", "pin")   # a step's call lands on its task
        tasks.set_document(self.con, t, "sp-3", "hide")
        meta = json.loads(self.get(t)["docs_json"])
        self.assertEqual((meta["pinned"], meta["hidden"]), (["lf-12"], ["sp-3"]))
        tasks.set_document(self.con, t, "lf-12", "hide")
        meta = json.loads(self.get(t)["docs_json"])
        self.assertEqual((meta["pinned"], meta["hidden"]), ([], ["lf-12", "sp-3"]))
        row = tasks.task_row(self.con, s)
        self.assertEqual(row["pinned_docs"], [])
        with self.assertRaises(ValueError):
            tasks.set_document(self.con, t, "../etc", "pin")

    def test_a_step_holds_more_than_three_actions(self):
        t = tasks.create(self.con, {"title": "T", "actions": [{"type": "email", "label": f"Email {i}", "to": [], "body": "x"} for i in range(5)]})
        self.assertEqual(len(json.loads(self.get(t)["actions_json"])), 5)


class Preplan(Base):
    def test_a_proposal_is_stored_shown_and_used_once_saved(self):
        from unittest import mock
        p = {"title": "Answer Rowan on the intake form", "done_when": "Rowan has the form", "initiative": "Roadmap & Q4 delivery", "needs_task": False,
             "note": "A short reply does it.", "subtasks": [{"title": "Reply to Rowan", "actions": [{"type": "email", "label": "Reply to Rowan", "body": "x"}]}]}
        src = [{"ref": "E77", "item_id": 77, "label": "Email", "url": "#/inbox?open=77", "closes": True}]
        with mock.patch.object(tasks, "propose_prompt", lambda con, mail=None, meeting=None, ask="", auto=False: ("prompt", {}, src)):
            self.assertTrue(tasks.preplan_one(self.con, 77, run_model=lambda t: json.dumps(p)))
        with mock.patch("assist.replies.inbox", lambda con, **k: []):
            g = tasks.proposal_get(self.con, 77)
        self.assertEqual((g["status"], g["needs_task"], g["note"]), ("ok", False, "A short reply does it."))
        self.assertEqual(g["proposal"]["initiative_id"], 2)
        tid = tasks.save_proposal(self.con, {**g["proposal"], "initiative_id": 2}, "mail")
        with mock.patch("assist.replies.inbox", lambda con, **k: []):
            g = tasks.proposal_get(self.con, 77)
        self.assertEqual((g["status"], g["task_id"], g["task_title"]), ("used", tid, "Answer Rowan on the intake form"))
        tasks.set_status(self.con, tid, "deleted")   # the task is gone: the proposal is offered again
        with mock.patch("assist.replies.inbox", lambda con, **k: []):
            self.assertEqual(tasks.proposal_get(self.con, 77)["status"], "ok")

    def test_mail_a_task_was_made_from_is_not_proposed_again(self):
        from unittest import mock
        tasks.create(self.con, {"title": "From the email", "sources": [{"ref": "E5", "item_id": 5}]})
        inbox = [{"id": 5, "needs_reply": True, "subject": "a"}, {"id": 6, "needs_reply": True, "subject": "b"}, {"id": 7, "needs_reply": False, "subject": "c"}]
        with mock.patch("assist.replies.inbox", lambda con, **k: inbox):
            self.assertEqual([m["id"] for m in tasks.preplan_candidates(self.con)], [6])


class FromMeetings(Base):
    def test_follow_up_actions_become_proposed_steps_once_with_provenance(self):
        from unittest import mock
        lid = self.loop("promise", "Send Oakley the pricing rules")
        md = "# Follow-up · Pricing\n\n**Outcome:** agreed the rules [05:00](#/meetings/m-7?t=300).\n\n```actions\n" + json.dumps([
            {"type": "email", "label": "Send Oakley the pricing rules", "why": "promised", "to": ["k@acme.example"], "body": "x", "meeting": "m-7",
             "said": {"t": 300, "at": "05:00", "me": True, "quote": "I'll send them today"}, "loop": lid},
            {"type": "create", "label": "Draft the MCP credit options", "why": "asked", "format": "docx", "prompt": "x", "meeting": "m-7"}]) + "\n```"
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('granola', 'granola', 'g')")
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (900, 'granola', 'n', 'note', '2026-10-22', '2026-10-22')")
        self.con.execute("INSERT INTO meetings(id, title, note_item_id) VALUES (7, 'Pricing review', 900)")
        self.con.commit()
        with mock.patch("assist.followup.latest", lambda con, mid: {"md": md}):
            self.assertEqual(tasks.propose_from_meeting(self.con, 7), 2)
            self.assertEqual(tasks.propose_from_meeting(self.con, 7), 0)   # once
        steps = tasks.steps_from(self.con, "G7")
        self.assertEqual([s["title"] for s in steps], ["Send Oakley the pricing rules", "Draft the MCP credit options"])
        a = steps[0]
        self.assertEqual((a["status"], a["loop_id"], a["parent_title"], a["parent_status"]), ("suggested", lid, "Follow up: Pricing review", "suggested"))
        self.assertEqual(a["sources"][0]["url"], "#/meetings/m-7?t=300")
        self.assertNotIn("said", a["actions"][0])
        self.assertEqual(steps[1]["kind"], "create")
        tasks.set_status(self.con, a["id"], "open")   # accepting a step accepts its new task
        self.assertEqual(self.get(a["parent_id"])["status"], "open")
        md2 = md.replace("Draft the MCP credit options", "Draft the MCP credit tiers")   # a rewritten follow-up
        with mock.patch("assist.followup.latest", lambda con, mid: {"md": md2}):
            tasks.propose_from_meeting(self.con, 7)
        st = {s["title"]: s["status"] for s in tasks.steps_from(self.con, "G7")}
        self.assertEqual(st, {"Send Oakley the pricing rules": "open", "Draft the MCP credit tiers": "suggested"})

    def test_a_meeting_joins_the_task_it_is_about_and_earlier_steps_move(self):
        from unittest import mock
        t = tasks.create(self.con, {"title": "contoso: next steps on PLT for Japan", "initiative": 2, "owner": "Rowan Lowell"}, "suggested", "assistant")
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('granola', 'granola', 'g')")
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (901, 'granola', 'n2', 'note', '2026-10-22', '2026-10-22')")
        self.con.execute("INSERT INTO mentions(ref_type, ref_id, entity_type, entity_id, confidence) VALUES ('item', 901, 'person', 1, 1.0), ('item', 901, 'initiative', 2, 0.5)")
        self.con.execute("INSERT INTO meetings(id, title, note_item_id) VALUES (9, 'Contoso partnership and PLT messaging', 901)")
        self.con.commit()
        md = "```actions\n" + json.dumps([{"type": "email", "label": "Draft answers to Indigo", "body": "x"}]) + "\n```"
        own = tasks.create(self.con, {"title": "Follow up: Contoso partnership and PLT messaging", "sources": [{"ref": "G9"}]}, "suggested", "meeting")
        old = tasks.create(self.con, {"title": "Draft answers to Indigo", "sources": [{"ref": "G9"}]}, "suggested", "meeting", parent_id=own)
        with mock.patch("assist.followup.latest", lambda con, mid: {"md": md}):
            tasks.propose_from_meeting(self.con, 9)
        self.assertEqual(self.get(old)["parent_id"], t)              # moved to the task the meeting is about
        self.assertEqual(self.get(own)["status"], "expired")         # its own task, now empty, went
        self.assertIsNone(tasks._meeting_target(self.con, 901, "Quarterly marketing review", "x"))   # no shared words: no target

    def test_a_meeting_task_with_no_steps_left_goes(self):
        p = tasks.create(self.con, {"title": "Follow up: X"}, "suggested", "meeting")
        a = tasks.create(self.con, {"title": "a"}, "suggested", "meeting", parent_id=p)
        b = tasks.create(self.con, {"title": "b"}, "suggested", "meeting", parent_id=p)
        tasks.set_status(self.con, a, "dismissed")
        self.assertEqual(self.get(p)["status"], "suggested")
        tasks.update(self.con, b, {"parent_id": None})   # Own task
        self.assertEqual(self.get(p)["status"], "expired")

    def test_steps_go_to_a_task_with_the_same_words(self):
        from unittest import mock
        t = tasks.create(self.con, {"title": "Finalise the MCP pricing model"})
        md = "```actions\n" + json.dumps([{"type": "draft", "label": "Finalise MCP pricing model credits", "prompt": "x"}]) + "\n```"
        self.con.execute("INSERT INTO meetings(id, title, note_item_id) VALUES (8, 'M', NULL)")
        with mock.patch("assist.followup.latest", lambda con, mid: {"md": md}):
            tasks.propose_from_meeting(self.con, 8)
        self.assertEqual(tasks.steps_from(self.con, "G8")[0]["parent_id"], t)


class Closing(Base):
    def test_a_step_done_closes_its_open_item_and_reopening_undoes_it(self):
        lid = self.loop("promise", "Send Rowan the PLT scope")
        t = tasks.create(self.con, {"title": "PLT scope agreed", "subtasks": [{"title": "Send Rowan the PLT scope", "loop_id": lid}]})
        s = self.con.execute("SELECT id FROM tasks WHERE parent_id=?", (t,)).fetchone()["id"]
        tasks.set_status(self.con, s, "done")
        l = self.con.execute("SELECT status, closed_by, close_ref FROM loops WHERE id=?", (lid,)).fetchone()
        self.assertEqual((l["status"], l["closed_by"]), ("done", "sam"))
        self.assertIn(f"#/tasks?open={s}", l["close_ref"])
        tasks.set_status(self.con, s, "open")
        self.assertEqual(self.con.execute("SELECT status FROM loops WHERE id=?", (lid,)).fetchone()["status"], "open")

    def test_closing_a_task_closes_its_open_steps_and_reopening_brings_them_back(self):
        t = tasks.create(self.con, {"title": "T", "subtasks": [{"title": "a"}, {"title": "b"}]})
        a, b = [r["id"] for r in self.con.execute("SELECT id FROM tasks WHERE parent_id=? ORDER BY position", (t,))]
        tasks.set_status(self.con, a, "done")
        tasks.set_status(self.con, t, "done")
        self.assertEqual((self.get(b)["status"], self.get(b)["closed_by"]), ("done", "task"))
        tasks.set_status(self.con, t, "open")
        self.assertEqual(self.get(b)["status"], "open")
        self.assertEqual(self.get(a)["status"], "done")   # Sam's own tick stays

    def test_evidence_in_the_register_closes_the_step(self):
        lid = self.loop("waiting", "Quinn sends the budget template", person=3)
        t = tasks.create(self.con, {"title": "Budget", "subtasks": [{"title": "Get the template", "owner": "Quinn", "loop_id": lid}]})
        loops._close(self.con, lid, "done", "auto:review", "Quinn sent it.", {"label": "Mail", "url": "#/inbox?open=9"})
        self.con.commit()
        tasks.sync(self.con, log=lambda *a: None)
        s = self.con.execute("SELECT * FROM tasks WHERE parent_id=?", (t,)).fetchone()
        self.assertEqual((s["status"], s["closed_by"]), ("done", "auto:review"))
        self.assertEqual(self.get(t)["status"], "open")   # the task waits for Sam's call

    def test_an_email_step_closes_when_sams_reply_is_in_the_thread(self):
        c = self.con
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox','outlook','i'), ('outlook.sent','outlook','s')")
        for i, folder, frm, at in ((501, "inbox", "rowan.lowell@acme.example", ago(2)), (502, "sentitems", "sam.doe@acme.example", ago(0))):
            c.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (?,?,?,?,?,?)",
                      (i, "outlook.sent" if folder == "sentitems" else "outlook.inbox", f"x{i}", "mail", at, at))
            c.execute("INSERT INTO mail_messages(item_id, graph_id, folder, conversation_id, from_name, from_address, to_json, cc_json, subject, "
                      "received_at, sent_at, body_text, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (i, f"G{i}", folder, "conv-1", frm, frm, json.dumps([{"address": "rowan.lowell@acme.example"}]), "[]", "Roadmap intake", at, at, "b", at))
        t = tasks.create(c, {"title": "Answer Rowan on intake", "actions": [{"type": "email", "label": "Reply to Rowan", "reply_to": "G501", "body": "x"}]})
        c.execute("UPDATE tasks SET created_at=? WHERE id=?", (ago(1), t))
        c.commit()
        tasks.sync(c, log=lambda *a: None)
        r = self.get(t)
        self.assertEqual((r["status"], r["closed_by"]), ("done", "auto:sent"))
        self.assertIn("502", r["close_ref"])


class Suggestions(Base):
    def test_cutover_archives_open_items_once_and_keeps_replies(self):
        p = self.loop("promise", "Old promise")
        w = self.loop("waiting", "Old wait")
        r = self.con.execute("INSERT INTO loops (kind, title, status, fact_type, fact_id, created_at) VALUES ('reply','Reply to Rowan','open','mail',77,?)", (ago(1),)).lastrowid
        res = tasks.cutover(self.con, log=lambda *a: None)
        self.assertEqual(res["archived"], 2)
        st = {x["id"]: (x["status"], x["closed_by"]) for x in self.con.execute("SELECT id, status, closed_by FROM loops")}
        self.assertEqual(st[p], ("dropped", "archive"))
        self.assertEqual(st[w], ("dropped", "archive"))
        self.assertEqual(st[r][0], "open")
        self.assertEqual(tasks.cutover(self.con, log=lambda *a: None)["archived"], 0)

    def test_new_register_items_become_suggestions_under_a_matching_task(self):
        tasks.cutover(self.con, log=lambda *a: None)
        t = tasks.create(self.con, {"title": "Finalise the MCP pricing model"})
        new = self.loop("decision", "Finalise MCP pricing model credits", days=0)
        other = self.loop("waiting", "Rowan sends the roadmap intake form", days=0, person=1)
        tasks.sync(self.con, log=lambda *a: None)
        a = self.con.execute("SELECT * FROM tasks WHERE loop_id=?", (new,)).fetchone()
        b = self.con.execute("SELECT * FROM tasks WHERE loop_id=?", (other,)).fetchone()
        self.assertEqual((a["status"], a["parent_id"], a["kind"]), ("suggested", t, "decide"))
        self.assertEqual((b["status"], b["parent_id"], b["owner"]), ("suggested", None, "Rowan Lowell"))
        tasks.sync(self.con, log=lambda *a: None)   # once each
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM tasks WHERE loop_id IN (?,?)", (new, other)).fetchone()[0], 2)
        data = tasks.listing(self.con)
        self.assertEqual({s["id"] for s in data["suggestions"]}, {a["id"], b["id"]})
        self.assertEqual([x["id"] for x in data["tasks"]], [t])

    def test_accepting_and_dismissing(self):
        lid = self.loop("promise", "Write the ORC one-pager", days=0)
        t = tasks.create(self.con, {"title": "ORC one-pager", "loop_id": lid, "subtasks": [{"title": "Outline"}, {"title": "Draft"}]}, "suggested", "assistant")
        tasks.set_status(self.con, t, "open")
        self.assertEqual({r["status"] for r in self.con.execute("SELECT status FROM tasks WHERE parent_id=?", (t,))}, {"open"})
        self.assertIsNotNone(self.get(t)["accepted_at"])
        u = tasks.create(self.con, {"title": "Not wanted", "loop_id": lid}, "suggested", "register")
        tasks.set_status(self.con, u, "dismissed")
        self.assertEqual(self.con.execute("SELECT status, closed_by FROM loops WHERE id=?", (lid,)).fetchone()["status"], "dropped")

    def test_suggestions_expire_after_30_days_and_drop_their_item(self):
        lid = self.loop("promise", "Something old", days=31)
        t = tasks.create(self.con, {"title": "Something old", "loop_id": lid}, "suggested", "register")
        self.con.execute("UPDATE tasks SET created_at=? WHERE id=?", (ago(31), t))
        keep = tasks.create(self.con, {"title": "Accepted long ago"})
        self.con.execute("UPDATE tasks SET created_at=? WHERE id=?", (ago(60), keep))
        self.con.commit()
        tasks.sync(self.con, log=lambda *a: None)
        self.assertEqual(self.get(t)["status"], "expired")
        self.assertEqual(self.get(keep)["status"], "open")
        l = self.con.execute("SELECT status, closed_by FROM loops WHERE id=?", (lid,)).fetchone()
        self.assertEqual((l["status"], l["closed_by"]), ("dropped", "archive:expired"))

    def test_model_suggestions_skip_repeats_and_dismissed(self):
        t = tasks.create(self.con, {"title": "Ship the Q4 roadmap"})
        gone = tasks.create(self.con, {"title": "Book the Team B offsite"}, "suggested", "assistant")
        tasks.set_status(self.con, gone, "dismissed")
        refs = {f"T{t}": {"task_id": t}, "E5": {"label": "Email", "url": "#/inbox?open=5", "item_id": 5}}
        n = tasks.store_suggestions(self.con, [
            {"title": "Ship the Q4 roadmap"},                       # already a task
            {"title": "Book the Team B offsite"},                   # dismissed
            {"add_to": f"T{t}", "subtasks": [{"title": "Ask Rowan for the final dates", "owner": "Rowan Lowell", "refs": ["E5"], "closes": ["E5"]}]},
            {"title": "Agree MCP credit packs", "initiative": "PLT / NOVA", "subtasks": [{"title": "Draft options", "kind": "create"}]},
        ], refs, None, set(), set())
        self.assertEqual(n, 2)
        step = self.con.execute("SELECT * FROM tasks WHERE parent_id=? AND status='suggested'", (t,)).fetchone()
        self.assertEqual(step["owner"], "Rowan Lowell")
        self.assertTrue(json.loads(step["sources_json"])[0]["closes"])
        new = self.con.execute("SELECT * FROM tasks WHERE title='Agree MCP credit packs'").fetchone()
        self.assertEqual((new["status"], new["initiative_id"]), ("suggested", 1))


class NextView(Base):
    def test_ranked_by_weight_date_and_ceo_and_waiting_is_separate(self):
        low = tasks.create(self.con, {"title": "Tidy the roadmap wiki", "initiative": 2})
        high = tasks.create(self.con, {"title": "PLT plan for Milo", "initiative": 1,
                                       "due": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")})
        wait = tasks.create(self.con, {"title": "Budget numbers", "subtasks": [{"title": "Quinn sends numbers", "owner": "Quinn Irving"}]})
        data = tasks.listing(self.con)
        by = {t["id"]: t for t in data["tasks"]}
        self.assertEqual(data["tasks"][0]["id"], high)
        self.assertGreater(by[high]["score"], by[low]["score"])
        self.assertTrue(by[wait]["waiting"])
        self.assertIsNone(by[wait]["next_id"])
        self.assertEqual(by[low]["next_id"], low)   # a task with no steps is its own step
        self.assertIn("Milo Marsh", by[high]["people"])

    def test_untouched_or_past_due_shows_decide_or_drop(self):
        fresh = tasks.create(self.con, {"title": "Fresh"})
        old = tasks.create(self.con, {"title": "Old", "subtasks": [{"title": "Pick the vendor", "kind": "decide"}]})
        late = tasks.create(self.con, {"title": "Late", "due": "2026-01-05"})
        self.con.execute("UPDATE tasks SET created_at=?, updated_at=?, accepted_at=? WHERE id=? OR parent_id=?", (ago(9), ago(9), ago(9), old, old))
        self.con.commit()
        by = {t["id"]: t for t in tasks.listing(self.con)["tasks"]}
        self.assertIsNone(by[fresh]["decide_or_drop"])
        self.assertIn("9 days", by[old]["decide_or_drop"])   # a decision step: 7 days
        self.assertIn("has passed", by[late]["decide_or_drop"])

    def test_a_delegation_is_sams_step_until_he_sends_it(self):
        t = tasks.create(self.con, {"title": "PHP exposure checked", "subtasks": [
            {"title": "Ask Gray to check", "owner": "Quinn Irving", "actions": [{"type": "email", "label": "Email Quinn", "to": ["k@acme.example"], "body": "x"}]}]})
        s = self.con.execute("SELECT id FROM tasks WHERE parent_id=?", (t,)).fetchone()["id"]
        x = next(x for x in tasks.listing(self.con)["tasks"] if x["id"] == t)
        self.assertEqual((x["next_id"], x["waiting"], x["subtasks"][0]["handoff"]), (s, False, True))
        tasks.log_action(self.con, s, 0, "email copied")
        x = next(x for x in tasks.listing(self.con)["tasks"] if x["id"] == t)
        self.assertEqual((x["next_id"], x["waiting"]), (None, True))

    def test_all_steps_done_asks_to_close(self):
        t = tasks.create(self.con, {"title": "T", "subtasks": [{"title": "a"}]})
        s = self.con.execute("SELECT id FROM tasks WHERE parent_id=?", (t,)).fetchone()["id"]
        tasks.set_status(self.con, s, "done")
        x = next(x for x in tasks.listing(self.con)["tasks"] if x["id"] == t)
        self.assertTrue(x["all_done"])
        self.assertEqual((x["steps_done"], x["steps_total"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
