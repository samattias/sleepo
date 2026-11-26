"""Live call (assist/live_call.py): the transcript's audio sources become Sam / Others, a meeting finds the note started
nearest its start, the transcript is read from Granola at most once per MIN_GAP, the state writes nothing to the database,
and the question goes to the model with the transcript marked as data.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import db, live_call as lc

LIST = ('<meetings_data><meeting id="n1" title="ELT" meeting_at="2026-10-26T14:57:49.499+00:00" url="https://notes.granola.ai/d/n1">'
        '</meeting><meeting id="n2" title="Eden" meeting_at="2026-10-26T14:00:08.579+00:00" url="u2"></meeting></meetings_data>')
TRANSCRIPT = json.dumps({"truncated": False, "transcript": "Microphone: Can we do Thursday?\n\nSystem audio: Thursday works. I'll send the deck."})


class LiveCall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        lc._notes.update(at=0.0, rows=[])
        lc._seen.clear()
        self.calls = []

        def fake(tool, args):
            self.calls.append(tool)
            return LIST if tool == "list_meetings" else TRANSCRIPT
        self.p = mock.patch.object(lc, "_call", side_effect=fake)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.con.close()
        self.tmp.cleanup()

    def test_sources_become_sam_and_others(self):
        t = lc.parse_turns("Microphone: hi.\n\nSystem audio: Hello.\ncontinued\n\nMicrophone: ok")
        self.assertEqual([x["who"] for x in t], ["Sam", "Others", "Sam"])
        self.assertEqual(t[1]["text"], "Hello.\ncontinued")
        t = lc.parse_turns("Microphone: Hi Eden.\n\nSystem audio (Devon Collins): Good\n\nSystem audio (Devon Collins): afternoon.\n\nMicrophone (Sam Doe): Hi.")
        self.assertEqual([(x["who"], x["text"]) for x in t], [("Sam", "Hi Eden."), ("Devon Collins", "Good afternoon."), ("Sam", "Hi.")])

    def test_a_meeting_finds_the_note_started_nearest_it(self):
        notes = lc.parse_notes(LIST)
        st = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(lc.pick(notes, st, st + timedelta(minutes=30))["id"], "n1")
        self.assertIsNone(lc.pick(notes, st + timedelta(hours=3), st + timedelta(hours=4)))
        self.assertEqual(lc.pick(notes, now=st)["id"], "n1")   # no meeting: the newest of the last 3 hours

    def test_state_reads_granola_once_per_gap_and_writes_nothing(self):
        before = self.con.total_changes
        s = lc.state(self.con, note_id="n1")
        lc.state(self.con, note_id="n1")
        self.assertEqual([t["who"] for t in s["turns"]], ["Sam", "Others"])
        self.assertEqual(self.calls.count("get_meeting_transcript"), 1)
        self.assertEqual(self.calls.count("list_meetings"), 1)
        self.assertEqual(self.con.total_changes, before)

    def test_not_signed_in_is_said_plainly(self):
        from assist import granola_shots as g
        with mock.patch.object(lc, "_call", side_effect=g.NotSignedIn()):
            s = lc.state(self.con)
        self.assertFalse(s["signed_in"])
        self.assertIn("granola-login", s["error"])

    def test_the_question_carries_the_transcript_as_data(self):
        p = lc.prompt(self.con, "What did they agree to send?", "n1", history=[{"q": "When?", "a": "Thursday."}])
        self.assertIn("What did they agree to send?", p)
        self.assertIn("<transcript>\nSam: Can we do Thursday?\n\nOthers: Thursday works.", p)
        self.assertIn("Sam asked: When?", p)
        with self.assertRaises(ValueError):
            lc.start_job(self.con, "  ", "n1")

    def test_recording_needs_growth_after_the_first_look_and_finds_its_meeting(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        notes = f'<meeting id="n9" title="Call" meeting_at="{(now - timedelta(minutes=25)).isoformat()}" url="u"></meeting>'
        texts = iter(["Microphone: Hi.", "Microphone: Hi.\n\nSystem audio: Hello."])
        ev = {"id": "E1", "subject": "Sync with Gray", "start": (now - timedelta(minutes=27)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "end": (now + timedelta(minutes=23)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('calendar','outlook','Calendar')")
        self.con.execute("INSERT INTO items (kind, source_id, external_id, ts, subject, payload, pulled_at) VALUES ('event','calendar','E1',?,?,?,?)",
                         (ev["start"], ev["subject"], json.dumps(ev), ev["start"]))
        self.con.commit()
        fake = lambda tool, args: notes if tool == "list_meetings" else json.dumps({"transcript": next(texts)})
        with mock.patch.object(lc, "_call", side_effect=fake), mock.patch.object(lc, "granola_running", return_value=True), \
                mock.patch.object(lc, "MIN_GAP", 0):
            self.assertIsNone(lc.recording(self.con))          # first look: the baseline
            r = lc.recording(self.con)                          # it grew: a call is on
        self.assertEqual((r["note"]["id"], r["event"]), ("n9", "E1"))
        with mock.patch.object(lc, "granola_running", return_value=False):
            self.assertIsNone(lc.recording(self.con))

    def test_a_note_just_started_with_words_is_live_on_the_first_look(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        notes = f'<meeting id="n8" title="New note" meeting_at="{(now - timedelta(minutes=2)).isoformat()}" url="u"></meeting>'
        fake = lambda tool, args: notes if tool == "list_meetings" else json.dumps({"transcript": "Microphone: Hi."})
        with mock.patch.object(lc, "_call", side_effect=fake), mock.patch.object(lc, "granola_running", return_value=True):
            self.assertEqual(lc.recording(self.con)["note"]["id"], "n8")

    def test_a_deleted_note_is_an_error_not_a_transcript(self):
        with mock.patch.object(lc, "_call", side_effect=lambda tool, args: LIST if tool == "list_meetings" else "Meeting not found"):
            s = lc.state(self.con, note_id="n1")
        self.assertEqual(s["turns"], [])
        self.assertIn("Meeting not found", s["error"])
