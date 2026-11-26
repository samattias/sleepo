"""Graph memory, phase 1 (assist/graph_memory.py, DESIGN-GRAPH-MEMORY.md; Sam, 17 Nov 2026): each new item marks the records
it touches, one hop through its sure links and a second along chosen edges; pages read what came in since their record
was written. The code walks the graph; no model call.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, graph_memory
from assist.retention import RETENTION_DAYS


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class GraphMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        c = self.con
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        for sid, system in [("outlook.inbox", "outlook"), ("teams", "teams"), ("granola", "granola"), ("calendar", "calendar")]:
            c.execute("INSERT INTO sources(id, system, name) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING", (sid, system, sid))
        self.me = self.person("The User", is_me=1)
        self.a = self.person("Milo Finance")
        self.b = self.person("Blair Sales")
        self.ours = c.execute("INSERT INTO orgs(name, kind) VALUES ('Our Company', 'internal')").lastrowid
        self.cust = c.execute("INSERT INTO orgs(name, kind) VALUES ('Customer Co', 'account')").lastrowid
        self.bet = c.execute("INSERT INTO initiatives(slug, name, active) VALUES ('pricing', 'Pricing', 1)").lastrowid
        self.old_bet = c.execute("INSERT INTO initiatives(slug, name, active) VALUES ('old', 'Old bet', 0)").lastrowid
        self.task = c.execute("INSERT INTO tasks(title, initiative_id, status, created_at, updated_at) VALUES ('Set MCP credit price', ?, 'open', ?, ?)",
                              (self.bet, iso(self.now - timedelta(days=5)), iso(self.now - timedelta(days=5)))).lastrowid
        self.done = c.execute("INSERT INTO tasks(title, initiative_id, status, created_at) VALUES ('Old task', ?, 'done', ?)",
                              (self.bet, iso(self.now))).lastrowid
        # a topic citing an older email of the thread "conv-1"
        self.m0 = self.mail("conv-1", "MCP credit pricing proposal", days=10)
        self.topic = c.execute("INSERT INTO topics(run_at, title, initiative_id, sources_json, status, updated_at) VALUES (?,?,?,?, 'current', ?)",
                               (iso(self.now - timedelta(days=1)), "MCP credit pricing", self.bet,
                                json.dumps([{"kind": "mail", "key": f"E{self.m0}", "id": self.m0}]), iso(self.now - timedelta(days=1)))).lastrowid
        c.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    # ---- fixtures
    def person(self, name, is_me=0):
        pid = self.con.execute("INSERT INTO people(name, is_me) VALUES (?,?)", (name, is_me)).lastrowid
        self.con.execute("INSERT OR IGNORE INTO people_aliases(alias, person_id) VALUES (?,?)", (name.split()[0].lower() + "@example.com", pid))
        return pid

    def item(self, kind, source, when, subject="", noise=0, payload=None):
        n = self.con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        return self.con.execute("INSERT INTO items(source_id, external_id, kind, ts, from_name, subject, text, payload, noise, pulled_at) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?)", (source, f"x{n}", kind, iso(when), "Milo Finance", subject, subject,
                                                                 json.dumps(payload) if payload else None, noise, iso(self.now))).lastrowid

    def mail(self, conv, subject, days=0, hours=2):
        iid = self.item("mail", "outlook.inbox", self.now - timedelta(days=days, hours=hours), subject)
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, conversation_id, subject, synced_at) VALUES (?,?,?,?,?,?)",
                         (iid, f"g{iid}", "inbox", conv, subject, iso(self.now)))
        return iid

    def link(self, iid, etype, eid, conf, verdict=None, role="from"):
        self.con.execute("INSERT INTO mentions(ref_type, ref_id, entity_type, entity_id, confidence, verdict, role, source) VALUES ('item',?,?,?,?,?,?, 'entities')",
                         (iid, etype, eid, conf, verdict, role))

    def touched(self):
        return {(r["item_id"], r["entity_type"], r["entity_id"]): dict(r) for r in self.con.execute("SELECT * FROM graph_touches")}

    def scenario(self):
        """A new email in the topic's thread from Milo, about the task, copied to the user, our company and the customer."""
        m1 = self.mail("conv-1", "Re: MCP credit pricing proposal")
        for t, e, conf, v in [("person", self.a, 0.95, None), ("person", self.me, 1.0, None), ("org", self.ours, 0.9, None),
                              ("org", self.cust, 0.9, None), ("initiative", self.bet, 0.5, None), ("initiative", self.old_bet, 0.9, None),
                              ("task", self.task, 0.85, None), ("task", self.done, 0.9, None), ("product", 1, 1.0, None)]:
            self.link(m1, t, e, conf, v)
        self.con.commit()
        return m1

    # ---- the walk
    def test_hop_one_follows_sure_links_only(self):
        m1 = self.scenario()
        graph_memory.propagate(self.con)
        t = self.touched()
        self.assertIn((m1, "person", self.a), t)
        self.assertNotIn((m1, "person", self.me), t, "the user is never a record touched")
        self.assertIn((m1, "org", self.cust), t)
        self.assertNotIn((m1, "org", self.ours), t, "our own company is a hub")
        self.assertEqual(t[(m1, "task", self.task)]["hop"], 1)
        self.assertNotIn((m1, "task", self.done), t, "a done task holds nothing to update")
        self.assertNotIn((m1, "initiative", self.old_bet), t, "an inactive bet")
        self.assertFalse(any(k[1] == "product" for k in t), "products hold no record")
        self.assertEqual(t[(m1, "topic", self.topic)]["reason"], "same thread")

    def test_hop_two_reaches_the_bet_through_its_task_or_topic(self):
        m1 = self.scenario()
        graph_memory.propagate(self.con)
        row = self.touched()[(m1, "initiative", self.bet)]
        self.assertEqual(row["hop"], 2, "the keyword link (0.5) is too weak; the bet is reached through the task or topic")
        self.assertIn(row["via_type"], ("task", "topic"))

    def test_hop_two_marks_the_brief_of_a_meeting_the_sender_attends(self):
        start = self.now + timedelta(hours=3)
        ev = self.item("event", "calendar", start, "Pricing review", payload={"id": "ev-1", "subject": "Pricing review", "start": iso(start),
                                                                              "end": iso(start + timedelta(minutes=30)), "attendees": ["milo@example.com"]})
        m1 = self.scenario()
        graph_memory.propagate(self.con)
        row = self.touched().get((m1, "event", ev))
        self.assertIsNotNone(row, "the brief of a meeting Milo attends should hear about Milo's new email")
        self.assertEqual((row["hop"], row["via_type"], row["via_id"]), (2, "person", self.a))

    def test_a_person_is_not_a_pass_through(self):
        other_task = self.con.execute("INSERT INTO tasks(title, initiative_id, status, created_at) VALUES ('Unrelated', ?, 'open', ?)",
                                      (self.bet, iso(self.now))).lastrowid
        self.link(self.m0, "task", other_task, 0.9)   # Milo is linked to another task through an old email
        m1 = self.scenario()
        graph_memory.propagate(self.con)
        self.assertNotIn((m1, "task", other_task), self.touched())

    def test_skipped_items(self):
        rej = self.mail("conv-9", "Rejected link")
        self.link(rej, "person", self.b, 0.95, verdict="rejected")
        noise = self.item("mail", "outlook.inbox", self.now - timedelta(hours=1), "Newsletter", noise=1)
        self.link(noise, "person", self.a, 0.95)
        old = self.mail("conv-8", "Old news", days=5)
        self.link(old, "person", self.a, 0.95)
        note = self.item("note", "granola", self.now - timedelta(hours=1), "Doctor")
        self.con.execute("INSERT INTO meetings(note_item_id, title, status) VALUES (?, 'Doctor', 'personal')", (note,))
        self.link(note, "person", self.a, 0.95)
        self.con.commit()
        graph_memory.propagate(self.con)
        self.assertEqual(self.touched(), {}, "rejected links, noise, items older than the window and personal meetings touch nothing")

    def test_caps_per_item(self):
        m = self.mail("conv-7", "All hands")
        for i in range(12):
            self.link(m, "person", self.person(f"Person {i}"), 0.9)
        self.con.commit()
        graph_memory.propagate(self.con)
        self.assertEqual(sum(1 for k in self.touched() if k[1] == "person"), graph_memory.CAP["person"])

    def test_a_second_pass_writes_nothing(self):
        self.scenario()
        first = graph_memory.propagate(self.con)
        self.con.commit()
        self.assertGreater(first["touches"], 0)
        before = self.con.total_changes
        again = graph_memory.propagate(self.con)
        self.assertEqual(again["touches"], 0)
        self.assertEqual(self.con.total_changes, before, "reads never write: nothing new, nothing written")

    def test_purge_after_retention(self):
        self.scenario()
        graph_memory.propagate(self.con)
        self.con.execute("INSERT INTO graph_touches(item_id, entity_type, entity_id, hop, seen_at) VALUES (1, 'person', 1, 1, ?)",
                         (iso(self.now - timedelta(days=RETENTION_DAYS + 1)),))
        r = graph_memory.propagate(self.con)
        self.assertEqual(r["purged"], 1)

    # ---- reading
    def test_since_the_status_was_written(self):
        m1 = self.scenario()
        self.con.execute("INSERT INTO initiative_updates(initiative_id, status_line, drafted_at, approved_at) VALUES (?, 'old', ?, ?)",
                         (self.bet, iso(self.now - timedelta(days=1)), iso(self.now - timedelta(days=1))))
        graph_memory.propagate(self.con)
        got = graph_memory.since_record(self.con, "initiative", self.bet)
        self.assertEqual(got["count"], 1)
        it = got["items"][0]
        self.assertEqual((it["item_id"], it["hop"], it["kind"]), (m1, 2, "mail"))
        self.assertTrue(it["via"].startswith("through the"))
        self.assertTrue(it["app"].startswith("#/mail?open="))
        # a status written after the walk saw it: nothing new
        self.con.execute("INSERT INTO initiative_updates(initiative_id, status_line, drafted_at, approved_at) VALUES (?, 'new', ?, ?)",
                         (self.bet, iso(self.now + timedelta(minutes=5)), iso(self.now + timedelta(minutes=5))))
        self.assertEqual(graph_memory.since_record(self.con, "initiative", self.bet)["count"], 0)

    def test_first_pass_dates_rows_by_the_items_own_time(self):
        """The first walk ever must not make every record look stale: a status written after an item was sent has seen it."""
        self.scenario()   # the email is 2 hours old
        self.con.execute("INSERT INTO initiative_updates(initiative_id, status_line, drafted_at) VALUES (?, 's', ?)",
                         (self.bet, iso(self.now - timedelta(hours=1))))
        graph_memory.propagate(self.con)
        self.assertEqual(graph_memory.since_record(self.con, "initiative", self.bet)["count"], 0)
        later = self.mail("conv-1", "Re: Re: MCP credit pricing proposal", hours=0)
        self.link(later, "task", self.task, 0.9)
        graph_memory.propagate(self.con)
        self.assertEqual(graph_memory.since_record(self.con, "initiative", self.bet)["count"], 1, "after the first walk, rows are dated when seen")

    def test_a_link_rejected_later_no_longer_counts(self):
        m1 = self.scenario()
        graph_memory.propagate(self.con)
        self.assertEqual(graph_memory.since_record(self.con, "person", self.a)["count"], 1)
        self.con.execute("UPDATE mentions SET verdict='rejected' WHERE ref_id=? AND entity_type='person' AND entity_id=?", (m1, self.a))
        self.assertEqual(graph_memory.since_record(self.con, "person", self.a)["count"], 0)

    def test_stale_and_report(self):
        self.scenario()
        graph_memory.propagate(self.con)
        s = graph_memory.stale(self.con)
        self.assertEqual(s["initiative"], {"stale": 1, "of": 1}, "the bet has no status yet: new material")
        self.assertEqual(s["topic"]["stale"], 1)
        self.assertEqual(s["task"]["stale"], 1)
        text = graph_memory.report_text(self.con)
        self.assertIn("bets: 1 of 1", text)


if __name__ == "__main__":
    unittest.main()
