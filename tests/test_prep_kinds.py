"""Meeting briefs take the shape of the meeting (assist/prep.py classify, prepgen.SHAPES; Sam, 28 Oct 2026): a 1:1 with
someone in his team is their update, what they owe, his asks and follow-ups; the ELT is his update; a large session is a few
lines; trip logistics get no brief. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import tempfile
import unittest
from pathlib import Path

from assist import db, prep, prepgen


class Classify(unittest.TestCase):
    def test_one_to_ones_by_who_the_other_person_is(self):
        self.assertEqual(prep.classify("Sam <> Gray 1:1", ["team"], "me"), "team_1on1")
        self.assertEqual(prep.classify("1:1 Sam & Milo", ["manager"], "manager"), "manager_1on1")
        self.assertEqual(prep.classify("Sam <> Glen - sync", ["internal"], "me"), "peer_1on1")
        self.assertEqual(prep.classify("Sam & Eden Catch up", ["external"], "external"), "external")

    def test_group_meetings_by_who_runs_them(self):
        self.assertEqual(prep.classify("Product Steering: Weekly", ["team", "team", "internal"], "me"), "you_lead")
        self.assertEqual(prep.classify("ELT Meeting", ["manager", "internal", "internal"], "manager"), "forum")
        self.assertEqual(prep.classify("QBR", ["manager", "internal", "internal"], "internal"), "forum")
        self.assertEqual(prep.classify("Roadmap review & quarterly update", ["team", "internal", "internal"], "team"), "team_leads")
        self.assertEqual(prep.classify("Adatum 10/30 Meeting Prep", ["internal", "internal"], "internal"), "contributor")

    def test_outside_people_large_sessions_and_socials(self):
        self.assertEqual(prep.classify("Adatum pricing", ["internal", "external", "external"], "internal"), "external")
        self.assertEqual(prep.classify("Visit: Ito-sama", ["internal", "manager"], "internal"), "external")   # only Acme on the invite
        self.assertEqual(prep.classify("Meeting with Suzuki-san", ["internal", "internal"], "internal"), "external")
        self.assertEqual(prep.classify("Acme Assist & AI Tools Enablement", ["internal"] * 40, "internal"), "large")
        self.assertEqual(prep.classify("Dinner @ Riverside", ["internal", "manager"], "internal"), "social")

    def test_every_kind_has_a_shape_and_a_word_limit(self):
        self.assertEqual(set(prep.KINDS), set(prepgen.SHAPES))
        for kind, (words, shape) in prepgen.SHAPES.items():
            self.assertLessEqual(words, 260, kind)
            self.assertIn("## ", shape, kind)

    def test_trip_logistics_and_cancellations_get_no_brief(self):
        for s in ("Head to the lodging", "Move to the office", "Check-in at the Lakeside Hotel", "Free", "Waiting Time Before the Presentation",
                  "Lakeside Sightseeing: Meeting Place", "National Holiday"):
            self.assertTrue(prep.LOGISTICS.search(s), s)
        for s in ("Keynote", "Visit: Ito-sama", "Free trial review", "Media Interview, Press(TBD)"):
            self.assertFalse(prep.LOGISTICS.search(s), s)
        self.assertTrue(prep.CANCELLED.match("Canceled: ELT Extented Team Meeting"))
        self.assertTrue(prep.CANCELLED.match("キャンセル済み: Block:JPN Customer Visit, etc"))


class MeetingType(unittest.TestCase):
    """Who is in Sam's team comes from the org chart (people.manager_id), at any depth; his manager is his own manager_id."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        c.execute("INSERT INTO people(id, name) VALUES (36, 'Milo Marsh')")
        c.execute("INSERT INTO people(id, name, manager_id) VALUES (1, 'Sam Doe', 36), (2, 'Gray Selby', 1), (3, 'Finley Kirby', 2), "
                  "(4, 'Glen Yardley', 36)")
        c.execute("UPDATE people SET is_me=1 WHERE id=1")   # the user (assist/profile.py)
        c.executemany("INSERT INTO people_aliases VALUES (?, ?)", [("milo.marsh@acme.example", 36), ("gray.selby@acme.example", 2),
                                                                  ("finley.kirby@acme.example", 3), ("glen.yardley@acme.example", 4)])

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def kind(self, subject, attendees, organiser="Sam.doe@acme.example"):
        ev = {"subject": subject, "attendee_addresses": attendees, "attendees": attendees}
        return prep.meeting_type(self.con, ev, organiser)[0]

    def test_relations_from_the_org_chart(self):
        self.assertEqual(self.kind("Sam <> Finley 1:1", ["finley.kirby@acme.example"]), "team_1on1")   # reports to Gray
        self.assertEqual(self.kind("1:1 Sam & Milo", ["milo.marsh@acme.example"], "milo.marsh@acme.example"), "manager_1on1")
        self.assertEqual(self.kind("Sam <> Glen - sync", ["glen.yardley@acme.example"]), "peer_1on1")
        self.assertEqual(self.kind("Margie AI Discussion", ["sreed@company703.com"], "sreed@company703.com"), "external")
        self.assertEqual(self.kind("ELT Meeting", ["milo.marsh@acme.example", "glen.yardley@acme.example", "Sam.doe@acme.example"],
                                   "milo.marsh@acme.example"), "forum")
        self.assertEqual(self.kind("Design review", ["gray.selby@acme.example", "glen.yardley@acme.example"], "gray.selby@acme.example"), "team_leads")


if __name__ == "__main__":
    unittest.main()
