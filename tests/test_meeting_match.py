"""Recordings to calendar events (scripts/reconcile_calendar.py, the only matcher; the Meetings page shows its pairs).
A quick call just before a meeting is a call of its own, also before the meeting's own recording is in (26 Oct 2026: ten
minutes with Gray became the 16:00 UX review); a recording started early and still running in the meeting is that meeting;
a 1:1 started early is matched when the other person was heard; a note with no transcript keeps the start rule.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reconcile_calendar as rc  # noqa: E402


def t(hm, day="2026-10-26"):
    return f"{day}T{hm}:00.000Z"


def note(nid, start, end=None, heard=(), title=None):
    """A raw Granola note: started at start, transcript lines until end, spoken by the names in heard."""
    lines = [] if end is None else [{"start_time": t(start), "end_time": t(start), "speaker": {"name": h}} for h in heard] + \
        [{"start_time": t(end), "end_time": t(end), "speaker": {"source": "microphone"}}]
    return rc.note_of({"id": nid, "title": title or nid, "created_at": t(start), "transcript": lines})


def event(eid, start, end, people=("Gray.selby@acme.example",), subject=None, response=None):
    at = lambda hm: datetime.fromisoformat(f"2026-10-26T{hm}:00+00:00").astimezone(timezone.utc)
    return {"id": eid, "subject": subject or eid, "_s": at(start), "_e": at(end),
            "attendees": list(people) + ["Sam.doe@acme.example"] if people else [], "response": response}


ELT = event("elt", "15:00", "16:00", ("Milo.marsh@acme.example", "Ellis.ingram@acme.example"))
UX = event("ux", "16:00", "17:00", ("Lane.fairley@acme.example", "Rowan.lowell@acme.example", "gray.selby@acme.example"))


def matched(notes, events):
    return {nid: (e["id"], loose) for nid, (e, loose) in rc.match(notes, events).items()}


class MeetingMatch(unittest.TestCase):
    def test_a_quick_call_before_a_meeting_is_not_that_meeting(self):
        elt, gray = note("elt", "14:57", "15:26", ["Milo Marsh"]), note("gray", "15:41", "15:51", ["Gray Selby"])
        self.assertEqual(matched([elt, gray], [ELT, UX]), {"elt": ("elt", False)})   # the review's recording is not in yet
        ux = note("ux", "16:01", "17:00", ["Lane Fairley", "Gray Selby"])
        self.assertEqual(matched([elt, gray, ux], [ELT, UX]), {"elt": ("elt", False), "ux": ("ux", False)})

    def test_a_call_ending_just_before_does_not_take_the_meeting_from_its_recording(self):
        quick, ux = note("quick", "15:50", "15:58", ["Gray Selby"]), note("ux", "16:01", "16:50", ["Lane Fairley"])
        self.assertEqual(matched([quick, ux], [UX]), {"ux": ("ux", False)})

    def test_a_recording_started_early_and_running_into_the_meeting_is_that_meeting(self):
        self.assertEqual(matched([note("ux", "15:52", "16:40")], [UX]), {"ux": ("ux", False)})
        self.assertEqual(matched([note("short", "15:58", "16:05")], [UX]), {"short": ("ux", False)})   # most of it inside

    def test_a_one_to_one_started_early_when_the_other_person_was_heard(self):
        milo = event("milo", "14:00", "15:00", ("Milo.marsh@acme.example",), "1:1 Sam & Milo")
        self.assertEqual(matched([note("n", "13:34", "14:03", ["Milo Marsh"])], [milo]), {"n": ("milo", True)})
        self.assertEqual(matched([note("n", "13:34", "14:03", ["Gray Selby"])], [milo]), {})
        self.assertEqual(matched([note("n", "15:41", "15:51", ["Gray Selby"])], [UX]), {})   # Lane and Rowan not heard

    def test_a_note_with_no_transcript_keeps_the_start_rule(self):
        self.assertEqual(matched([note("typed", "15:50")], [UX]), {"typed": ("ux", False)})

    def test_a_short_recording_at_the_end_of_one_meeting_stays_with_it(self):
        # 13 Jul 2026: nine minutes at the end of the ELT took the next meeting's slot, and that meeting's recording the ELT
        elt = event("elt", "14:00", "15:00", ("Milo.marsh@acme.example",))
        pp = event("pp", "15:00", "15:45", ("Quinn.irving@acme.example",))
        got = matched([note("elt", "14:48", "14:57"), note("pp", "14:59", "15:52")], [elt, pp])
        self.assertEqual(got, {"elt": ("elt", False), "pp": ("pp", False)})

    def test_two_meetings_at_once_go_by_who_was_heard_and_the_title(self):
        # 27 Oct 2026: the 1:1 with Rowan and the CFT meeting (Rowan among eight) both at 15:00; only Rowan was heard
        cft = event("cft", "15:00", "15:45", ("cove.thorne@acme.example", "Zane.keller@acme.example", "isla.jensen@acme.example",
                                             "Rowan.lowell@acme.example", "Finley.kirby@acme.example", "gray.selby@acme.example"), response="none")
        rowan = event("rowan", "15:00", "15:45", ("Rowan.lowell@acme.example",), response="organizer")
        n = note("n", "15:01", "15:44", heard=("Rowan Lowell",), title="Q4 roadmap and NOVA design partnership with Rowan")
        self.assertEqual(matched([n], [cft, rowan]), {"n": ("rowan", False)})
        self.assertEqual(matched([note("t", "15:01", "15:44", title="Roadmap with Rowan")], [cft, rowan]), {"t": ("rowan", False)})
        self.assertEqual(matched([note("r", "15:01", "15:44")], [cft, rowan]), {"r": ("rowan", False)})   # no evidence: the one he organised
        everyone = note("e", "15:01", "15:44", heard=("Cove Thorne", "Zane Keller", "Isla Jensen", "Finley Kirby"))
        self.assertEqual(matched([everyone], [rowan, cft]), {"e": ("cft", False)})

    def test_a_journey_is_not_the_meeting_it_leads_to(self):
        # 4 Nov 2026, Lisbon: recorded in person from 07:59 to 09:04 for the 08:15 contoso meeting; the itinerary's "Move to
        # Contoso" at 08:00 carries everyone on the trip and took it. No speaker names in a room recording.
        trip = ("traveller.one@acme.example", "traveller.two@acme.example")
        travel = event("travel", "07:00", "08:00", (), "Travel to contoso office")
        move = event("move", "08:00", "08:45", trip, "Move to Contoso")
        visit = event("visit", "08:15", "09:00", ("host.one@contoso.example", "host.two@contoso.example"), "Meeting:contoso")
        self.assertEqual(matched([note("n", "07:59", "09:04")], [travel, move, visit]), {"n": ("visit", True)})
        self.assertEqual(matched([note("n", "07:59", "08:40")], [travel, move]), {"n": ("move", False)})   # no meeting: the journey keeps it
        own = note("own", "08:16", "08:58")   # the meeting's own recording keeps it; the early one stays on the journey
        self.assertEqual(matched([note("n", "07:59", "08:40"), own], [travel, move, visit]), {"own": ("visit", False), "n": ("move", False)})


if __name__ == "__main__":
    unittest.main()
