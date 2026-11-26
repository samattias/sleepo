"""The Replies page's mail refresh and the formatted original read from Apple Mail (assist/api.py, assist/applemail.py).
Apple Mail and the CLI are mocked; the database is a temporary one. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from assist import api, applemail, db
from assist.routes import mail as mail_routes


class MailRefresh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.db"
        c = db.connect(self.path)
        db.migrate(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox', 'outlook', 'i'), ('outlook.sent', 'outlook', 's')")
        c.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (7, 'outlook.inbox', 'x7', 'mail', '2026-10-12T09:00:00Z', '2026-10-12T09:00:00Z')")
        c.execute("INSERT INTO mail_messages(item_id, graph_id, folder, internet_message_id, body_type, body_text, received_at, synced_at) "
                  "VALUES (7, 'am:a@b', 'inbox', '<a@b>', 'text', 'hello', '2026-10-12T09:00:00Z', '2026-10-12T09:00:00Z')")
        c.commit()
        c.close()
        self.patches = [mock.patch.object(m, "con", lambda: db.connect(self.path)) for m in (api, mail_routes)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _pull(self, src, n):
        c = db.connect(self.path)
        pid = db.start_pull(c, src, "assist mail-local", "2026-01-01", None, "Apple Mail")
        db.finish_pull(c, pid, available=n, pulled=n, noise=None, complete=1)
        c.commit()
        c.close()

    def test_refresh_reports_new_mail_and_runs_the_open_items_sync(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd[3:])
            if cmd[3] == "mail-local":
                self._pull("outlook.inbox", 2)
                self._pull("outlook.sent", 1)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(api.subprocess, "run", run), mock.patch.object(applemail, "mail_running", lambda: True):
            r = api.api_refresh_mail()
        body = __import__("json").loads(r.body)
        self.assertEqual(body["new"], {"inbox": 2, "sent": 1})
        self.assertEqual(calls, [["mail-local", "--quiet"], ["loops", "sync"], ["tasks", "sync"]])   # replies Sam sent close their items and their steps; --quiet: no write when nothing changed
        self.assertFalse(api.MAIL_LOCK.locked())

    def test_refresh_reports_mail_that_turned_read(self):
        c = db.connect(self.path)
        c.execute("UPDATE mail_messages SET is_read=0 WHERE item_id=7")
        c.commit()
        c.close()

        def run(cmd, **kw):
            if cmd[3] == "mail-local":   # Sam read it in Mail
                c = db.connect(self.path)
                c.execute("UPDATE mail_messages SET is_read=1 WHERE item_id=7")
                c.commit()
                c.close()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(api.subprocess, "run", run), mock.patch.object(applemail, "mail_running", lambda: True):
            body = __import__("json").loads(api.api_refresh_mail().body)
        self.assertEqual((body["read"], body["unread"]), (1, 0))

    def _unread(self, i, imid, received):
        c = db.connect(self.path)
        c.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (?, 'outlook.inbox', ?, 'mail', ?, ?)", (i, f"x{i}", received, received))
        c.execute("INSERT INTO mail_messages(item_id, graph_id, folder, internet_message_id, body_type, body_text, received_at, synced_at, is_read) "
                  "VALUES (?, ?, 'inbox', ?, 'text', 'hello', ?, ?, 0)", (i, f"am:{imid}", f"<{imid}>", received, received))
        c.commit()
        c.close()

    def _is_read(self):
        c = db.connect(self.path)
        try:
            return {r[0]: r[1] for r in c.execute("SELECT item_id, is_read FROM mail_messages WHERE item_id > 7")}
        finally:
            c.close()

    def test_mail_gone_from_mails_inbox_is_no_longer_unread(self):
        self._unread(8, "still@x", "2026-10-15T09:00:00Z")    # unread in Mail's Inbox
        self._unread(9, "deleted@x", "2026-10-14T09:00:00Z")  # deleted, archived or an answered invitation
        self._unread(10, "new@x", "2026-10-19T12:00:00Z")     # newer than anything Mail has synced
        c = db.connect(self.path)
        n = applemail.left_inbox(c, {"<still@x>"}, "2026-10-19T09:00:00Z", "2026-01-01T00:00:00Z", 400)
        c.commit()
        c.close()
        self.assertEqual(n, 1)
        self.assertEqual(self._is_read(), {8: 0, 9: 1, 10: 0})

    def test_a_near_empty_mail_index_changes_nothing(self):
        for i in range(8, 40):
            self._unread(i, f"m{i}@x", "2026-10-14T09:00:00Z")
        c = db.connect(self.path)
        self.assertIsNone(applemail.left_inbox(c, set(), "2026-10-19T09:00:00Z", "2026-01-01T00:00:00Z", 3))   # 32 gone of 3 listed
        self.assertIsNone(applemail.left_inbox(c, set(), None, "2026-01-01T00:00:00Z", 0))
        c.close()
        self.assertEqual(set(self._is_read().values()), {0})

    def test_no_full_disk_access_is_a_clear_error_and_releases_the_lock(self):
        with mock.patch.object(api.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "")):
            with self.assertRaises(HTTPException) as e:
                api.api_refresh_mail()
        self.assertEqual(e.exception.status_code, 503)
        self.assertFalse(api.MAIL_LOCK.locked())

    def test_inline_parts_are_images_only(self):
        for kind, ok in (("image/png", True), ("image/svg+xml", False), ("text/html", False)):
            with mock.patch.object(applemail, "inline_part", lambda imid, cid, k=kind: (b"x", k)):
                if ok:
                    self.assertEqual(mail_routes.api_mail_inline(7, "logo").media_type, kind)
                else:
                    with self.assertRaises(HTTPException):
                        mail_routes.api_mail_inline(7, "logo")

    def test_formatted_original_falls_back_to_the_stored_text(self):
        with mock.patch.object(applemail, "html_body", side_effect=applemail.NoAccess("no access")):
            self.assertEqual(mail_routes._rich("<a@b>"), {})
        with mock.patch.object(applemail, "html_body", lambda imid: "<p><b>hi</b></p>"):
            self.assertEqual(mail_routes._rich("<a@b>")["body_type"], "html")


if __name__ == "__main__":
    unittest.main()
