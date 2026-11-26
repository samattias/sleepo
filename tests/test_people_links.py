"""Everything with a person reaches their page (assist/entities.py): email from, to or cc them, and every message in a DM or
group chat they are in, Sam's own included. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, entities


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class PeopleLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox','outlook','i'), ('outlook.sent','outlook','s'), ('teams','teams','t')")
        c.executemany("INSERT INTO people(id, name, is_me) VALUES (?,?,?)", [(1, "Sam Doe", 1), (2, "Pat Noel", 0), (3, "Gray Selby", 0),
                                                                            (4, "Dan One", 0), (5, "Dan Two", 0)])
        c.executemany("INSERT INTO people_aliases VALUES (?,?)", [("pat.lee@acme.example", 2), ("pat lee", 2), ("gray.selby@acme.example", 3), ("gray selby", 3)])
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def item(self, src, kind, days, text="x"):
        self.n += 1
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, text, pulled_at) VALUES (?,?,?,?,?,?,?)",
                         (self.n, src, f"e{self.n}", kind, ago(days), text, ago(0)))
        return self.n

    def mail(self, folder, frm, to, cc=(), days=1):
        i = self.item("outlook.sent" if folder == "sentitems" else "outlook.inbox", "mail", days)
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, from_address, to_json, cc_json, subject, received_at, sent_at, synced_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?)", (i, f"g{i}", folder, frm, json.dumps([{"address": a} for a in to]),
                                                           json.dumps([{"address": a} for a in cc]), f"subject {i}", ago(days), ago(days), ago(0)))
        return i

    def chat(self, conv, kind, author, text, days=1):
        i = self.item("teams", "chat", days, text)
        self.con.execute("INSERT INTO chat_messages(item_id, source_id, external_id, conversation_id, conversation_name, conversation_kind, author, sent_at, body_text) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (i, "teams", f"c{i}", conv, conv, kind, author, ago(days), text))
        return i

    def linked(self, person):
        return {r[0] for r in self.con.execute("SELECT ref_id FROM mentions WHERE ref_type='item' AND entity_type='person' AND entity_id=? AND confidence >= 0.6", (person,))}

    def test_mail_from_to_and_cc_all_reach_the_person(self):
        a = self.mail("inbox", "pat.lee@acme.example", ["sam.doe@acme.example"])
        b = self.mail("sentitems", "sam.doe@acme.example", ["gray.selby@acme.example"], cc=["pat.lee@acme.example"])
        c = self.mail("inbox", "gray.selby@acme.example", ["sam.doe@acme.example"])
        entities.link(self.con, log=lambda *_: None)
        self.assertEqual(self.linked(2) & {a, b, c}, {a, b})
        roles = {x["id"]: (x.get("role"), x.get("mine")) for x in entities.timeline(self.con, "person", 2)}
        self.assertEqual(roles, {a: ("from", False), b: ("cc", True)})

    def test_both_sides_of_a_dm_and_everyone_in_a_group_chat(self):
        mine = self.chat("DM Pat Noel", "dm", "Sam Doe", "Can you send the plan?")
        theirs = self.chat("DM Pat Noel", "dm", "Pat Noel", "Sending now")
        quiet = self.chat("group chat Gray, Pat", "group", "Gray Selby", "Budget is in")   # Pat is in the chat but did not write
        teams1on1 = self.chat("Sam / Pat", "oneOnOne", "Sam Doe", "Thanks")
        ambiguous = self.chat("group chat Dan, Gray", "group", "Gray Selby", "Hi")         # "Dan" is two people: nobody guessed
        entities.link(self.con, log=lambda *_: None)
        self.assertTrue({mine, theirs, quiet, teams1on1} <= self.linked(2))
        self.assertNotIn(ambiguous, self.linked(4) | self.linked(5))
        t = {x["id"]: x for x in entities.timeline(self.con, "person", 2)}
        self.assertEqual((t[mine]["mine"], t[mine]["dm"], t[mine]["title"]), (True, True, "Can you send the plan?"))
        self.assertEqual((t[quiet]["mine"], t[quiet]["where"]), (False, "group chat Gray, Pat"))

    def test_other_names_shared_mailboxes_and_first_names_in_notes(self):
        c = self.con
        c.execute("INSERT INTO people(id, name) VALUES (6, 'Noel Osborne'), (7, 'Finley One'), (8, 'Finley Two')")
        c.execute("INSERT INTO people_aliases VALUES ('noel osborne', 6), ('jira@acme.atlassian.net', 3)")   # a Jira mail once 'from Gray'
        other = self.mail("inbox", "quinn.dalton@acme.example", ["sam.doe@acme.example"])
        jira = self.mail("inbox", "jira@acme.atlassian.net", ["sam.doe@acme.example"])
        c.execute("UPDATE items SET from_name='Pat Noel (Jira)' WHERE id=?", (jira,))
        chat = self.chat("group chat ops", "group", "Quinn Dalton", "Done")
        note = self.item("teams", "note", 1, "Noel to share the plan. Finley owns the build. We will mark it done.")
        entities.link(c, log=lambda *_: None)
        self.assertTrue({other, chat, note} <= self.linked(6))
        self.assertNotIn(jira, self.linked(3))          # the shared mailbox is nobody's alias any more
        self.assertIn(jira, {r[0] for r in c.execute("SELECT ref_id FROM mentions WHERE entity_type='person' AND entity_id=2")})   # who acted, low confidence
        self.assertNotIn(note, self.linked(7) | self.linked(8))   # two Scotts: nobody guessed
        self.assertIsNone(c.execute("SELECT 1 FROM people_aliases WHERE alias LIKE 'jira@%'").fetchone())


if __name__ == "__main__":
    unittest.main()
