"""A recording resumed in the wrong Granola note joins the meeting it continues (assist/granola_stitch.py).
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import unittest

from assist.granola_stitch import stitch


def seg(start, end, text="x"):
    return {"start_time": start, "end_time": end, "text": text, "speaker": {"attribution": "me"}}


def note(nid, created, segs, summary=""):
    return {"id": nid, "title": nid, "created_at": created, "transcript": segs, "summary_markdown": summary, "web_url": f"https://g/{nid}"}


class Stitch(unittest.TestCase):
    def test_resumed_empty_note_joins_the_meeting_it_continues(self):
        today = note("today", "2026-10-12T13:58:47.000Z", [seg("2026-10-12T13:58:50Z", "2026-10-12T14:29:03Z")], "first half")
        friday = note("friday", "2026-10-09T11:46:18.000Z", [seg("2026-10-12T14:29:04Z", "2026-10-12T14:57:23Z")], "second half")
        ms, joins = stitch([today, friday])
        self.assertEqual(joins, [("friday", "today")])
        self.assertEqual([m["id"] for m in ms], ["today"])
        self.assertEqual(len(ms[0]["transcript"]), 2)
        self.assertIn("second half", ms[0]["summary_markdown"])
        self.assertEqual(ms[0]["_continued_by"], ["friday"])
        self.assertEqual(len(today["transcript"]), 1)   # inputs untouched

    def test_resumed_note_with_old_content_is_split(self):
        old = note("old", "2026-10-09T11:00:00.000Z", [seg("2026-10-09T11:00:05Z", "2026-10-09T11:30:00Z"), seg("2026-10-12T14:29:04Z", "2026-10-12T14:57:00Z")])
        today = note("today", "2026-10-12T14:00:00.000Z", [seg("2026-10-12T14:00:05Z", "2026-10-12T14:29:00Z")])
        ms, joins = stitch([old, today])
        by = {m["id"]: m for m in ms}
        self.assertEqual(joins, [("old~2", "today")])
        self.assertEqual(len(by["old"]["transcript"]), 1)
        self.assertEqual(len(by["today"]["transcript"]), 2)

    def test_back_to_back_meetings_are_not_joined_and_lone_resumes_are_redated(self):
        a = note("a", "2026-10-12T13:00:00.000Z", [seg("2026-10-12T13:00:05Z", "2026-10-12T13:29:58Z")])
        b = note("b", "2026-10-12T13:30:00.000Z", [seg("2026-10-12T13:30:02Z", "2026-10-12T14:00:00Z")])
        lone = note("lone", "2026-10-01T09:00:00.000Z", [seg("2026-10-12T16:00:00Z", "2026-10-12T16:30:00Z")])
        ms, joins = stitch([a, b, lone])
        self.assertEqual(joins, [])
        self.assertEqual({m["id"]: m["created_at"][:16] for m in ms}["lone"], "2026-10-12T16:00")


if __name__ == "__main__":
    unittest.main()
