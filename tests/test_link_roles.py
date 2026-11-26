"""Links carry a role and evidence, Sam's verdicts stick and teach, documents/products/Jira are linked, and who-said-what
only keeps points and placements that match a real turn of that speaker (assist/entities.py, refs.py, speakers.py).
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assist import db, entities, speakers


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class LinkRoles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox','outlook','i'), ('granola','granola','g'), "
                  "('teams','teams','t'), ('sharepoint','sharepoint','s')")
        c.executemany("INSERT INTO people(id, name, is_me) VALUES (?,?,?)", [(1, "Sam Doe", 1), (2, "Pat Noel", 0), (3, "Gray Selby", 0), (4, "Rowan Lowell", 0)])
        c.executemany("INSERT INTO people_aliases VALUES (?,?)", [("pat.lee@acme.example", 2), ("pat lee", 2), ("gray.selby@acme.example", 3), ("gray selby", 3),
                                                                   ("rowan lowell", 4), ("rowan.lowell@acme.example", 4)])
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def item(self, src, kind, text="x", subject=None, from_name=None, url=None):
        self.n += 1
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, text, from_name, url, pulled_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (self.n, src, f"e{self.n}", kind, ago(1), subject, text, from_name, url, ago(0)))
        return self.n

    def link_of(self, item, etype, eid):
        r = self.con.execute("SELECT role, reason, confidence, verdict FROM mentions WHERE ref_type='item' AND ref_id=? AND entity_type=? AND entity_id=?",
                             (item, etype, eid)).fetchone()
        return dict(r) if r else None

    def test_mail_roles_and_mention_evidence(self):
        i = self.item("outlook.inbox", "mail", text="Can Gray Selby review the deck before Friday?", subject="Deck")
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, from_address, to_json, cc_json, subject, synced_at) VALUES (?,?,?,?,?,?,?,?)",
                         (i, "g", "inbox", "pat.lee@acme.example", json.dumps([{"address": "sam.doe@acme.example"}]), json.dumps([{"address": "rowan.lowell@acme.example"}]), "Deck", ago(0)))
        entities.link(self.con, log=lambda *_: None)
        self.assertEqual(self.link_of(i, "person", 2)["role"], "from")
        self.assertEqual(self.link_of(i, "person", 4)["role"], "cc")
        gray = self.link_of(i, "person", 3)
        self.assertEqual(gray["role"], "mentioned")
        self.assertIn("review the deck", gray["reason"])

    def test_envelope_mail_without_message_row_links_sender_and_recipients(self):
        i = self.item("outlook.inbox", "mail", subject="Old mail")
        self.con.execute("UPDATE items SET payload=? WHERE id=?", (json.dumps({"envelope": "True", "sender": "Pat.Noel@acme.example",
                                                                               "recipients": "['Sam.doe@acme.example', 'gray.selby@acme.example']"}), i))
        entities.link(self.con, log=lambda *_: None)
        self.assertEqual(self.link_of(i, "person", 2)["role"], "from")
        self.assertEqual(self.link_of(i, "person", 3)["role"], "to")

    def test_verdicts_survive_relinking_and_crossed_first_names_stop_matching(self):
        a = self.item("teams", "note", text="Rowan will send the roadmap")
        b = self.item("teams", "note", text="Ask Rowan about pricing")
        c = self.item("teams", "note", text="Rowan again")
        entities.link(self.con, full=True, log=lambda *_: None)
        self.assertTrue(self.link_of(a, "person", 4)["reason"].startswith("first name:"))
        entities.set_verdict(self.con, "item", a, "person", 4, "rejected")
        entities.set_verdict(self.con, "item", b, "person", 4, "rejected")
        self.con.execute("DELETE FROM mentions WHERE ref_id=? AND verdict IS NULL", (c,))
        entities.link(self.con, full=True, log=lambda *_: None)
        self.assertEqual(self.link_of(a, "person", 4)["verdict"], "rejected")   # kept, still rejected
        self.assertIsNone(self.link_of(c, "person", 4))                          # "Rowan" alone no longer links
        self.assertFalse(any(x["id"] == a for x in entities.timeline(self.con, "person", 4)))

    def test_tick_on_a_missing_link_adds_it(self):
        a = self.item("teams", "note", text="nothing about anyone")
        entities.set_verdict(self.con, "item", a, "person", 3, "confirmed", role="attendee")
        entities.link(self.con, full=True, log=lambda *_: None)
        self.assertEqual(self.link_of(a, "person", 3)["verdict"], "confirmed")

    def test_documents_products_and_jira(self):
        d = self.item("sharepoint", "doc", subject="PLT market context two-pager.docx", from_name="Rowan Lowell")
        ch = self.item("teams", "chat", text="here it is")
        self.con.execute("INSERT INTO chat_messages(item_id, source_id, external_id, conversation_id, conversation_name, conversation_kind, author, sent_at, body_text, links_json) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?)", (ch, "teams", "c1", "x", "x", "group", "Gray Selby", ago(1), "here it is",
                                                          json.dumps([{"url": "https://x", "title": "PLT market context two-pager.docx"}])))
        note = self.item("granola", "note", text="We reviewed the PLT market context two-pager; COPILOT pricing and DEV-59722. CVE-2026-1234 is unrelated.")
        entities.link(self.con, full=True, log=lambda *_: None)
        self.assertEqual(self.link_of(d, "person", 4)["role"], "owner")
        self.assertEqual(self.link_of(d, "person", 3)["role"], "shared")
        self.assertEqual(self.link_of(ch, "doc", d)["role"], "shared")
        self.assertEqual(self.link_of(note, "doc", d)["role"], "mentioned")
        refs = {r["type"]: r for r in self.con.execute("SELECT r.type, r.key FROM mentions m JOIN ref_entities r ON r.id=m.entity_id WHERE m.ref_id=? "
                                                       "AND m.entity_type IN ('product','ticket')", (note,))}
        self.assertEqual(refs["product"]["key"], "copilot")
        self.assertEqual(refs["ticket"]["key"], "DEV-59722")
        self.assertFalse(self.con.execute("SELECT 1 FROM ref_entities WHERE key LIKE 'CVE%'").fetchone())


    def test_jira_import_keeps_support_desk_summaries_out(self):
        from assist import refs
        f = Path(self.tmp.name) / "issues.json"
        f.write_text(json.dumps({"issues": [{"key": "DEV-1", "summary": "Fix search", "status": "Done", "type": "Bug"},
                                            {"key": "SUP-9", "summary": "Customer ACME cannot log in", "status": "Resolved", "type": "Question"},
                                            {"key": "not a key", "summary": "x"}]}))
        self.assertEqual(refs.import_issues(self.con, str(f), "2026-10-13T00:00:00Z"), 2)
        names = dict(self.con.execute("SELECT key, name FROM ref_entities WHERE type='ticket'").fetchall())
        self.assertEqual(names["DEV-1"], "Fix search")
        self.assertNotIn("ACME", names["SUP-9"])


class WhoSaidWhat(unittest.TestCase):
    T = {"turns": [{"t": 0, "end": 20, "clock": "14:00", "me": True, "speaker": None, "lines": ["Hello"]},
                   {"t": 30, "end": 60, "clock": "14:00", "me": False, "speaker": "Noel Osborne", "lines": ["Let's do a town hall next week"]},
                   {"t": 65, "end": 70, "clock": "14:01", "me": False, "speaker": "Marlow Harlow", "lines": ["Makes sense"]}]}

    def test_points_must_cite_a_turn_of_the_same_speaker(self):
        data = {"speakers": [{"name": "Noel Osborne", "points": [{"t": "00:45", "text": "Proposes a town hall"}, {"t": "01:06", "text": "Agrees"}]},
                             {"name": "Somebody Else", "points": [{"t": "00:10", "text": "x"}]}]}
        got, dropped = speakers.check(self.T, {"Noel Osborne", "Marlow Harlow"}, data, "Sam Doe")
        self.assertEqual([p["text"] for p in got["Noel Osborne"]], ["Proposes a town hall"])
        self.assertEqual(got["Noel Osborne"][0]["t"], 30)
        self.assertEqual(dropped, 2)

    def test_document_quote_must_be_in_the_transcript_and_about_the_document(self):
        self.assertEqual(speakers._terms("collecting a list of frequently asked questions") & speakers._terms("Connect, Copilot - FAQs"), {"faq"})
        self.assertFalse(speakers._terms("I don't know, man.") & speakers._terms("joint solution context layer agent execution"))


if __name__ == "__main__":
    unittest.main()
