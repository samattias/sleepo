"""Fixes from the 13 Oct 2026 code review: what pull runs may do (assist/api.py), previews and file routes, pulls that do not
say they are complete, bundles loaded once, actions that come back, Sam's chat answers, the calendar merge.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from assist import api, cli, db, importer, ingest, loops, todo
from assist.routes import knowledge


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class PullPermissions(unittest.TestCase):
    def test_no_wildcard_in_front_of_fixed_text(self):
        # "*" matches spaces too: "rm -f *x" allows "rm -f <anything> x", "python3 scripts/*" allowed "scripts/../evil.py"
        for rule in api.ALLOWED:
            if rule.startswith("Bash(") and "*" in rule:
                self.assertTrue(rule.endswith(" *)") and rule.count("*") == 1, rule)
        self.assertFalse(any(r.startswith("Bash(python3 scripts/") and "*" in r for r in api.ALLOWED))

    def test_writes_are_scoped_and_the_mode_refuses_the_rest(self):
        self.assertNotIn("Write", api.ALLOWED)
        self.assertNotIn("Edit", api.ALLOWED)
        self.assertIn("Edit(inbox/**)", api.ALLOWED)
        self.assertEqual(api.PULL_MODE, "default")   # acceptEdits would accept any edit in the folder
        self.assertIn("Edit(.git/**)", api.PROTECTED)
        self.assertEqual(api.PULL_SETTINGS, ["--setting-sources", "user,project"])   # not settings.local.json ("pnpm build *")

    def test_prompts_merge_the_calendar_through_the_cli(self):
        self.assertIn("assist.cli calendar-merge", api.PULL_PROMPTS["chat"])
        self.assertIn("assist.cli calendar-merge", api.retry_prompt(["calendar"]))
        self.assertIn("only under inbox/", api.retry_prompt(["teams"]))

    def test_retry_touches_only_the_missing_sources(self):
        # 16 Oct 2026: a Slack-only retry also pulled Teams and the calendar, timed out, and its partial rows hid the good pulls
        p = api.retry_prompt(["slack"], {"slack": {"newest": "2026-10-15T20:01:00Z"}})
        self.assertNotIn("calendar-merge", p)
        self.assertIn("2026-10-15T20:01:00Z", p)
        self.assertIn("ONLY these sources", p)
        self.assertIn("other Slack channels are background only", api.PULL_PROMPTS["chat-nocal"])


class FileRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Granola Export").mkdir()
        (self.root / "Granola Export" / "note.md").write_text("ok")
        (self.root / "Granola Export-old").mkdir()
        (self.root / "Granola Export-old" / "secret.md").write_text("no")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_sibling_folder_with_the_same_prefix_is_not_inside(self):
        with mock.patch.object(api, "ROOT", self.root):
            self.assertTrue(api.granola_file("note.md").path.endswith("note.md"))
            with self.assertRaises(HTTPException):
                api.granola_file("../Granola Export-old/secret.md")

    def test_an_svg_preview_is_sandboxed_and_a_pdf_is_not(self):
        svg, pdf = self.root / "a.svg", self.root / "a.pdf"
        svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
        pdf.write_bytes(b"%PDF-1.4")
        mode = {"lf-1": "image", "lf-2": "pdf"}
        with mock.patch.object(knowledge, "con", lambda: sqlite3.connect(":memory:")), \
                mock.patch("assist.previews.local_path", lambda c, d: svg if d == "lf-1" else pdf), \
                mock.patch("assist.previews.mode", lambda c, d: mode[d]):
            self.assertIn("sandbox", knowledge.api_preview_file("lf-1").headers["content-security-policy"])
            self.assertNotIn("sandbox", knowledge.api_preview_file("lf-2").headers["content-security-policy"])


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "t.db"
        self.con = db.connect(self.path)
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('slack', 'slack', 's')")
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_a_pull_is_complete_only_when_the_bundle_says_so(self):
        ingest.ingest_bundle(self.con, {"agent": "t", "pulls": [{"source_id": "slack", "pulled": 3}, {"source_id": "slack", "complete": True}]})
        self.assertEqual([r[0] for r in self.con.execute("SELECT complete FROM pulls ORDER BY id")], [0, 1])

    def test_a_lock_after_the_commit_does_not_load_the_bundle_twice(self):
        queue = self.dir / "inbox" / "queue"
        queue.mkdir(parents=True)
        f = queue / "pull-chat.json"
        f.write_text(json.dumps({"agent": "t", "pulls": [{"source_id": "slack", "complete": True}]}))
        calls = []

        def reindex(con):   # the search rebuild meets a parallel pull's write lock once, then succeeds
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.OperationalError("database is locked")

        with mock.patch.dict(os.environ, {"ASSIST_DB": str(self.path)}), mock.patch.object(db, "ASSIST", self.dir), \
                mock.patch.object(ingest, "reindex", reindex), mock.patch("time.sleep"), mock.patch("builtins.print"):
            cli.main(["ingest", str(f)])
        c = db.connect(self.path)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM pulls").fetchone()[0], 1)
        c.close()
        self.assertEqual(len(calls), 2)   # retried the rebuild, once for the whole run
        self.assertFalse(f.exists())
        self.assertTrue((queue / "done" / "pull-chat.json").exists())

    def test_a_bundle_back_in_the_queue_is_not_loaded_again(self):
        # 16 Nov 2026: October bundles came back into the queue; loading them again set Slack to "partial" (Capped)
        queue = self.dir / "inbox" / "queue"
        queue.mkdir(parents=True)
        f = queue / "pull-retry-2026-10-12.json"
        body = json.dumps({"agent": "t", "pulls": [{"source_id": "slack", "complete": True}],
                           "source_health": [{"source_id": "slack", "health": "partial", "last_pull_at": "2026-10-12T06:55:00Z"}]})
        f.write_text(body)
        os.utime(f, (1760000000, 1760000000))   # written in October
        with mock.patch.object(db, "ASSIST", self.dir), mock.patch.object(ingest, "reindex", lambda con: None):
            ingest.ingest_file(self.con, f)
            self.con.execute("UPDATE sources SET health='ok', last_pull_at='2026-11-16T15:47:50Z' WHERE id='slack'")
            (queue / "done" / f.name).rename(f)   # it reappears, unchanged
            msg = ingest.ingest_file(self.con, f)
        self.assertIn("already loaded", msg)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM pulls").fetchone()[0], 1)
        self.assertEqual(tuple(self.con.execute("SELECT health, last_pull_at FROM sources WHERE id='slack'").fetchone()),
                         ("ok", "2026-11-16T15:47:50Z"))
        self.assertFalse(f.exists())
        f.write_text(body)   # rewritten since: a new pull, loaded
        with mock.patch.object(db, "ASSIST", self.dir), mock.patch.object(ingest, "reindex", lambda con: None):
            self.assertNotIn("already loaded", ingest.ingest_file(self.con, f))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM pulls").fetchone()[0], 2)
        # an older last_pull_at in source_health never moves the source back in time; a newer one does
        now = self.con.execute("SELECT last_pull_at FROM sources WHERE id='slack'").fetchone()[0]
        ingest.ingest_bundle(self.con, {"agent": "t", "source_health": [{"source_id": "slack", "last_pull_at": "2026-10-06T11:06:03Z"}]})
        self.assertEqual(self.con.execute("SELECT last_pull_at FROM sources WHERE id='slack'").fetchone()[0], now)
        ingest.ingest_bundle(self.con, {"agent": "t", "source_health": [{"source_id": "slack", "last_pull_at": "2099-01-01T00:00:00Z"}]})
        self.assertEqual(self.con.execute("SELECT last_pull_at FROM sources WHERE id='slack'").fetchone()[0], "2099-01-01T00:00:00Z")


class Actions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def status(self, title):
        return self.con.execute("SELECT status FROM todo WHERE id=?", (db.fingerprint(title),)).fetchone()[0]

    def test_a_done_title_comes_back_after_a_week_but_not_before(self):
        title = "Prep for the weekly strategy call with Milo"
        todo.store(self.con, [{"title": title, "actions": []}], {})
        todo.set_status(self.con, db.fingerprint(title), "done")
        todo.store(self.con, [{"title": title, "actions": []}], {})
        self.assertEqual(self.status(title), "done")    # tomorrow's list: still done
        self.con.execute("UPDATE todo SET updated_at=? WHERE id=?", (ago(8), db.fingerprint(title)))
        todo.store(self.con, [{"title": title, "actions": []}], {})
        self.assertEqual(self.status(title), "open")    # next week's call: a new action


class ChatAnswers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('teams', 'teams', 't')")
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def chat(self, author, text, hours):
        self.n += 1
        at = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, pulled_at) VALUES (?,?,?,?,?,?)", (self.n, "teams", f"c{self.n}", "chat", at, at))
        self.con.execute("INSERT INTO chat_messages(item_id, source_id, external_id, conversation_id, conversation_name, conversation_kind, author, sent_at, body_text) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (self.n, "teams", f"c{self.n}", "g1", "Launch", "group", author, at, text))
        return self.n

    def loop_status(self, ask):
        self.con.execute("INSERT INTO loops (kind, title, status, fact_type, fact_id, created_at) VALUES ('reply', 'Answer Rowan', 'open', 'chat', ?, ?)", (ask, ago(0)))
        loops.sync(self.con, log=lambda *_: None)
        return self.con.execute("SELECT status FROM loops WHERE fact_id=?", (ask,)).fetchone()[0]

    def test_another_sam_does_not_answer_for_sam(self):
        ask = self.chat("Rowan Lowell", "Sam, can you confirm the launch date?", 5)
        self.chat("Samir Haddad", "Thanks, all fine on our side", 4)
        self.chat("Rowan Lowell", "Ok, moving on", 3)   # the conversation moved on, so the open item is no longer the last word
        self.assertEqual(self.loop_status(ask), "open")

    def test_sam_answering_closes_it(self):
        ask = self.chat("Rowan Lowell", "Sam, can you confirm the launch date?", 5)
        self.chat("Sam Doe", "Yes, 5 Nov", 4)
        self.assertEqual(self.loop_status(ask), "done")


class CalendarMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.events = self.dir / "events.json"
        self.events.write_text(json.dumps({"windows": [], "events": [
            {"id": "a", "start": "2026-10-14T13:00:00.0000000", "start_tz": "UTC", "subject": "Old", "join_url": "https://teams/x"},
            {"id": "b", "start": "2026-10-01T09:00:00.0000000", "start_tz": "UTC", "subject": "Kept"}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_replace_by_id_keep_older_and_the_join_link(self):
        pull = self.dir / "pull.json"
        pull.write_text(json.dumps({"window": {"afterDateTime": "2026-10-12T00:00:00Z"}, "events": [
            {"id": "a", "start": "2026-10-14T14:00:00.0000000", "subject": "Moved", "summary": "x" * 300},
            {"id": "c", "start": "2026-10-15T10:00:00.0000000", "subject": "New"}]}))
        self.assertEqual(importer.merge_calendar_pull(pull, self.events), (1, 1))
        d = json.loads(self.events.read_text())
        by = {e["id"]: e for e in d["events"]}
        self.assertEqual([e["id"] for e in d["events"]], ["b", "a", "c"])   # by start
        self.assertEqual((by["a"]["subject"], by["a"]["join_url"], by["a"]["start_tz"], len(by["a"]["summary"])), ("Moved", "https://teams/x", "UTC", 200))
        self.assertEqual(d["windows"], [{"afterDateTime": "2026-10-12T00:00:00Z"}])

    def test_a_malformed_pull_changes_nothing(self):
        before = self.events.read_text()
        pull = self.dir / "pull.json"
        pull.write_text(json.dumps({"events": [{"subject": "no id"}]}))
        with self.assertRaises(ValueError):
            importer.merge_calendar_pull(pull, self.events)
        self.assertEqual(self.events.read_text(), before)


if __name__ == "__main__":
    unittest.main()
