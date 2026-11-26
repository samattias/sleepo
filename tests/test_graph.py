"""The Explore graph (assist/graph.py): people are the centre of the ontology. Every edge has a person at one end except
the ties between two things (filed under a bet or area, a topic's meetings, the companies a topic, task or meeting names);
a task that names no one but Sam takes the people on its sources; a thing no person links to is left out and counted as a
gap. Since 29 Oct 2026 it follows the app: tasks (with their steps) instead of open items, companies with what they are to
Acme and the Acme people who deal with them, the top-of-mind topics, and the day-to-day areas.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, entities, graph, meeting_people, tasks, topics


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def snap_person(pid, name, status="active", affiliation="employee", department="", org=""):
    return {"id": f"p-{pid}", "name": name, "status": status, "affiliation": affiliation, "title": "", "org": org, "avatar": "", "department": department}


class Graph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        entities.ensure_schema(c)
        meeting_people.ensure_schema(c)
        tasks.ensure_schema(c)
        topics.ensure_schema(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox','outlook','i'), ('granola','granola','g')")
        c.executemany("INSERT INTO orgs(id, name, kind, relation) VALUES (?,?,?,?)", [(1, "Acme", "internal", None), (2, "Contoso", "partner", None),
                                                                              (3, "Northwind Traders", "account", "customer"), (4, "Acme Ltd", "account", "customer")])
        c.executemany("INSERT INTO people(id, name, is_me, manager_id, org_id, affiliation) VALUES (?,?,?,?,?,?)",
                      [(1, "Sam Doe", 1, None, 1, "employee"), (2, "Gray Selby", 0, None, 1, "employee"), (3, "Rowan Lowell", 0, 1, 1, "employee"),
                       (4, "Marlow Harlow", 0, None, 1, "employee"), (5, "Reese Prescott", 0, None, 2, "partner")])
        c.executemany("INSERT INTO people_aliases VALUES (?,?)", [("gray selby", 2), ("rowan lowell", 3), ("marlow harlow", 4), ("reese prescott", 5)])
        self.n = 0
        self.snap = {"people": [snap_person(1, "Sam Doe", status="me"), snap_person(2, "Gray Selby", department="R&D"),
                                snap_person(3, "Rowan Lowell", department="Product Management"), snap_person(4, "Marlow Harlow", department="Sales"),
                                snap_person(5, "Reese Prescott", affiliation="partner", org="Contoso")],
                     "meetings": [{"id": "m-1", "title": "PLT sync", "date": "2026-10-10", "status": "analysed", "initiatives": ["PLT"]}]}

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def item(self, days, people, kind="mail", src="outlook.inbox", orgs=()):
        """An item with these people taking part: [(person_id, role)], naming these companies."""
        self.n += 1
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, text, pulled_at) VALUES (?,?,?,?,?,?,?,?)",
                         (self.n, src, f"e{self.n}", kind, ago(days), "s", "x", ago(0)))
        for pid, role in people:
            self.con.execute("INSERT INTO mentions(ref_type, ref_id, entity_type, entity_id, confidence, role) VALUES ('item',?,'person',?,1.0,?)",
                             (self.n, pid, role))
        for oid in orgs:
            self.con.execute("INSERT INTO mentions(ref_type, ref_id, entity_type, entity_id, confidence) VALUES ('item',?,'org',?,1.0)", (self.n, oid))
        return self.n

    def task(self, tid, title, status="open", parent=None, owner=None, initiative=None, area=None, sources=(), created=1):
        self.con.execute("INSERT INTO tasks(id, parent_id, initiative_id, area, title, status, owner_person_id, sources_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (tid, parent, initiative, area, title, status, owner, json.dumps([{"item_id": i} for i in sources]), ago(created)))

    def test_people_are_the_hub(self):
        c = self.con
        # Gray and Rowan on the same three small threads, on three different days
        mails = [self.item(d, [(2, "from"), (3, "to"), (1, "to")]) for d in (2, 3, 4)]
        note = self.item(5, [(2, "attendee")], kind="note", src="granola")
        c.execute("INSERT INTO meetings(id, note_item_id, title, starts_at, status) VALUES (1, ?, 'PLT sync', ?, 'analysed')", (note, ago(5)))
        c.executemany("INSERT INTO meeting_people(meeting_id, key, person_id, name, confidence, status) VALUES (1,?,?,?,?, 'suggested')",
                      [("person:2", 2, "Gray Selby", 0.95), ("person:3", 3, "Rowan Lowell", 0.4)])   # Rowan's is too weak to count
        c.execute("INSERT INTO initiatives(id, slug, name, weight, key_people, match_regex) VALUES (1, 'plt', 'PLT', 5, ?, 'PLT')",
                  (json.dumps(["Gray Selby", "Marlow Harlow"]),))   # a spelling without the hyphen still resolves
        # tasks: a step with Rowan; one naming no one, taking the people on its source email; one with no one and no source (a gap);
        # a suggestion still waiting on Sam, and one too old to show
        self.task(1, "Design partnership terms agreed for NWT", initiative=1)
        self.task(2, "Send NWT the pilot dates", parent=1, owner=3)
        self.task(3, "Answer the pricing question", status="suggested", sources=[mails[0]])
        self.task(4, "Renew the design tool licences", area="admin")
        self.task(5, "An old suggestion", status="suggested", sources=[mails[0]], created=graph.SUGGESTED_DAYS + 3)
        # companies: Marlow deals with NWT (two of its emails); Acme only ever reaches Sam (a gap); the meeting names NWT
        for d in (6, 7):
            self.item(d, [(4, "from"), (1, "to")], orgs=[3])
        for d in (6, 7):
            self.item(d, [(1, "to")], orgs=[4])
        c.execute("INSERT INTO mentions(ref_type, ref_id, entity_type, entity_id, confidence) VALUES ('item',?,'org',3,1.0)", (note,))
        c.execute("INSERT INTO topics(run_at, title, summary, ask, initiative_id, area, importance, raised_by, people_json, sources_json, rank, status) "
                  "VALUES (?, 'NWT co-design pilot', 'NWT wants a paid POC.', NULL, NULL, 'team', 'high', 'Gray Selby', ?, ?, 1, 'current')",
                  (ago(0), json.dumps(["Rowan Lowell", "Gray Selby"]), json.dumps([{"kind": "meeting", "app": "#/meetings/m-1"}])))
        g = graph.build(self.snap, c)
        nodes = {n["id"]: n for n in g["nodes"]}
        edges = {(e["source"], e["target"], e["rel"]): e for e in g["edges"]}
        people = {k for k, n in nodes.items() if n["type"] in ("person", "partner")}

        self.assertTrue(nodes["p-1"]["me"])
        for (a, b, rel) in edges:   # the ontology rule: a person at one end, or a tie between two things
            self.assertTrue(rel in ("about", "came up in", "involves", "with") or a in people or b in people, (a, b, rel))
        self.assertEqual(nodes["p-2"]["contact"], 4)                            # four different days in touch
        self.assertGreaterEqual(edges[("p-2", "p-3", "works with")]["w"], 3)
        self.assertIn(("p-3", "p-1", "reports to"), edges)
        self.assertIn(("p-2", "m-1", "attended"), edges)
        self.assertNotIn(("p-3", "m-1", "attended"), edges)
        self.assertIn(("m-1", "i-1", "about"), edges)
        self.assertIn(("p-2", "i-1", "drives"), edges)
        self.assertIn(("p-4", "i-1", "drives"), edges)
        self.assertIn(("p-5", "o-2", "works at"), edges)
        self.assertNotIn("o-1", nodes)                                          # Acme itself is never a node
        # companies: what each is to Acme, the Acme people who deal with it, its page; the meeting that named it
        self.assertEqual((nodes["o-3"]["relation"], nodes["o-3"]["sub"], nodes["o-3"]["href"]), ("customer", "Customer", "/companies/3"))
        self.assertIn(("p-4", "o-3", "deals with"), edges)
        self.assertIn(("m-1", "o-3", "with"), edges)
        self.assertNotIn("o-4", nodes)
        self.assertEqual(g["unlinked"].get("org"), 1)
        # tasks: a step's owner counts for its task; filed under its bet; the company its words name
        self.assertIn(("p-3", "task-1", "owes"), edges)
        self.assertIn(("task-1", "i-1", "about"), edges)
        self.assertIn(("task-1", "o-3", "involves"), edges)                     # "NWT": the initials of Northwind Traders
        self.assertEqual(nodes["p-3"]["tasks"], 2)                              # the step's task, and the one from the email she is on
        self.assertEqual((nodes["task-3"]["status"], nodes["task-3"]["href"]), ("suggested", "/tasks?open=3"))
        self.assertIn(("p-2", "task-3", "involved"), edges)                     # from its source email
        self.assertNotIn("task-2", nodes)                                       # a step is part of its task
        self.assertNotIn("task-4", nodes)
        self.assertNotIn("task-5", nodes)                                       # an old suggestion
        self.assertEqual(g["unlinked"].get("task"), 1)
        self.assertNotIn("area-admin", nodes)                                   # an area shows only with something filed there
        # top of mind: who raised it, who else, the meeting it came up in, its area and the company it names
        tid = next(k for k in nodes if k.startswith("topic-"))
        for e in (("p-2", tid, "raised"), ("p-3", tid, "discussed"), (tid, "m-1", "came up in"), (tid, "area-team", "about"), (tid, "o-3", "involves")):
            self.assertIn(e, edges)
        self.assertNotIn(("p-2", tid, "discussed"), edges)                      # raised it: not counted twice
        self.assertFalse([k for k in nodes if k.startswith(("d-", "l-"))])      # decisions retired (26 Oct), open items not shown (29 Oct)

    def test_company_names_in_text(self):
        nwt, ntt, sps = graph._namer("Northwind Traders"), graph._namer("Contoso"), graph._namer("Company 766")
        self.assertTrue(nwt("NWT co-design partnership") and not nwt("the wider world of technology"))
        self.assertTrue(ntt("contoso LIVE keynote deck") and not ntt("CONTOSO Japan budget"))   # CTS and DATA name several companies
        self.assertTrue(sps("Lucerne pilot via LPS") and not sps("sps"))
        self.assertTrue(graph._namer("Company 845")("Adatum deal") and not graph._namer("Company 845")("bank holiday"))

if __name__ == "__main__":
    unittest.main()
