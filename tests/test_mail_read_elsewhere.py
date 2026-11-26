"""Mail that Apple Mail has read, or moved out of its Inbox (Outlook moves a meeting request to Deleted Items once the
calendar has it), stops counting as unread in SleePO (assist/applemail.py read_elsewhere; Sam, 26 Oct 2026).
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import applemail, db


def ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReadElsewhere(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.con = db.connect(d / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox', 'outlook', 'i')")
        for iid, imid, read in ((1, "<inv@x>", 0), (2, "<kept@x>", 0), (3, "<readinmail@x>", 0), (4, "<unknown@x>", 0)):
            self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (?, 'outlook.inbox', ?, 'mail', ?, ?)", (iid, imid, ago(2), ago(1)))
            self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, internet_message_id, subject, received_at, is_read, synced_at) "
                             "VALUES (?, ?, 'inbox', ?, 's', ?, ?, ?)", (iid, f"am:{imid}", imid, ago(2), read, ago(1)))
        self.con.commit()
        self.ix = d / "Envelope Index"
        ix = sqlite3.connect(self.ix)
        ix.executescript("""CREATE TABLE mailboxes (ROWID INTEGER PRIMARY KEY, url TEXT);
            CREATE TABLE message_global_data (ROWID INTEGER PRIMARY KEY, message_id_header TEXT);
            CREATE TABLE messages (ROWID INTEGER PRIMARY KEY, mailbox INTEGER, global_message_id INTEGER, read INTEGER, deleted INTEGER);
            INSERT INTO mailboxes VALUES (1, 'ews://x/Inbox'), (2, 'ews://x/Deleted%20Items');
            INSERT INTO message_global_data VALUES (1, '<inv@x>'), (2, '<kept@x>'), (3, '<readinmail@x>');
            INSERT INTO messages VALUES (1, 2, 1, 1, 0), (2, 1, 2, 0, 0), (3, 1, 3, 1, 0);""")
        ix.commit()
        ix.close()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_moved_or_read_in_mail_is_read_here_and_the_rest_is_left(self):
        with mock.patch.object(applemail, "index_path", lambda: self.ix):
            self.assertEqual(applemail.read_elsewhere(self.con), 2)
        st = {r[0]: r[1] for r in self.con.execute("SELECT item_id, is_read FROM mail_messages")}
        self.assertEqual(st, {1: 1, 2: 0, 3: 1, 4: 0})   # the invite in Deleted Items and the one read in Mail; unread and unknown stay



class QuietCheck(unittest.TestCase):
    """The Inbox's Refresh mail (every 2 minutes while it is on screen) writes nothing when nothing changed: every database
    write reloads every open tab (assist-c3, 26 Oct 2026). A pull is still recorded once an hour, and always without quiet."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.con = db.connect(d / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox', 'outlook', 'i'), ('outlook.sent', 'outlook', 's')")
        self.con.commit()
        root = d / "V10"
        (root / "MailData").mkdir(parents=True)
        self.ix = root / "MailData" / "Envelope Index"
        ix = sqlite3.connect(self.ix)
        ix.executescript("""CREATE TABLE mailboxes (ROWID INTEGER PRIMARY KEY, url TEXT);
            CREATE TABLE subjects (ROWID INTEGER PRIMARY KEY, subject TEXT);
            CREATE TABLE addresses (ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
            CREATE TABLE recipients (ROWID INTEGER PRIMARY KEY, message INTEGER, type INTEGER, address INTEGER, position INTEGER);
            CREATE TABLE message_global_data (ROWID INTEGER PRIMARY KEY, message_id_header TEXT);
            CREATE TABLE messages (ROWID INTEGER PRIMARY KEY, mailbox INTEGER, subject INTEGER, subject_prefix TEXT, sender INTEGER, date_sent INTEGER,
                                   date_received INTEGER, read INTEGER, flagged INTEGER, deleted INTEGER, global_message_id INTEGER, conversation_id INTEGER);
            INSERT INTO mailboxes VALUES (1, 'ews://x/Inbox'), (2, 'ews://x/Sent%20Items');""")
        ix.commit()
        ix.close()
        self.patches = [mock.patch.object(applemail, "index_path", lambda: str(self.ix)), mock.patch.object(applemail, "mail_running", lambda: False),
                        mock.patch.object(applemail, "_checked_path", lambda: d / "jobs" / "mail_checked")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.con.close()
        self.tmp.cleanup()

    def pulls(self):
        return self.con.execute("SELECT COUNT(*) FROM pulls WHERE agent='assist mail-local'").fetchone()[0]

    def test_nothing_new_writes_nothing_but_a_pull_is_kept_hourly(self):
        log = lambda *_: None
        applemail.sync(self.con, quiet=True, log=log)          # no pull yet: recorded
        self.assertEqual(self.pulls(), 2)
        r = applemail.sync(self.con, quiet=True, log=log)      # a pull a moment ago, nothing new: nothing written
        self.assertTrue(r.get("quiet"))
        self.assertEqual(self.pulls(), 2)
        self.assertIsNotNone(applemail.checked())
        applemail.sync(self.con, log=log)                      # the quick sync and the full refresh always record theirs
        self.assertEqual(self.pulls(), 4)
        self.con.execute("UPDATE pulls SET finished_at=?", (ago(2),))
        self.con.commit()
        applemail.sync(self.con, quiet=True, log=log)          # the last pull is over an hour old: recorded again
        self.assertEqual(self.pulls(), 6)


if __name__ == "__main__":
    unittest.main()
