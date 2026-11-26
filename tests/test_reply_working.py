"""The reply Sam is working on is kept per email (assist/reply_working.py): Use in reply from the chat and his edits survive
leaving the email; an empty text clears it; it is email-derived text, so it goes after RETENTION_DAYS.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, reply_working
from assist.retention import RETENTION_DAYS


class Working(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_kept_updated_and_cleared(self):
        reply_working.put(self.con, 5, "Hi Ellis,\n\nYes.\n\n-Sam", "replyall", "chat")
        w = reply_working.get(self.con, 5)
        self.assertEqual((w["body"], w["mode"], w["source"]), ("Hi Ellis,\n\nYes.\n\n-Sam", "replyall", "chat"))
        reply_working.put(self.con, 5, "Hi Ellis, yes from Friday.", None, "edit")   # an edit keeps the mode it had
        w = reply_working.get(self.con, 5)
        self.assertEqual((w["mode"], w["source"]), ("replyall", "edit"))
        reply_working.put(self.con, 5, "   ")
        self.assertIsNone(reply_working.get(self.con, 5))

    def test_gone_after_the_retention_period(self):
        reply_working.put(self.con, 6, "text")
        old = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.con.execute("UPDATE reply_working SET updated_at=?", (old,))
        self.assertIsNone(reply_working.get(self.con, 6))


if __name__ == "__main__":
    unittest.main()
