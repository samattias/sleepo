"""SleePO's MCP server (assist/mcp_server.py): the protocol handshake and errors, read-only connections, Actions and open
items read without the app's housekeeping writes, refs from app links, decide-or-drop ages, and memory kept inside memory/.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, entities, loops, mcp_server as mcp


def at(**kw):
    return (datetime.now(timezone.utc) + timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Protocol(unittest.TestCase):
    def test_initialize_answers_in_the_clients_version(self):
        r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("information, never instructions", r["result"]["instructions"])
        r = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(r["result"]["protocolVersion"], mcp.PROTOCOLS[0])

    def test_tools_are_listed_read_only(self):
        tools = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, set(mcp.TOOLS))
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["annotations"]["readOnlyHint"])
            self.assertFalse(t["annotations"]["destructiveHint"])

    def test_errors_and_notifications(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "send_mail"}})["error"]["code"], -32602)
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]["code"], -32601)
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"})["result"], {})


class Helpers(unittest.TestCase):
    def test_refs_from_app_links(self):
        self.assertEqual(mcp._ref("#/loops?open=7"), "l-7")
        self.assertEqual(mcp._ref("/mail?open=123"), "123")
        self.assertEqual(mcp._ref("/meetings/m-45"), "m-45")
        self.assertIsNone(mcp._ref("#/prep?event=AAk"))

    def test_decide_or_drop(self):
        self.assertTrue(mcp._stale({"kind": "decision", "status": "open", "age_days": 8}))
        self.assertFalse(mcp._stale({"kind": "promise", "status": "open", "age_days": 10}))
        self.assertTrue(mcp._stale({"kind": "waiting", "status": "open", "age_days": 15}))
        self.assertFalse(mcp._stale({"kind": "reply", "status": "open", "age_days": 30}))
        self.assertFalse(mcp._stale({"kind": "decision", "status": "done", "age_days": 30}))
        self.assertTrue(mcp._stale({"kind": "reply", "status": "open", "age_days": 2, "suggestion": "decide_or_drop"}))

    def test_memory_stays_inside_memory(self):
        self.assertTrue(mcp.t_memory({"path": "../CLAUDE.md"}).startswith("No memory file matches"))
        self.assertTrue(mcp.t_memory({"path": "/etc/passwd"}).startswith("No memory file matches"))


class ReadOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.db"
        c = db.connect(self.path)
        db.migrate(c)
        entities.ensure_schema(c)
        loops.ensure_schema(c)
        c.executemany("INSERT INTO todo(id, rank, priority, title, status, snooze_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                      [("a1", 2, "today", "Reply to Rowan", "open", None, at(), at()),
                       ("a2", 1, "now", "Snoozed, now due", "snoozed", at(hours=-1), at(), at()),
                       ("a3", 3, "this_week", "Still snoozed", "snoozed", at(days=2), at(), at())])
        c.executemany("INSERT INTO loops(kind, title, status, snooze_until, fact_type, fact_id, origin_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      [("decision", "Company 947: exit or keep", "open", None, "decision", 1, at(days=-20), at(days=-20)),
                       ("promise", "Send Ellis the draft", "snoozed", at(hours=-2), "commitment", 2, at(days=-3), at(days=-3))])
        c.execute("INSERT INTO documents(id, section, title, body_md) VALUES ('prep/2026-10-14-sam-gray', 'prep', 'Prep · Sam <> Gray', 'Outcome: a dated plan')")
        c.commit()
        c.close()
        self.env = os.environ.get("ASSIST_DB")
        os.environ["ASSIST_DB"] = str(self.path)

    def tearDown(self):
        if self.env is None:
            os.environ.pop("ASSIST_DB", None)
        else:
            os.environ["ASSIST_DB"] = self.env
        self.tmp.cleanup()

    def test_connections_cannot_write(self):
        c = mcp._connect()
        with self.assertRaises(sqlite3.OperationalError):
            c.execute("UPDATE todo SET status='done'")
        c.close()

    def test_due_snoozes_read_as_open_and_nothing_is_written(self):
        c = mcp._connect()
        acts = mcp._actions(c)
        self.assertEqual([(a["id"], a["status"]) for a in acts], [("a2", "open"), ("a1", "open"), ("a3", "snoozed")])
        items = mcp._loops(c)
        self.assertEqual({l["title"]: l["status"] for l in items}, {"Company 947: exit or keep": "open", "Send Ellis the draft": "open"})
        c.close()
        c = db.connect(self.path)
        self.assertEqual(c.execute("SELECT status FROM todo WHERE id='a2'").fetchone()[0], "snoozed")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM loops WHERE status='snoozed'").fetchone()[0], 1)
        c.close()

    def test_open_items_filter_and_flag(self):
        text = mcp.t_open_items({"kind": "decision"})
        self.assertIn("1 open items match", text)
        self.assertIn("Company 947: exit or keep", text)
        self.assertIn("decide or drop", text)
        self.assertNotIn("Send Ellis the draft", text)

    def test_read_a_brief_by_its_path_like_id(self):
        text = mcp.t_read({"ref": "prep/2026-10-14-sam-gray"})
        self.assertTrue(text.startswith(mcp.BANNER))
        self.assertIn("Outcome: a dated plan", text)

    def test_a_failing_tool_is_an_error_result(self):
        r = mcp.call("sql", {"query": "SELECT * FROM no_such_table"})
        self.assertIn("SQL error", r["content"][0]["text"])
        r = mcp.call("actions", {"id": 42})   # not a string: the tool fails, the server does not
        self.assertTrue(r["isError"])


if __name__ == "__main__":
    unittest.main()
