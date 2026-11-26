"""The person page (assist/person_page.py): their own words, documents merged across copies with sensitivity carried over,
the address they actually write from, and the current topics they are part of; where things stand with them
(assist/person_summary.py): the pack, references checked, the latest summary kept and marked out of date.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unittest import mock

from assist import db, entities, loops, person_page, person_summary, topics


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class PersonPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        entities.ensure_schema(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox','outlook','i'), ('outlook.sent','outlook','s'), ('teams','teams','t'), "
                  "('sharepoint','sharepoint','sp')")
        c.executemany("INSERT INTO people(id, name, is_me) VALUES (?,?,?)", [(1, "Sam Doe", 1), (2, "Reese Prescott", 0), (3, "Pat Noel", 0)])
        c.executemany("INSERT INTO people_aliases VALUES (?,?)", [("reese.prescott@acme.example", 2), ("reese.prescott@contoso.example", 2), ("reese prescott", 2),
                                                                  ("pat.lee@acme.example", 3), ("pat lee", 3)])
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def item(self, src, kind, days, text="x", subject=None):
        self.n += 1
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, text, pulled_at) VALUES (?,?,?,?,?,?,?,?)",
                         (self.n, src, f"e{self.n}", kind, ago(days), subject, text, ago(0)))
        return self.n

    def mail(self, frm, to, days=1, folder="inbox", subject="hello", preview="Thanks, the plan works for us."):
        i = self.item("outlook.sent" if folder == "sentitems" else "outlook.inbox", "mail", days, subject=subject)
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, from_address, to_json, cc_json, subject, received_at, sent_at, preview, synced_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (i, f"g{i}", folder, frm, json.dumps([{"address": a} for a in to]), "[]", subject,
                                                             ago(days), ago(days), preview, ago(0)))
        return i

    def attach(self, item_id, name):
        self.con.execute("INSERT INTO mail_attachments(item_id, graph_id, name, is_inline) VALUES (?,?,?,0)", (item_id, f"a{name}", name))
        return self.con.execute("SELECT last_insert_rowid()").fetchone()[0]

    def card(self, doc_id, title, sensitivity="normal", people=()):
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(doc_cards)")}
        vals = {"doc_id": doc_id, "title": title, "kind": "contract", "summary": "s", "sensitivity": sensitivity, "people": json.dumps(list(people)),
                "is_current": 1, "created_at": ago(0)}
        vals = {k: v for k, v in vals.items() if k in cols}
        self.con.execute(f"INSERT INTO doc_cards({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", list(vals.values()))

    def test_page(self):
        a = self.mail("reese.prescott@contoso.example", ["sam.doe@acme.example"], days=2)
        b = self.mail("reese.prescott@contoso.example", ["sam.doe@acme.example"], days=3, subject="Re: contract")
        x1 = self.attach(a, "Waiver Letter.pdf")
        x2 = self.attach(b, "Waiver Letter (1).pdf")   # a second copy of the same file
        self.attach(b, "image001.png")                # a signature, not a document
        self.card(f"ma-{x1}", "Waiver letter", sensitivity="hr-legal")
        self.card("lf-99", "Board notes", people=["Reese Prescott", "Pat Noel"])
        entities.link(self.con, log=lambda *_: None)
        d = person_page.build(self.con, 2)
        self.assertEqual(d["email"], "reese.prescott@contoso.example")   # the address they write from, not the unused guest one
        self.assertEqual(d["teams"], "")
        self.assertEqual([s["kind"] for s in d["said"]], ["email", "email"])
        docs = {x["name"]: x for x in d["documents"]}
        self.assertNotIn("image001.png", docs)
        waiver = [x for x in d["documents"] if x["name"].startswith("Waiver")]
        self.assertEqual(len(waiver), 1)                      # copies merged
        self.assertEqual(waiver[0]["copies"], 2)
        self.assertTrue(waiver[0]["sensitive"])               # one copy's HR/legal card covers both
        self.assertEqual(waiver[0]["how"], "theirs")
        self.assertIn("lf-99", {x["id"] for x in d["documents"]})   # a card that names them
        self.assertIsNone(person_page.build(self.con, 404))

    def topic(self, title, raised, people, rank):
        self.con.execute("INSERT INTO topics(run_at, title, summary, raised_by, people_json, status, rank) VALUES (?,?,?,?,?,'current',?)",
                         (ago(0), title, f"{title} stands", raised, json.dumps(people), rank))

    def test_on_the_table(self):
        topics.ensure_schema(self.con)
        self.con.execute("INSERT INTO people_aliases VALUES ('reese prescott-san', 2)")
        self.topic("Pricing", "Pat Noel", ["Pat Noel", "Reese Prescott"], 1)          # part of it
        self.topic("ORC timeline", "Reese Prescott-san", ["Reese Prescott-san"], 2)     # raised it, under an alias
        self.topic("Budget", "you", ["Pat Noel"], 3)                              # not theirs
        self.topic("Contract", "Reese (ケニア)", [], 4)                           # a first name no one else has, with a note
        got = person_page.on_the_table(self.con, 2, "Reese Prescott")
        self.assertEqual([t["title"] for t in got], ["ORC timeline", "Contract", "Pricing"])   # raised by them first
        self.assertEqual([t["raised"] for t in got], ["them", "them", "Pat Noel"])
        self.assertEqual(person_page.on_the_table(self.con, 3, "Pat Noel")[0]["title"], "Pricing")
        self.assertEqual(person_page.on_the_table(self.con, 3, "Pat Noel")[1]["raised"], "you")

    def test_summary(self):
        loops.ensure_schema(self.con)
        mid = self.mail("reese.prescott@contoso.example", ["sam.doe@acme.example"], days=2, subject="ORC dates", preview="Can you confirm the ORC dates?")
        self.con.execute("INSERT INTO loops(kind, title, person_id, origin_at, status, created_at, updated_at, fact_type, fact_id) VALUES ('reply','Reply to Reese Prescott: ORC dates',2,?,'open',?,?,'mail',1)",
                         (ago(2), ago(2), ago(2)))
        lid = self.con.execute("SELECT MAX(id) FROM loops").fetchone()[0]
        entities.link(self.con, log=lambda *_: None)
        seen = {}

        def model(prompt):
            seen["prompt"] = prompt
            return json.dumps({"situation": f"Reese asked you to confirm the ORC dates [E{mid}] [L{lid}] [E999].",
                               "raise": [{"text": "Confirm the dates", "refs": [f"L{lid}"]}, {"text": "Made up", "refs": ["Q1"]}]})
        with tempfile.TemporaryDirectory() as d, mock.patch.object(person_summary, "JOB_DIR", Path(d)), \
                mock.patch("assist.remember.block", return_value=""):
            rec = person_summary.write_now(self.con, 2, run_model=model)
            self.assertIn("<context>", seen["prompt"])                       # mail is inside the untrusted block
            self.assertIn(f"[L{lid}]", seen["prompt"])
            s = rec["summary"]
            self.assertNotIn("[E999]", s["situation"])                        # a reference the pack does not hold is removed
            self.assertEqual([x["text"] for x in s["raise"]], ["Confirm the dates"])   # a point left with none is dropped
            self.assertEqual(set(rec["refs"]), {f"E{mid}", f"L{lid}"})
            self.assertEqual(rec["refs"][f"E{mid}"]["url"], f"#/mail?open={mid}")
            person_summary.JOBS.write_file(person_summary._latest_path(2), rec)
            st = person_summary.state(self.con, 2)
            self.assertEqual(st["summary"]["summary"], s)
            self.assertFalse(st["newer"])
            self.con.execute("UPDATE loops SET updated_at=? WHERE id=?", ("2999-01-01T00:00:00Z", lid))   # something changed since
            self.assertTrue(person_summary.state(self.con, 2)["newer"])


if __name__ == "__main__":
    unittest.main()
