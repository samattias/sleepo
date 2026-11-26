"""Connection problems (assist/connections.py; Sam, 17 Nov 2026): Microsoft 365 needed a new sign-in for days, every Teams
pull failed, and the Sources page still said Up to date. Now the sign-in state of each connector is read from
`claude mcp list` (and any pull's init event), stored only when it changes, shown with what it stopped and what to do,
and the sources it stopped are marked on Sources.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import connections, db, source_status

LIST = """Checking MCP server health…

claude.ai Claude Docs: https://api.anthropic.com/v1/pages/mcp - ✔ Connected
claude.ai Process Design - demo.acmecloud.com: https://process-design-mcp.example/c1 - ! Needs authentication
claude.ai Acme Account Intelligence: https://crm.example - ✘ Failed to connect — HTTP 502: Error POSTing to endpoint: {"status":502}
claude.ai Microsoft 365: https://microsoft365.mcp.claude.com/mcp - ! Needs authentication
plugin:productivity:slack: https://mcp.slack.com/mcp (HTTP) - ✔ Connected
plugin:productivity:gmail:  (HTTP) - - Not configured
sleepo: /Users/x/.assist/venv/bin/python -m assist.mcp_server - ✔ Connected
"""
CRM = {"connector": "Acme_Account_Intelligence", "system": "Salesforce"}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Connections(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.db"
        self.con = db.connect(self.path)
        db.migrate(self.con)
        for sid, system, name in [("teams", "teams", "Teams"), ("outlook.inbox", "outlook", "Mail (inbox)"),
                                  ("slack", "slack", "Slack"), ("salesforce", "salesforce", "Salesforce")]:
            self.con.execute("INSERT INTO sources(id, system, name, health) VALUES (?,?,?, 'ok') "
                             "ON CONFLICT(id) DO UPDATE SET health='ok', note=NULL", (sid, system, name))
        self.con.commit()
        self.now = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
        # never the live database: every connection the module opens itself goes to the test file
        self.patches = [mock.patch.object(connections.db, "connect", lambda path=None: db.sqlite3.connect(str(self.path))),
                        mock.patch.object(connections.org, "section", lambda name, default=None: CRM if name == "crm" else (default or {}))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.con.close()
        self.tmp.cleanup()

    def pull(self, sid, complete, at, agent="claude-code:pull-chat"):
        self.con.execute("INSERT INTO pulls(source_id, complete, agent, started_at, finished_at, pulled) VALUES (?,?,?,?,?,0)",
                         (sid, complete, agent, iso(at), iso(at)))
        self.con.execute("UPDATE sources SET last_pull_at=? WHERE id=?", (iso(at), sid))   # a failed pull moves it too
        self.con.commit()

    def stored(self):
        return json.loads(db.get_setting(self.con, connections.KEY) or "{}")

    # ---- reading what Claude Code says

    def test_parse_list(self):
        self.assertEqual(connections.parse_list(LIST),
                         {"Microsoft_365": "needs-auth", "Acme_Account_Intelligence": "failed", "Slack": "connected"})

    def test_init_event_pending_says_nothing_and_aliases_fold(self):
        ev = {"type": "system", "subtype": "init", "mcp_servers": [
            {"name": "claude.ai Microsoft 365", "status": "pending"}, {"name": "claude.ai Slack", "status": "needs-auth"},
            {"name": "plugin:productivity:slack", "status": "connected"}]}
        self.assertEqual(connections.from_init(ev), {"Slack": "connected"})
        self.assertIsNone(connections.from_init({"type": "assistant"}))

    def test_seen_init_ignores_other_lines(self):
        self.assertIsNone(connections.seen_init('{"type":"assistant","message":{"content":[]}}'))
        line = json.dumps({"type": "system", "subtype": "init", "mcp_servers": [{"name": "claude.ai Microsoft 365", "status": "needs-auth"}]})
        self.assertEqual(connections.seen_init(line, "pull-chat"), {"Microsoft_365": "needs-auth"})
        self.assertEqual(self.stored()["items"]["Microsoft_365"]["status"], "needs-auth")

    def test_probe_runs_mcp_list_where_the_pulls_run(self):
        done = subprocess.CompletedProcess([], 0, stdout=LIST, stderr="")
        with mock.patch.object(connections.subprocess, "run", return_value=done) as run:
            self.assertEqual(connections.probe("/somewhere")["Microsoft_365"], "needs-auth")
        args, kw = run.call_args
        self.assertEqual(args[0][1:], ["mcp", "list"])
        self.assertEqual(kw["cwd"], "/somewhere")
        self.assertFalse(any(k.startswith("CLAUDE_CODE_") for k in kw["env"]))
        with mock.patch.object(connections.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 60)):
            self.assertIsNone(connections.probe())

    # ---- storing only what changed

    def test_record_writes_only_on_change_or_after_an_hour(self):
        t0 = iso(self.now)
        self.assertTrue(connections.record(self.con, {"Microsoft_365": "needs-auth", "Slack": "connected"}, "check", t0))
        self.assertFalse(connections.record(self.con, {"Microsoft_365": "needs-auth"}, "check", iso(self.now + timedelta(minutes=30))))
        self.assertEqual(self.stored()["checked"], t0)
        later = iso(self.now + timedelta(minutes=61))
        self.assertTrue(connections.record(self.con, {"Microsoft_365": "needs-auth"}, "check", later))
        self.assertEqual(self.stored()["items"]["Microsoft_365"]["since"], t0)   # still the same problem
        fixed = iso(self.now + timedelta(minutes=70))
        self.assertTrue(connections.record(self.con, {"Microsoft_365": "connected"}, "check", fixed))
        self.assertEqual(connections.issues(self.con, self.now + timedelta(minutes=70)), [])
        self.assertFalse(connections.record(self.con, {"Somebody_else": "needs-auth"}, "check", fixed))   # not watched

    # ---- what the app shows

    def test_signin_issue_names_the_sources_it_stopped(self):
        self.pull("teams", 1, self.now - timedelta(days=11))
        self.pull("teams", 0, self.now - timedelta(hours=2))
        self.pull("outlook.inbox", 0, self.now - timedelta(hours=2), "claude-code:pull-retry")
        self.pull("outlook.inbox", 1, self.now - timedelta(minutes=20), "assist:mail-local")   # Apple Mail still delivers
        connections.record(self.con, {"Microsoft_365": "needs-auth", "Slack": "connected"}, "check", iso(self.now))
        before = self.con.total_changes
        (i,) = connections.issues(self.con, self.now)
        self.assertEqual(self.con.total_changes, before)   # reads never write
        self.assertEqual((i["key"], i["kind"], i["urgent"]), ("Microsoft_365", "signin", True))
        self.assertEqual([a["id"] for a in i["affected"]], ["teams"])
        self.assertEqual(i["affected"][0]["last_ok"], iso(self.now - timedelta(days=11)))
        self.assertEqual(i["fix"]["login"], "Microsoft_365")
        self.assertIn("Microsoft 365", i["fix"]["label"])
        self.assertEqual(i["fix"]["also"]["command"], 'claude mcp login "claude.ai Microsoft 365"')

    def test_sources_page_says_signin_needed_not_up_to_date(self):
        self.pull("teams", 1, self.now - timedelta(days=11))
        self.pull("teams", 0, self.now - timedelta(minutes=10))
        connections.record(self.con, {"Microsoft_365": "needs-auth"}, "check", iso(self.now))
        teams = source_status.systems(self.con, self.now)["teams"]
        self.assertEqual((teams["state"], teams["label"], teams["issue"]), ("off", "Sign-in needed", "Microsoft_365"))
        self.assertGreater(teams["age_hours"], 24 * 10)   # aged from the last pull that came in full
        connections.record(self.con, {"Microsoft_365": "connected"}, "check", iso(self.now + timedelta(minutes=1)))
        self.pull("teams", 1, self.now)
        self.assertEqual(source_status.systems(self.con, self.now)["teams"]["state"], "fresh")

    def test_unreachable_connector_waits_before_the_header(self):
        self.pull("salesforce", 1, self.now - timedelta(days=32), "claude-code:salesforce")   # stale while it failed
        connections.record(self.con, {"Acme_Account_Intelligence": "failed"}, "check", iso(self.now))
        (i,) = connections.issues(self.con, self.now + timedelta(hours=1))
        self.assertEqual((i["kind"], i["urgent"]), ("unreachable", False))
        self.assertEqual([a["id"] for a in i["affected"]], ["salesforce"])
        (i,) = connections.issues(self.con, self.now + timedelta(hours=7))
        self.assertTrue(i["urgent"])

    def test_local_imports(self):
        connections.note_local("apple-mail", "no-access")
        (i,) = connections.issues(self.con, self.now)
        self.assertEqual((i["kind"], i["fix"]["open"], i["fix"]["also"]["open"]), ("access", "disk", "python"))
        connections.note_local("apple-mail", "ok")
        self.assertEqual(connections.issues(self.con, self.now), [])
        connections.note_local("granola-mcp", "signed-out")
        self.assertIn("granola-login", connections.issues(self.con, self.now)[0]["fix"]["command"])

    def test_no_retry_for_sources_waiting_for_a_signin(self):
        connections.record(self.con, {"Microsoft_365": "needs-auth", "Slack": "connected"}, "check", iso(self.now))
        self.assertEqual(connections.needs_signin(self.con, ["outlook.inbox", "teams", "slack", "calendar"]), ["outlook.inbox", "teams"])

    def test_check_keeps_the_server_name_for_signing_in(self):
        done = subprocess.CompletedProcess([], 0, stdout=LIST, stderr="")
        with mock.patch.object(connections.subprocess, "run", return_value=done):
            connections.check("check")
        items = self.stored()["items"]
        self.assertEqual(items["Slack"]["server"], "plugin:productivity:slack")
        self.assertEqual(items["Microsoft_365"]["server"], "claude.ai Microsoft 365")

    def test_login_opens_claudes_signin_link_only(self):
        connections.record(self.con, {"Microsoft_365": "needs-auth"}, "check", iso(self.now), servers={"Microsoft_365": "claude.ai Microsoft 365"})
        out = ("Visit this URL to authorize:\n  https://claude.ai/api/organizations/abc/mcp/start-auth/xyz?redirect=1\n\n"
               "Once authorized on claude.ai, the connector will be available the next time you start Claude Code.\n")
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=out if cmd[1:3] == ["mcp", "login"] else "", stderr="")
        with mock.patch.object(connections.subprocess, "run", side_effect=run):
            r = connections.login(self.con, "Microsoft_365", "/somewhere")
        self.assertTrue(r["opened"])
        self.assertEqual(calls[0][1:], ["mcp", "login", "--no-browser", "claude.ai Microsoft 365"])
        self.assertEqual(calls[1], ["open", "https://claude.ai/api/organizations/abc/mcp/start-auth/xyz?redirect=1"])
        # a link anywhere else is never opened, and only connectors SleePO uses can be signed in to
        calls.clear()
        out = "Visit this URL to authorize:\n  https://evil.example/claude.ai/x\n"
        with mock.patch.object(connections.subprocess, "run", side_effect=run):
            self.assertFalse(connections.login(self.con, "Microsoft_365")["opened"])
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            connections.login(self.con, "apple-mail")

    def test_open_targets_are_fixed(self):
        with mock.patch.object(connections.subprocess, "run") as run:
            connections.open_target("mail")
            self.assertEqual(run.call_args[0][0], ["open", "-a", "Mail"])
            with self.assertRaises(ValueError):
                connections.open_target("https://example.com")


if __name__ == "__main__":
    unittest.main()
