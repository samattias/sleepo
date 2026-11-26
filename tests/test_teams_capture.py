"""The Teams pull built in code from the connector's results (assist/teams_capture.py; Sam, 17 Nov 2026: "make the Teams and
Slack synchronization much faster"). The model only calls the tools; the hook keeps each result; this module makes the
records. Temp database and capture folder; nothing runs Claude."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from assist import chatsync, db, profile, teams_capture

ME = "ann.lee@example.com"


def text(objs, more=None):
    """A connector result as the hook receives it: MCP text blocks holding objects one after another."""
    t = "".join(json.dumps(o) for o in objs) + (json.dumps({"moreResults": True, "nextOffset": more}) if more is not None else "")
    return [{"type": "text", "text": t}]


def search_hit(chat, mid, who, summary, at, channel=None):
    uri = (f"teams:///teams/team-1/channels/{chat}/messages/{mid}" if channel else f"teams:///chats/{chat}/messages/{mid}")
    o = {"uri": uri, "id": mid, "chatId": chat, "summary": summary, "createdDateTime": at, "from": {"displayName": who, "email": ""},
         "webUrl": f"https://teams.microsoft.com/l/message/{chat}/{mid}"}
    if channel:
        o["channelUri"] = f"teams:///teams/team-1/channels/{chat}/messages"
    return o


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('teams', 'teams', 'Teams')")
        profile.use({**profile.DEFAULTS, "full_name": "Ann Noel", "emails": [ME], "timezone": "Europe/London"})
        self.cap = Path(self.tmp.name) / "cap"
        self.cap.mkdir()
        self.n = 0

    def tearDown(self):
        profile.use(None)
        self.con.close()
        self.tmp.cleanup()

    def call(self, tool, inp, response):
        self.n += 1
        (self.cap / f"{self.n:04d}.json").write_text(json.dumps({"tool": tool, "input": inp, "response": response}))

    def test_messages_built_from_the_raw_results(self):
        after = {"query": "*", "afterDateTime": "2026-11-17T07:30:00Z"}
        long = "<p>Dear Team. I need a clear answer on <a href=\"https://x.sharepoint.com/deck.pptx\">the deck</a>.</p><p>Thanks</p>"
        self.call("chat_message_search", {**after, "offset": 0}, text([
            search_hit("19:g1@example.org", "101", "Milo Marsh", "Dear Team. I need a clear…", "2026-11-17T08:17:00.540Z"),
            search_hit("19:g1@example.org", "102", "Ann Noel", "On it", "2026-11-17T08:20:00.000Z"),
        ], more=2))
        self.call("chat_message_search", {**after, "offset": 2}, text([
            search_hit("19:c1@example.org", "201", "Slack Bridge", "[slack] <Gray Selby> shipped", "2026-11-17T08:00:00Z", channel=True),
            search_hit("19:c1@example.org", "202", "Slack Bridge", "[slack] <Jira> DEV-1 created", "2026-11-17T08:01:00Z", channel=True),
            search_hit("19:a_b@example.org", "301", "Ann Noel", "hi Gray", "2026-11-17T08:05:00Z"),
        ]))   # no nextOffset: the end
        self.call("read_resource", {"uri": "teams:///chats/19%3Ag1%40thread.v2/messages/101"}, text([
            {"id": "101", "messageType": "message", "chatId": "19:g1@example.org", "body": {"contentType": "html", "content": long},
             "from": {"displayName": "Milo Marsh"}, "createdDateTime": "2026-11-17T08:17:00.540Z", "webUrl": "https://t/101",
             "replyToId": None, "attachments": [
                 {"contentType": "reference", "contentUrl": "https://x.sharepoint.com/deck.pptx", "name": "deck.pptx"},
                 {"contentType": "messageReference", "contentUrl": None, "name": None}]}]))
        self.call("teams_list_chats", {"limit": 25}, text([
            {"id": "19:g1@example.org", "chatType": "group", "topic": None, "members": [
                {"displayName": "Ann Noel", "email": ME}, {"displayName": "Milo Marsh", "email": "a@x"}, {"displayName": "Vale Talbot", "email": "h@x"}]},
            {"id": "19:a_b@example.org", "chatType": "oneOnOne", "topic": None, "members": [
                {"displayName": "Ann Noel", "email": ME}, {"displayName": "Gray Selby", "email": "n@x"}]}]))
        self.call("teams_list_channels", {"teamId": "team-1"}, text([{"id": "19:c1@example.org", "displayName": "dev"}]))
        before = self.con.total_changes
        b = teams_capture.build(teams_capture.load(self.cap), self.con)
        self.assertEqual(self.con.total_changes, before)   # reads only
        self.assertTrue(b["complete"])
        self.assertEqual((b["available"], b["searches"], b["reads"]), (5, 2, 1))
        r = {x["external_id"]: x for x in b["records"]}
        milo = r["teams:19:g1@example.org:101"]
        self.assertEqual((milo["conversation_kind"], milo["conversation_name"], milo["ts"]), ("group", "Group chat: Milo Marsh, Vale Talbot", "2026-11-17T08:17:00Z"))
        self.assertIn("the deck", milo["body_html"])                     # the full text, not the search's clip
        self.assertEqual(milo["attachments"], [{"name": "deck.pptx", "content_type": "reference", "size": None, "url": "https://x.sharepoint.com/deck.pptx"}])
        self.assertEqual(r["teams:19:g1@example.org:102"]["body_text"], "On it")   # not read in full: the search's text
        dm = r["teams:19:a_b@example.org:301"]
        self.assertEqual((dm["conversation_kind"], dm["conversation_name"]), ("dm", "1:1 chat Gray Selby"))   # only Ann wrote: the member list names it
        chan = r["teams:19:c1@example.org:201"]
        self.assertEqual((chan["conversation_kind"], chan["conversation_name"], chan["noise"]), ("channel", "Teams channel: dev", False))
        self.assertTrue(r["teams:19:c1@example.org:202"]["noise"])          # a bot relayed through Slack Bridge
        # the bundle goes in like any pull: stored, the full text kept, a second ingest adds nothing
        wins = [("2026-11-17T07:30:00Z", None)]
        bundle = teams_capture.bundle(b, wins, "2026-11-17T08:30:00Z", "test")
        self.assertEqual(bundle["pulls"][0]["complete"], True)
        for rec in bundle["chat_messages"]:
            chatsync.store_record(self.con, rec)
        n = self.con.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        for rec in bundle["chat_messages"]:
            chatsync.store_record(self.con, rec)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], n)
        body = self.con.execute("SELECT body_text FROM chat_messages WHERE external_id='teams:19:g1@example.org:101'").fetchone()[0]
        self.assertEqual(body, "Dear Team. I need a clear answer on [the deck](https://x.sharepoint.com/deck.pptx).\nThanks")

    def test_an_unfinished_search_or_an_error_is_not_complete(self):
        self.call("chat_message_search", {"query": "*", "afterDateTime": "2026-11-17T07:30:00Z", "offset": 0},
                  text([search_hit("19:g1@example.org", "101", "Milo Marsh", "hi", "2026-11-17T08:17:00Z")], more=1))
        b = teams_capture.build(teams_capture.load(self.cap), self.con)
        self.assertFalse(b["complete"])
        self.assertIn("gaps", teams_capture.bundle(b, [("2026-11-17T07:30:00Z", None)], "2026-11-17T08:30:00Z", "x"))
        self.call("chat_message_search", {"query": "*", "afterDateTime": "2026-11-17T07:30:00Z", "offset": 1},
                  text([{"code": "FORBIDDEN", "message": "Missing scope"}]))
        b = teams_capture.build(teams_capture.load(self.cap), self.con)
        self.assertEqual((b["complete"], b["errors"]), (False, ["chat_message_search: FORBIDDEN"]))

    def test_a_message_an_earlier_pull_stored_under_its_bare_id_keeps_it(self):
        chatsync.store_record(self.con, {"source_id": "teams", "external_id": "101", "conversation_id": "19:g1@example.org", "conversation_name": "x",
                                         "conversation_kind": "group", "ts": "2026-11-17T08:17:00Z", "author": "Milo Marsh", "body_text": "Dear Team. I need a clear…"})
        self.call("chat_message_search", {"query": "*", "afterDateTime": "2026-11-17T07:30:00Z", "offset": 0},
                  text([search_hit("19:g1@example.org", "101", "Milo Marsh", "Dear Team. I need a clear…", "2026-11-17T08:17:00Z")]))
        b = teams_capture.build(teams_capture.load(self.cap), self.con)
        self.assertEqual(b["records"][0]["external_id"], "101")
        self.assertEqual(b["records"][0]["conversation_name"], "Group chat: Milo Marsh")

    def test_windows_start_before_the_last_pull_and_a_backfill_goes_day_by_day(self):
        now = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(teams_capture.windows(self.con, now=now), [("2026-11-14T09:00:00Z", None)])   # nothing on record: 3 days
        self.con.execute("INSERT INTO pulls (source_id, complete, finished_at) VALUES ('teams', 1, '2026-11-17T08:29:59Z')")
        self.assertEqual(teams_capture.windows(self.con, now=now), [("2026-11-17T07:59:59Z", None)])
        w = teams_capture.windows(self.con, ("2026-11-15", "2026-11-17"), now=now)
        self.assertEqual(w, [("2026-11-15T00:00:00Z", "2026-11-16T00:00:00Z"), ("2026-11-16T00:00:00Z", "2026-11-17T00:00:00Z")])
        self.assertIn("once for each of these windows", teams_capture.prompt(w))

    def test_the_hook_keeps_only_connector_results_and_never_fails(self):
        hook = str(teams_capture.HOOK)
        env = dict(os.environ, ASSIST_CAPTURE=str(self.cap / "h"))
        ev = {"tool_name": "mcp__claude_ai_Microsoft_365__chat_message_search", "tool_input": {"query": "*"}, "tool_response": [{"type": "text", "text": "{}"}]}
        for e in (ev, {**ev, "tool_name": "Bash"}, "not json"):
            p = subprocess.run([sys.executable, hook], input=json.dumps(e) if isinstance(e, dict) else e, env=env, capture_output=True, text=True)
            self.assertEqual((p.returncode, p.stdout), (0, ""))
        files = list((self.cap / "h").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text())["tool"], "chat_message_search")
        p = subprocess.run([sys.executable, hook], input=json.dumps(ev), env={k: v for k, v in env.items() if k != "ASSIST_CAPTURE"}, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)   # without the variable it does nothing


class SlackPull(unittest.TestCase):
    """The Slack run writes one file in the scratch folder; slack_pull checks it, files it in the queue and ingests it."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.con = db.connect(self.home / "t.db")
        db.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_window_then_the_file_is_checked_filed_and_ingested(self):
        from unittest import mock
        from assist import slack_pull
        now = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(slack_pull.window(self.con, now=now), ("2026-11-14T09:00:00Z", None))
        self.con.execute("INSERT INTO pulls (source_id, complete, finished_at) VALUES ('slack', 1, '2026-11-17T08:30:00Z')")
        self.assertEqual(slack_pull.window(self.con, now=now), ("2026-11-17T08:00:00Z", None))
        self.assertEqual(slack_pull.window(self.con, ("2026-11-01", "2026-11-02")), ("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"))
        calls = []

        def fake(cmd, **kw):
            calls.append((cmd, kw))
            if cmd[1] == "-p":   # the Slack run: it writes the file the prompt names
                path = Path(kw["cwd"]) / "bundle.json"
                self.assertIn(str(path), cmd[2])
                path.write_text(json.dumps({"pulls": [{"source_id": "slack", "available": 1, "pulled": 1, "complete": True, "note": "read"}],
                                            "chat_messages": [{"source_id": "slack", "external_id": "D1:1.2", "conversation_id": "D1", "conversation_name": "DM Gray Selby",
                                                               "conversation_kind": "dm", "ts": "2026-11-17T08:40:00Z", "author": "Gray Selby", "body_text": "ok"},
                                                              {"note": "not a message"}]}))
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"type": "result", "result": "1 message"}) + "\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")   # the ingest
        class Kept:   # the test's connection, which run() may "close"
            def __init__(self, c): self.c = c
            def __getattr__(self, k): return getattr(self.c, k)
            def close(self): pass
        with mock.patch.object(slack_pull.db, "connect", return_value=Kept(self.con)), mock.patch.object(slack_pull.db, "ASSIST", self.home), \
                mock.patch.object(slack_pull, "SCRATCH", self.home / "scratch"), mock.patch.object(slack_pull.subprocess, "run", side_effect=fake):
            ok, note = slack_pull.run("claude", "sonnet", "DMs, group DMs and #product-steering", log=lambda x: None)
        self.assertTrue(ok)
        claude, ingest = calls
        self.assertNotIn("Bash", claude[0][claude[0].index("--allowedTools"):claude[0].index("--disallowedTools")])   # no commands
        self.assertNotEqual(Path(claude[1]["cwd"]).parent, Path.cwd())                                                  # not the project folder
        filed = json.loads(Path(ingest[0][-1]).read_text())
        self.assertEqual(Path(ingest[0][-1]).parent, self.home / "inbox" / "queue")
        self.assertEqual([m["external_id"] for m in filed["chat_messages"]], ["D1:1.2"])   # the record without an id is dropped
        self.assertEqual(filed["pulls"][0]["window_from"], "2026-11-17T08:00:00Z")
        self.assertFalse((self.home / "scratch").exists() and any((self.home / "scratch").iterdir()))   # scratch cleared


if __name__ == "__main__":
    unittest.main()
