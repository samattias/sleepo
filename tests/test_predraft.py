"""Pre-drafted replies (assist/replies.py predraft): only mail waiting on Sam, one draft each, failures retried at most
three times, the draft stored for the Inbox and recorded for the reply evaluation, and old ones cleared.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from assist import replies
from assist.retention import RETENTION_DAYS


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    from assist.migrations import m015_reply_predrafts, m017_response_calls
    m015_reply_predrafts.up(con)
    m017_response_calls.up(con)
    return con


MAIL = [{"id": 1, "subject": "Pricing for Q1", "needs_reply": True}, {"id": 2, "subject": "FYI", "needs_reply": False},
        {"id": 3, "subject": "PLT timeline?", "needs_reply": True}]
TEAM = [{"name": "Gray Selby", "role": "VP Development & Engineering", "address": "gray.selby@acme.example"}]
REPLY = json.dumps({"subject": "Re: Pricing for Q1", "body": "Hi Quinn,\n\nYes, let us use the new rules.\n\n-Sam", "notes": "check the date"})


class Predraft(unittest.TestCase):
    def run_it(self, con, outs):
        with mock.patch.object(replies, "inbox", lambda c: MAIL), \
                mock.patch.object(replies, "prompt", lambda c, i, *a, **k: ("prompt", {"conversation_id": f"c{i}"})), \
                mock.patch.object(replies, "team", lambda c: TEAM), mock.patch.object(replies, "response_triage", lambda *a, **k: 0), \
                mock.patch.object(replies, "_run", side_effect=outs), \
                mock.patch("assist.feedback.record_draft") as rec, mock.patch("assist.feedback.last_model", lambda c, p: "claude-opus-5-5"):
            res = replies.predraft(con, ".", log=lambda *_: None)
        return res, rec

    def test_drafts_only_mail_waiting_on_sam_and_stores_it(self):
        con = _db()
        res, rec = self.run_it(con, [(True, REPLY, ""), (True, REPLY, "")])
        self.assertEqual((res["drafted"], res["failed"]), (2, 0))
        got = replies.predraft_get(con, 1)
        self.assertEqual((got["status"], got["subject"], got["length"]), ("ok", "Re: Pricing for Q1", 3))
        self.assertIn("-Sam", got["body"])
        self.assertIsNone(replies.predraft_get(con, 2))
        self.assertEqual(rec.call_count, 2)   # kept for the draft-vs-sent evaluation
        res, _ = self.run_it(con, [])   # nothing left to draft: no model call
        self.assertEqual(res["drafted"], 0)

    def test_a_failed_draft_is_retried_at_most_three_times(self):
        con = _db()
        for _ in range(3):
            self.run_it(con, [(False, "", "timeout"), (True, REPLY, "")] if _ == 0 else [(False, "", "timeout")])
        self.assertEqual(con.execute("SELECT tries, status FROM reply_predrafts WHERE item_id=1").fetchone()[:], (3, "error"))
        res, _ = self.run_it(con, [])
        self.assertEqual(res["drafted"] + res["failed"], 0)   # given up after three tries; 3 was drafted the first time

    def test_old_predrafts_are_cleared(self):
        con = _db()
        old = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        con.execute("INSERT INTO reply_predrafts (item_id, status, body, created_at) VALUES (9, 'ok', 'x', ?)", (old,))
        self.run_it(con, [(True, REPLY, ""), (True, REPLY, "")])
        self.assertIsNone(replies.predraft_get(con, 9))


class Response(unittest.TestCase):
    """Needs response, not needs reply (22 Oct 2026): the draft chooses reply, reply all or forward, and to whom."""
    def test_a_forward_keeps_its_team_recipients(self):
        con = _db()
        fwd = json.dumps({"response": "forward", "to": ["Gray Selby"], "why": "engineering should patch", "subject": "Fw: PHP advisory",
                          "body": "Gray, please check our PHP exposure.\n\n-Sam", "notes": ""})
        Predraft.run_it(self, con, [(True, fwd, ""), (True, REPLY, "")])
        got = replies.predraft_get(con, 1)
        self.assertEqual((got["mode"], json.loads(got["recipients"]), got["why"]), ("forward", ["gray.selby@acme.example"], "engineering should patch"))
        self.assertEqual(replies.predraft_get(con, 3)["mode"], "reply")   # no response given: a plain reply

    def test_a_forward_to_no_one_becomes_a_reply(self):
        con = _db()
        fwd = json.dumps({"response": "forward", "to": [], "subject": "Fw: x", "body": "x\n\n-Sam", "notes": ""})
        Predraft.run_it(self, con, [(True, fwd, ""), (True, REPLY, "")])
        self.assertEqual(replies.predraft_get(con, 1)["mode"], "reply")

    def test_the_response_check_stores_forwards_to_the_team_only(self):
        con = _db()
        con.executescript("CREATE TABLE mail_messages (item_id INTEGER, to_json TEXT, cc_json TEXT, body_text TEXT);"
                          "INSERT INTO mail_messages VALUES (5, '[]', '[]', 'A critical PHP vulnerability. Please review.');"
                          "INSERT INTO mail_messages VALUES (6, '[]', '[]', 'Newsletter');")
        left_out = [{"id": 5, "subject": "Cyber vulnerability", "from_name": "Noel Owner", "from_address": "k@example.org", "needs_reply": False,
                     "considered": True, "reply_why": "addressed to Margie Portfolio Technology Leadership"},
                    {"id": 6, "subject": "News", "from_name": "X", "from_address": "x@y.com", "needs_reply": False, "considered": True, "reply_why": "group mail"}]
        out = json.dumps([{"id": 5, "response": "forward", "to": ["gray.selby@acme.example", "someone@else.com"], "why": "forward to Gray: engineering should patch"},
                          {"id": 6, "response": "none"}, {"id": 99, "response": "reply"}])
        with mock.patch.object(replies, "inbox", lambda c, days=14: left_out), mock.patch.object(replies, "team", lambda c: TEAM), \
                mock.patch("assist.llm.run", lambda *a, **k: out), mock.patch("assist.feedback.last_model", lambda c, p: "m"):
            self.assertEqual(replies.response_triage(con, ".", log=lambda *_: None), 1)
        rows = {r[0]: (r[1], json.loads(r[2])) for r in con.execute("SELECT item_id, response, recipients FROM response_calls")}
        self.assertEqual(rows, {5: ("forward", ["gray.selby@acme.example"]), 6: ("none", [])})   # 99 was not asked about


if __name__ == "__main__":
    unittest.main()
