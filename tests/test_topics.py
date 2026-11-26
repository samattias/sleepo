"""Top of mind (assist/topics.py; Sam, 28 Oct 2026): the topics Sam discussed in the last days, each citing where it came up;
who raised it and how often are read from the references, never from the model; a topic Sam set aside stays out until it comes
up again; Make a task files it under its initiative; reading writes nothing.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, speakers, topics
from assist.retention import RETENTION_DAYS


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class TopOfMind(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = topics.STATE
        topics.STATE = t / "topics.json"
        self.con = c = db.connect(t / "t.db")
        db.migrate(c)
        speakers.ensure_schema(c)
        topics.ensure_schema(c)
        self.now = now = datetime.now(timezone.utc)
        c.execute("INSERT INTO people(id, name, is_me) VALUES (1, 'Sam Doe', 1)")
        c.execute("INSERT INTO people(id, name) VALUES (4, 'Glen Yardley')")
        c.execute("INSERT OR IGNORE INTO initiatives(slug, name, weight, active) VALUES ('gtm-marketing', 'GTM & partner enablement', 3, 1)")
        self.ini = c.execute("SELECT id FROM initiatives WHERE slug='gtm-marketing'").fetchone()[0]
        self.meeting("COPILOT early access sunset with Glen", now - timedelta(days=2), [
            ("Glen Yardley", 0, [{"t": 189, "clock": "03:09", "text": "Announce COPILOT GA and switch free access off mid-November."}]),
            ("Sam Doe", 1, [{"t": 64, "clock": "01:04", "text": "COPILOT early access must end now that COPILOT is sold."}])])
        self.meeting("Sam <> Robin sync", now - timedelta(days=1), [("Sam Doe", 1, [{"t": 5, "clock": "00:05", "text": "Weekend plans"}])], status="personal")
        self.meeting("Old roadmap review", now - timedelta(days=12), [("Sam Doe", 1, [{"t": 5, "clock": "00:05", "text": "Roadmap intake"}])])
        c.commit()

    def tearDown(self):
        topics.STATE = self.saved
        self.con.close()
        self.tmp.cleanup()

    def meeting(self, title, start, speakers_, status="analysed"):
        mid = self.con.execute("INSERT INTO meetings (title, starts_at, ends_at, attendees, digest_md, status) VALUES (?,?,?,?,?,?)",
                               (title, iso(start), iso(start + timedelta(minutes=30)), "[]", "", status)).lastrowid
        for name, me, pts in speakers_:
            self.con.execute("INSERT INTO meeting_speakers (meeting_id, name, is_me, words, turns, share, points) VALUES (?,?,?,?,?,?,?)",
                             (mid, name, me, 300, 10, 0.5, json.dumps(pts)))
        return mid

    def refs_by(self, refs, who):
        return next(k for k, v in refs.items() if k.startswith("P") and v["who"] == who)

    def topic(self, pk, title="COPILOT early access sunset", **kw):
        return {"title": title, "initiative": "gtm-marketing", "area": None, "summary": "Free access ends mid-November.",
                "ask": "Agree who sends the customer notice", "importance": "high", "private": False, "task": None,
                "refs": [self.refs_by(pk, "Glen Yardley"), self.refs_by(pk, "you")], **kw}

    def test_pack_cites_each_persons_point_and_leaves_out_personal_and_old_meetings(self):
        text, refs = topics.pack(self.con, now=self.now)
        self.assertIn("COPILOT early access sunset with Glen", text)
        self.assertNotIn("Robin", text)
        self.assertNotIn("Old roadmap review", text)
        mine = refs[self.refs_by(refs, "you")]
        self.assertTrue(mine["me"])
        self.assertTrue(mine["app"].endswith("?t=64"))
        self.assertIn("Sam (you): COPILOT early access must end", text)

    def test_who_raised_it_and_how_often_come_from_the_references(self):
        text, refs = topics.pack(self.con, now=self.now)
        data = {"topics": [self.topic(refs, refs=[self.refs_by(refs, "Glen Yardley"), self.refs_by(refs, "you"), "E999999"]),
                           {"title": "Invented", "refs": ["X1"]},
                           self.topic(refs, title="A small aside", importance="low", ask=None, refs=[self.refs_by(refs, "Glen Yardley")])]}
        out = topics.clean(self.con, data, refs, self.now)
        self.assertEqual([t["title"] for t in out], ["COPILOT early access sunset", "A small aside"])   # the uncited one is dropped
        t = out[0]
        self.assertEqual(t["raised_by"], "you")             # Sam spoke first (01:04, before Glen at 03:09)
        self.assertEqual(out[1]["raised_by"], "Glen Yardley")
        self.assertEqual((t["meetings"], t["mails"], t["initiative_id"], t["people"]), (1, 0, self.ini, ["Glen Yardley"]))
        self.assertEqual(len(t["sources"]), 1)               # one meeting, at its earliest cited moment
        self.assertEqual(t["sources"][0]["clock"], "01:04")
        self.assertGreater(t["score"], out[1]["score"])

    def test_a_topic_set_aside_stays_out_until_it_comes_up_again(self):
        text, refs = topics.pack(self.con, now=self.now)
        topics.store(self.con, topics.clean(self.con, {"topics": [self.topic(refs)]}, refs, self.now))
        tid = self.con.execute("SELECT id FROM topics").fetchone()[0]
        self.assertTrue(topics.set_status(self.con, tid, "dismissed"))
        again = topics.clean(self.con, {"topics": [self.topic(refs, title="COPILOT early access sunset plan")]}, refs, self.now)
        self.assertEqual(topics.store(self.con, again), 0)
        again[0]["last_ts"] = iso(self.now + timedelta(minutes=5))   # it came up after he set it aside
        self.assertEqual(topics.store(self.con, again), 1)
        self.assertIn("COPILOT early access sunset", topics.pack(self.con, now=self.now)[0].split("MEETINGS")[0])   # the run is told

    def test_make_a_task_files_it_under_the_initiative_and_later_runs_keep_the_link(self):
        text, refs = topics.pack(self.con, now=self.now)
        topics.store(self.con, topics.clean(self.con, {"topics": [self.topic(refs)]}, refs, self.now))
        first = topics.listing(self.con)["topics"][0]
        self.assertFalse(first["is_new"])                    # the first run has nothing to compare with
        task = topics.make_task(self.con, first["id"])
        r = self.con.execute("SELECT title, status, initiative_id, sources_json FROM tasks WHERE id=?", (task,)).fetchone()
        self.assertEqual((r["title"], r["status"], r["initiative_id"]), ("COPILOT early access sunset", "open", self.ini))
        self.assertIn("?t=64", r["sources_json"])
        self.assertEqual(topics.make_task(self.con, first["id"]), task)   # twice is the same task
        nxt = topics.clean(self.con, {"topics": [self.topic(refs), self.topic(refs, title="Woodgrove renewal risk")]}, refs, self.now)
        topics.store(self.con, nxt)
        got = {t["title"]: t for t in topics.listing(self.con)["topics"]}
        self.assertEqual(got["COPILOT early access sunset"]["task_id"], task)
        self.assertEqual((got["COPILOT early access sunset"]["is_new"], got["Woodgrove renewal risk"]["is_new"]), (False, True))
        self.assertEqual(topics.by_initiative(self.con)[self.ini][0]["title"], "COPILOT early access sunset")

    def test_a_topic_that_continues_keeps_its_row_and_who_said_what(self):
        text, refs = topics.pack(self.con, now=self.now)
        topics.store(self.con, topics.clean(self.con, {"topics": [self.topic(refs)]}, refs, self.now), now=self.now)
        tid = topics.listing(self.con)["topics"][0]["id"]
        said = topics.listing(self.con)["topics"][0]["sources"][0]["said"]
        self.assertEqual([(x["who"], x["clock"]) for x in said], [("you", "01:04"), ("Glen Yardley", "03:09")])
        self.assertIn("Announce COPILOT GA", said[1]["text"])
        nxt = topics.clean(self.con, {"topics": [self.topic(refs, title="COPILOT early access sunset and notice"), self.topic(refs, title="Woodgrove renewal risk")]}, refs, self.now)
        topics.store(self.con, nxt, now=self.now + timedelta(hours=4))
        got = {t["title"]: t for t in topics.listing(self.con)["topics"]}
        self.assertEqual(got["COPILOT early access sunset and notice"]["id"], tid)   # its page and links stay
        self.assertEqual(len(got), 2)

    def test_a_pinned_topic_comes_first_and_outlives_runs_that_drop_it(self):
        text, refs = topics.pack(self.con, now=self.now)
        run1 = topics.clean(self.con, {"topics": [self.topic(refs, title="Woodgrove renewal risk"), self.topic(refs, title="A small aside", importance="low", ask=None)]}, refs, self.now)
        topics.store(self.con, run1, now=self.now)
        ids = {t["title"]: t["id"] for t in topics.listing(self.con)["topics"]}
        self.assertTrue(topics.set_pin(self.con, ids["A small aside"], True))
        self.assertFalse(topics.set_pin(self.con, ids["A small aside"], True))   # unchanged: no write
        self.assertEqual(topics.listing(self.con)["topics"][0]["title"], "A small aside")
        run2 = topics.clean(self.con, {"topics": [self.topic(refs, title="Woodgrove renewal risk")]}, refs, self.now)
        topics.store(self.con, run2, now=self.now + timedelta(hours=4))
        got = topics.listing(self.con)["topics"]
        self.assertEqual([(t["title"], t["pinned"], t["current"]) for t in got], [("A small aside", True, False), ("Woodgrove renewal risk", False, True)])
        self.assertEqual(topics.one(self.con, ids["A small aside"])["title"], "A small aside")
        topics.set_pin(self.con, ids["A small aside"], False)                 # unpinned: out of the list at once, gone at the next run
        self.assertEqual([t["title"] for t in topics.listing(self.con)["topics"]], ["Woodgrove renewal risk"])
        topics.store(self.con, run2, now=self.now + timedelta(hours=8))
        self.assertIsNone(topics.one(self.con, ids["A small aside"]))

    def test_a_pin_ends_with_the_retention_period(self):
        text, refs = topics.pack(self.con, now=self.now)
        topics.store(self.con, topics.clean(self.con, {"topics": [self.topic(refs)]}, refs, self.now), now=self.now)
        tid = topics.listing(self.con)["topics"][0]["id"]
        old = iso(self.now - timedelta(days=RETENTION_DAYS + 1))
        self.con.execute("UPDATE topics SET pinned_at=?, last_ts=? WHERE id=?", (old, old, tid))
        topics.store(self.con, [], now=self.now + timedelta(hours=4))
        self.assertIsNone(topics.one(self.con, tid))

    def test_reading_writes_nothing(self):
        text, refs = topics.pack(self.con, now=self.now)
        topics.store(self.con, topics.clean(self.con, {"topics": [self.topic(refs)]}, refs, self.now))
        self.con.commit()
        before = self.con.total_changes
        topics.listing(self.con)
        topics.listing(self.con, self.ini)
        topics.by_initiative(self.con)
        topics.pack(self.con, now=self.now)
        self.assertFalse(topics.set_status(self.con, topics.listing(self.con)["topics"][0]["id"], "current"))   # unchanged
        self.assertEqual(self.con.total_changes, before)

    def test_a_new_run_is_asked_for_only_when_something_came_in(self):
        marks = topics._marks(self.con)
        topics._save_state({"run_at": iso(self.now - timedelta(hours=4)), "marks": marks})
        self.assertIsNone(topics.stale(self.con))
        self.meeting("NOVA kickoff", self.now - timedelta(hours=1), [])
        self.assertEqual(topics.stale(self.con), "new meetings")
        topics._save_state({"run_at": iso(self.now - timedelta(hours=1)), "marks": marks})
        self.assertIsNone(topics.stale(self.con))            # too soon after the last run
        self.con.execute("INSERT INTO meetings (title, starts_at) VALUES ('x', ?)", (iso(self.now),))
        # mail came in since, no meetings: a run only after MAIL_STALE_HOURS
        topics._save_state({"run_at": iso(self.now - timedelta(hours=4)), "marks": {**topics._marks(self.con), "mail": -1}})
        self.assertIsNone(topics.stale(self.con))
        topics._save_state({"run_at": iso(self.now - timedelta(hours=9)), "marks": {**topics._marks(self.con), "mail": -1}})
        self.assertEqual(topics.stale(self.con), "new mail")

    def test_run_with_a_model_stores_the_ranked_set(self):
        seen = []

        def model(prompt):
            seen.append(prompt)
            _, refs = topics.pack(self.con, now=self.now)
            return "Here you go:\n" + json.dumps({"topics": [self.topic(refs)]})
        self.assertEqual(topics.run(self.con, run_model=model)["topics"], 1)
        self.assertIn("Name the topics most on Sam's mind", seen[0])
        got = topics.listing(self.con)
        self.assertEqual((got["topics"][0]["initiative"], got["topics"][0]["raised_by"], got["topics"][0]["rank"]), ("GTM & partner enablement", "you", 1))
        self.assertIsNotNone(got["run_at"])


if __name__ == "__main__":
    unittest.main()
