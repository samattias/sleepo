"""Ask SleePO answers that run on their own (assist/chat.py start, live_events; Sam, 25 Nov 2026: "When the assistant is
working, I'm not able to access any other chats or previous chats ... make sure that we can run multiple assistants in
parallel"). Each answer runs in a thread of its own and the page follows it with short requests; a conversation answers one
question at a time, several conversations answer at once. Claude is replaced by a fake stream; the database and the
workspace folder are throwaway ones, and nothing touches the live jobs/ folder.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from assist import chat, claude_open, db, desktop
from assist.routes import chat as routes


class Live(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for p in (mock.patch.dict(os.environ, {"ASSIST_DB": str(root / "t.db")}),
                  mock.patch.object(claude_open, "WORKSPACE", root / "ws"),
                  mock.patch.object(chat, "summarize_later", lambda tid: None),   # no real Claude call to name a conversation
                  mock.patch.object(chat, "_LIVE", {}),
                  mock.patch.object(chat, "RUNS", {}),
                  mock.patch.object(chat, "stream", self.fake_stream),
                  mock.patch.object(desktop, "ids_for_run", lambda run: []),
                  mock.patch.object(desktop, "stop_run", lambda run: None)):
            p.start()
            self.addCleanup(p.stop)
        c = db.connect()
        db.migrate(c)
        c.close()
        self.gates = {}
        self.addCleanup(lambda: [g.set() for g in self.gates.values()])   # never leave a fake answer waiting

    def gate(self, message):
        return self.gates.setdefault(message, threading.Event())

    def fake_stream(self, message, session=None, page=None, workspace=None, thread=None):
        yield {"type": "run", "run": f"run-{message}"}
        yield {"type": "text", "text": "Hello "}
        yield {"type": "text", "text": "there."}
        if not self.gate(message).wait(5):
            yield {"type": "error", "error": "test gate never opened"}
        yield {"type": "done", "session": "s-1", "secs": 1.0, "cost": 0}

    def until(self, job, test):
        for _ in range(250):
            d = chat.live_events(job)
            if test(d):
                return d
            time.sleep(0.02)
        self.fail(f"answer {job} never got there: {chat.live_events(job)}")

    def test_an_answer_runs_on_its_own_and_is_followed_by_short_requests(self):
        r = chat.start("one")
        d = self.until(r["job"], lambda d: d["next"] >= 4)
        self.assertEqual([e["type"] for e in d["events"]], ["thread", "run", "text"])
        self.assertEqual(d["events"][2]["text"], "Hello there.")             # consecutive text arrives as one piece
        self.assertFalse(d["done"])
        self.assertEqual(chat.live_events(r["job"], after=d["next"])["events"], [])
        self.assertEqual([j["job"] for j in chat.live_jobs()], [r["job"]])
        self.assertEqual({t["id"]: t["live"] for t in chat.threads()}, {r["thread"]: r["job"]})   # History shows it answering
        t = chat.thread(r["thread"])
        self.assertEqual((t["live"], [u["role"] for u in t["turns"]]), (r["job"], ["user"]))       # the question is kept at once

        self.gate("one").set()
        d = self.until(r["job"], lambda d: d["done"])
        self.assertEqual(d["events"][-1]["type"], "done")
        t = chat.thread(r["thread"])
        self.assertEqual((t["live"], t["turns"][-1]["role"], t["turns"][-1]["text"]), (None, "assistant", "Hello there."))
        self.assertEqual(chat.live_jobs(), [])

    def test_answers_run_in_parallel_and_a_conversation_takes_one_question_at_a_time(self):
        a, b = chat.start("a"), chat.start("b")
        self.assertNotEqual(a["thread"], b["thread"])
        self.assertEqual(len(chat.live_jobs()), 2)
        with self.assertRaises(ValueError):
            chat.start("again", a["thread"])
        with self.assertRaises(HTTPException) as e:   # the route says so as 429, the page shows it
            routes.api_chat(routes.ChatRequest(message="again", thread=a["thread"]), None)
        self.assertEqual(e.exception.status_code, 429)
        self.gate("b").set()
        self.until(b["job"], lambda d: d["done"])
        self.assertFalse(chat.live_events(a["job"])["done"])                 # one finishing leaves the other running
        self.gate("a").set()
        self.until(a["job"], lambda d: d["done"])
        c = chat.start("again", a["thread"])                                  # once answered, it takes the next question
        self.gate("again").set()
        self.until(c["job"], lambda d: d["done"])
        self.assertEqual([u["text"] for u in chat.thread(a["thread"])["turns"]], ["a", "Hello there.", "again", "Hello there."])

    def test_at_most_max_live_answers_at_once(self):
        with mock.patch.object(chat, "MAX_LIVE", 2):
            chat.start("x")
            chat.start("y")
            with self.assertRaises(ValueError):
                chat.start("z")

    def test_stop_kills_the_answer_s_run(self):
        r = chat.start("long")
        self.until(r["job"], lambda d: d["next"] >= 2)
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.kill.side_effect = lambda: self.gate("long").set()
        chat.RUNS["run-long"] = proc
        self.assertTrue(chat.stop_job(r["job"]))
        proc.kill.assert_called_once()
        self.until(r["job"], lambda d: d["done"])
        self.assertFalse(chat.stop_job("nope"))

    def test_an_answer_a_restart_cut_off_says_so(self):
        c = db.connect()
        c.execute("INSERT INTO chat_threads (id, title, created_at, updated_at) VALUES ('t1', 'Old', '2026-11-25T09:00:00Z', '2026-11-25T09:00:00Z')")
        c.execute("INSERT INTO chat_turns (thread_id, role, text, created_at) VALUES ('t1', 'user', 'Still there?', '2026-11-25T09:00:00Z')")
        c.commit()
        c.close()
        turns = chat.thread("t1")["turns"]
        self.assertEqual([u["role"] for u in turns], ["user", "assistant"])
        self.assertIn("Interrupted", turns[-1]["error"])
        self.assertIsNone(chat.live_events("gone"))


if __name__ == "__main__":
    unittest.main()
