"""Document folders (assist/documents.py): Sam's move wins over the card and the filing pass; the emery yates is never filed.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from pathlib import Path

from assist import db, documents


class Folders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        c.executemany("INSERT INTO initiatives (slug, name, weight) VALUES (?,?,?)", [("pricing", "Pricing", 4), ("plt", "PLT", 5)])
        c.commit()

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def docs(self):
        return [{"id": "lf-1", "origin": "local", "ext": "pptx", "card": {"initiatives": ["plt"], "kind": "deck", "sensitivity": "normal"}},
                {"id": "lf-2", "origin": "local", "ext": "xlsx", "card": None},
                {"id": "sp-3", "origin": "sharepoint", "ext": "docx", "card": None},
                {"id": "kb-4", "origin": "kb", "ext": "md", "card": None}]

    def test_order_of_authority(self):
        self.con.execute("INSERT INTO doc_folders (doc_id, initiatives, kind, sensitivity, by, filed_at) VALUES "
                         "('lf-2', '[\"pricing\"]', 'spreadsheet', 'normal', 'claude', 'x'), ('lf-1', '[\"pricing\"]', 'deck', 'normal', 'claude', 'x')")
        f = {d["id"]: d["folder"] for d in documents.folders(self.con, self.docs())}
        self.assertEqual((f["lf-1"]["initiatives"], f["lf-1"]["by"]), (["plt"], "card"))          # the card beats the filing pass
        self.assertEqual((f["lf-2"]["initiatives"], f["lf-2"]["by"]), (["pricing"], "claude"))
        self.assertEqual((f["sp-3"]["initiatives"], f["sp-3"]["kind"], f["sp-3"]["by"]), ([], "other", "links"))   # unfiled: to file
        self.assertEqual(f["kb-4"]["by"], "kb")
        self.assertEqual([d["id"] for d in documents.to_file(self.con, documents.folders(self.con, self.docs()))], ["sp-3"])

    def test_sams_move_wins_and_survives_refiling(self):
        documents.move(self.con, "lf-1", ["pricing", "not-an-initiative"])
        self.con.execute("UPDATE doc_folders SET initiatives='[\"plt\"]' WHERE doc_id='lf-1' AND by != 'sam'")   # what a refiling pass may do
        f = {d["id"]: d["folder"] for d in documents.folders(self.con, self.docs())}
        self.assertEqual((f["lf-1"]["initiatives"], f["lf-1"]["kind"], f["lf-1"]["by"]), (["pricing"], "deck", "sam"))
        documents.move(self.con, "lf-1", [])
        f = {d["id"]: d["folder"] for d in documents.folders(self.con, self.docs())}
        self.assertEqual(f["lf-1"]["initiatives"], [])   # "No initiative" is a choice too


if __name__ == "__main__":
    unittest.main()
