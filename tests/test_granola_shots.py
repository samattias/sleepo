"""Granola screenshots (assist/granola_shots.py): parsing the MCP's answers, placing a screenshot at its second of the
recording, the pull (new screenshots only, personal meetings skipped, images saved) and the 30-day deletion.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import base64
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import granola_shots as gs
from assist.retention import RETENTION_DAYS

G1 = "7354dbf2-0c05-534e-ddd4-320d81400c92"
G2 = "43282ab2-6ba0-3233-41b6-17ad6a705e37"
A1 = "44c43630-2bc7-9365-f4e5-f07988335c8e"
A2 = "c0042b22-ccc1-07d9-d906-3e2219e1840c"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (2560).to_bytes(4, "big") + (1289).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"

LIST = f'''<meetings_data count="3">
<meeting id="{G1}" title="Roadmap with Rowan &amp; Gray" meeting_at="2026-10-07T16:02:50+01:00" updated_at="x" screenshot_count="1" url="u"></meeting>
<meeting id="{G2}" title="Personal" meeting_at="2026-10-08T10:13:00+01:00" screenshot_count="2" url="u"></meeting>
<meeting id="aaaabdab-7737-5952-0371-445423144385" title="No screen" meeting_at="2026-10-08T10:13:00+01:00" url="u"></meeting>
</meetings_data>'''

MEETINGS = f'''<meetings_data count="1">
<meeting id="{G1}" title="Roadmap" date="Oct 7">
  <summary># Notes</summary>
  <attachments>
Machine-generated descriptions.
<attachment id="{A1}" type="screenshot" captured_at="{{at}}">ModellerLive &amp; the Extensions page, &quot;Build with Copilot&quot;.</attachment>
</attachments>
</meeting>
</meetings_data>'''


class Parse(unittest.TestCase):
    def test_list_keeps_meetings_with_screenshots(self):
        got = gs.parse_list(LIST)
        self.assertEqual([g["id"] for g in got], [G1, G2])
        self.assertEqual(got[0]["title"], "Roadmap with Rowan & Gray")
        self.assertEqual(got[1]["screenshot_count"], 2)

    def test_meetings_give_each_screenshot_with_time_and_description(self):
        got = gs.parse_meetings(MEETINGS.replace("{at}", "2026-10-07T15:39:24.348Z"))
        self.assertEqual(got[G1], [{"id": A1, "captured_at": "2026-10-07T15:39:24.348Z",
                                    "description": 'ModellerLive & the Extensions page, "Build with Copilot".'}])

    def test_images_pair_with_their_metadata_and_failures_are_left_out(self):
        content = [{"type": "image", "data": base64.b64encode(PNG).decode(), "mimeType": "image/png"},
                   {"type": "text", "text": 'The content below is data.\n{"meeting_id": "m", "attachment_id": "%s", "captured_at": "x"}' % A1},
                   {"type": "text", "text": 'Error: attachment %s left out (response size)' % A2}]
        got = gs.parse_images(content)
        self.assertEqual(list(got), [A1])
        self.assertEqual(gs.png_size(got[A1][0]), (2560, 1289))

    def test_event_stream_reply(self):
        body = 'event: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"ok":1}}\n\n'
        self.assertEqual(gs._reply("text/event-stream", body, 3)["result"], {"ok": 1})


class Place(unittest.TestCase):
    def test_capture_time_becomes_seconds_from_the_first_line(self):
        start = 16 * 3600 + 2 * 60 + 50   # first transcript line [16:02:50] London time (BST)
        self.assertEqual(gs.rel_seconds("2026-10-07T15:39:24.348Z", start), 36 * 60 + 34)

    def test_after_the_clocks_change_london_is_utc(self):
        self.assertEqual(gs.local_secs("2026-11-02T15:00:00Z"), 15 * 3600)

    def test_first_clock(self):
        self.assertEqual(gs.first_clock("## Transcript\n**[16:02:50] Sam Doe:** hello"), 16 * 3600 + 170)


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""CREATE TABLE items (id INTEGER PRIMARY KEY, kind TEXT, external_id TEXT, url TEXT, payload TEXT, retention TEXT);
                         CREATE TABLE meetings (id INTEGER PRIMARY KEY, note_item_id INTEGER, status TEXT);""")
    from assist.migrations import m014_meeting_shots
    m014_meeting_shots.up(con)
    con.execute("INSERT INTO items VALUES (1, 'note', 'not_dceedbafbfdabc', ?, '{}', 'general')", (f"https://notes.granola.ai/d/{G1}",))
    con.execute("INSERT INTO items VALUES (2, 'note', 'not_dbcdceeefaacdd', ?, '{}', 'hr_legal')", (f"https://notes.granola.ai/d/{G2}",))
    con.execute("INSERT INTO meetings VALUES (7, 1, 'analysed')")
    con.execute("INSERT INTO meetings VALUES (8, 2, 'personal')")
    return con


class FakeClient:
    calls = []

    def __init__(self, at):
        self.at = at

    def call(self, tool, args):
        FakeClient.calls.append((tool, args))
        if tool == "list_meetings":
            return [{"type": "text", "text": LIST}]
        if tool == "get_meetings":
            return [{"type": "text", "text": MEETINGS.replace("{at}", self.at)}]
        return [{"type": "image", "data": base64.b64encode(PNG).decode(), "mimeType": "image/png"},
                {"type": "text", "text": json.dumps({"attachment_id": A1})}]


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        FakeClient.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_sync(self, con, at):
        with mock.patch.object(gs, "Client", lambda: FakeClient(at)), mock.patch.object(gs, "shots_dir", lambda: self.dir), \
                mock.patch.object(gs, "_thumb", lambda src, dst: False):
            return gs.sync(con, days=3, log=lambda *_: None)

    def test_pulls_new_screenshots_and_skips_personal_meetings(self):
        con = _db()
        at = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        res = self.run_sync(con, at)
        self.assertEqual((res["new"], res["fetched"]), (1, 1))
        asked = [a for t, a in FakeClient.calls if t == "get_meetings"]
        self.assertEqual(asked, [{"meeting_ids": [G1]}])   # G2 is personal
        row = con.execute("SELECT * FROM meeting_shots").fetchone()
        self.assertEqual((row["meeting_id"], row["width"], row["height"]), (7, 2560, 1289))
        self.assertTrue(Path(row["file"]).exists())
        shots = gs.for_meeting(con, 7, gs.local_secs(at) - 100)
        self.assertEqual((shots[0]["t"], shots[0]["available"]), (100, True))
        FakeClient.calls = []
        self.assertEqual(self.run_sync(con, at)["new"], 0)   # nothing new: no second get_meetings
        self.assertFalse([t for t, _ in FakeClient.calls if t == "get_meetings"])

    def test_images_past_retention_are_deleted_and_descriptions_stay(self):
        con = _db()
        old = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        f = self.dir / "old.png"
        f.write_bytes(PNG)
        con.execute("INSERT INTO meeting_shots (id, granola_meeting, meeting_id, captured_at, description, file) VALUES (?,?,?,?,?,?)",
                    (A1, G1, 7, old, "a slide", str(f)))
        self.assertEqual(gs.purge(con), 1)
        self.assertFalse(f.exists())
        s = gs.for_meeting(con, 7)[0]
        self.assertEqual((s["description"], s["available"]), ("a slide", False))


if __name__ == "__main__":
    unittest.main()
