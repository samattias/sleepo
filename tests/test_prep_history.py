"""The meeting brief sees all recent communication with each person (assist/prep_history.py), in every channel and both
directions. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, prep_history


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class History(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        c = self.con
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook', 'outlook', 'o'), ('teams', 'teams', 't'), ('granola', 'granola', 'g')")
        c.execute("INSERT INTO people(id, name) VALUES (1, 'Rowan Lowell'), (2, 'Sam Doe')")
        c.execute("INSERT INTO people_aliases VALUES ('rowan.lowell@acme.example', 1), ('rowan lowell', 1)")
        n = 0

        def item(kind, ts, noise=0, src="outlook"):
            nonlocal n
            n += 1
            c.execute("INSERT INTO items(id, source_id, external_id, kind, ts, noise, pulled_at) VALUES (?,?,?,?,?,?,?)",
                      (n, src, f"x{n}", kind, ts, noise, ts))
            return n

        def mail(folder, frm, to, subject, body, days, noise=0):
            i = item("sent" if folder == "sentitems" else "mail", ago(days), noise)
            c.execute("INSERT INTO mail_messages(item_id, graph_id, folder, conversation_id, from_name, from_address, to_json, cc_json, subject, "
                      "received_at, sent_at, body_text, web_link, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (i, f"G{i}", folder, f"conv-{subject}", frm.split("@")[0], frm, json.dumps([{"address": a} for a in to]), "[]", subject,
                       ago(days), ago(days), body, f"https://outlook/x{i}", ago(0)))

        mail("inbox", "rowan.lowell@acme.example", ["sam.doe@acme.example"], "Roadmap", "Can you review the Q4 roadmap?", 3)
        mail("sentitems", "sam.doe@acme.example", ["rowan.lowell@acme.example"], "Roadmap", "Reviewed, comments inline.\nFrom: Rowan", 2)
        mail("inbox", "rowan.lowell@acme.example", ["sam.doe@acme.example"], "Newsletter", "noise", 1, noise=1)
        mail("inbox", "rowan.lowell@acme.example", ["sam.doe@acme.example"], "Old", "too old", 45)
        for author, body in (("Sam Doe", "Did the intake form go out?"), ("Rowan Lowell", "Yes, sent Tuesday")):
            i = item("chat", ago(1), src="teams")
            c.execute("INSERT INTO chat_messages(item_id, source_id, external_id, conversation_id, conversation_name, conversation_kind, author, sent_at, body_text) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (i, "teams", f"c{i}", "dm1", "DM Rowan Lowell", "dm", author, ago(1), body))
        i = item("note", ago(7), src="granola")
        c.execute("INSERT INTO meetings(id, note_item_id, title, starts_at, attendees, digest_md, status) VALUES (1, ?, 'Sam / Rowan 1:1', ?, ?, ?, 'analysed')",
                  (i, ago(7), json.dumps(["Sam Doe", "Rowan Lowell"]), "## Summary\nAgreed one intake process."))
        c.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_one_to_one_covers_every_channel_both_ways(self):
        rowan = self.con.execute("SELECT * FROM people WHERE id=1").fetchone()
        text = "\n".join(prep_history.history(self.con, [rowan], [], ago(-1)))
        self.assertIn("Sam / Rowan 1:1", text)                  # meeting
        self.assertIn("Can you review the Q4 roadmap?", text)   # their mail to Sam
        self.assertIn("Reviewed, comments inline.", text)       # Sam's reply ...
        self.assertNotIn("From: Rowan", text)                     # ... without the quoted history
        self.assertIn("Did the intake form go out?", text)      # Sam's own DM message
        self.assertIn("Yes, sent Tuesday", text)                # their DM reply
        self.assertNotIn("noise", text)                         # noise mail left out
        self.assertNotIn("too old", text)                       # outside the 30-day window


if __name__ == "__main__":
    unittest.main()
