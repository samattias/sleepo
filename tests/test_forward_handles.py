"""A forward handles an email whose right response was a forward (assist/replies.py forwarded; Sam, 23 Oct 2026: his forward
of Noel Owner's advisory to Gray stayed on Needs response, because Gray was not on the original and Apple Mail gave the
forward its own conversation id). A forward does not answer mail that wanted a reply.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import unittest

from assist import replies
from test_open_items import Base

SAM = "sam.doe@acme.example"


class ForwardHandles(Base):
    def setUp(self):
        super().setUp()
        self.orig = self.mail("inbox", "kfrank@company703.com", ["teo@company293.com", SAM], "Cyber Vulnerability - Margie Portfolio", 2, conv="c1", name="Noel Owner")

    def row(self, i):
        return self.con.execute("SELECT * FROM mail_messages WHERE item_id=?", (i,)).fetchone()

    def test_forward_found_whoever_it_went_to(self):
        fwd = self.mail("sentitems", SAM, ["gray.selby@acme.example"], "FW: Cyber Vulnerability - Margie Portfolio", 1, conv="c2")
        self.mail("sentitems", SAM, ["gray.selby@acme.example"], "RE: Cyber Vulnerability - Margie Portfolio", 1, conv="c3")   # a reply is not a forward
        self.assertEqual(replies.forwarded(replies.sent_threads(self.con), self.row(self.orig))["item_id"], fwd)
        self.assertIsNone(replies.sam_wrote(replies.sent_threads(self.con), self.row(self.orig)))   # no one in common: not a reply

    def test_not_before_it_nor_long_after(self):
        self.mail("sentitems", SAM, ["gray.selby@acme.example"], "FW: Cyber Vulnerability - Margie Portfolio", 3, conv="c2")    # before
        self.assertIsNone(replies.forwarded(replies.sent_threads(self.con), self.row(self.orig)))

    def test_answers_only_when_a_forward_was_the_response(self):
        self.mail("sentitems", SAM, ["gray.selby@acme.example"], "FW: Cyber Vulnerability - Margie Portfolio", 1, conv="c2")
        answered = lambda: next(m for m in replies.inbox(self.con) if m["id"] == self.orig)["answered"]
        self.assertFalse(answered())                                   # it wanted a reply, as far as SleePO knows
        self.con.execute("INSERT INTO reply_predrafts (item_id, status, body, mode, tries, created_at) VALUES (?, 'ok', 'x', 'forward', 1, '2026-10-22T00:00:00Z')", (self.orig,))
        self.con.commit()
        self.assertTrue(answered())                                    # its recommended response was a forward: done


if __name__ == "__main__":
    unittest.main()
