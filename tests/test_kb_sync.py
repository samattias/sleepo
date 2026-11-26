"""The emery yates and product docs, read through the connector and built in code (assist/kb_sync.py; Sam, 17 Nov 2026:
"Update the emery yates, the product docs, and Salesforce too"). Temp database; nothing runs Claude."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assist import db, kb_sync, pull_hook

KB = {"repo": "kb", "source": "acme-kb", "section": "Emery Yates", "doc_prefix": "kb/"}
PD = {"repo": "docs", "source": "public-docs", "section": "Product docs", "doc_prefix": "pd/"}
NOW = "2026-11-17T10:00:00Z"


def note(repo, path, content):
    return {"repo": repo, "path": path, "url": f"https://kb.example.com/{path[:-3]}", "content": content}


def listing(repo, paths):
    return {"tool": "igxkb_list", "input": {"repo": repo}, "objs": [{"repo": repo, "count": len(paths), "paths": paths}], "raw": []}


def read(n):
    return {"tool": "igxkb_read_note", "input": {"repo": n["repo"], "path": n["path"]}, "objs": [n], "raw": []}


class Records(unittest.TestCase):
    def test_a_note_becomes_an_item_and_a_document(self):
        n = note("kb", "Sales/people/Ann Noel.md", "---\ndate: 2026-06-28\ndescription: Head of sales.\ntags:\n  - kb\n---\n\n# Ann Noel\n\nRuns sales.")
        item, doc = kb_sync.record(KB, n, NOW)
        self.assertEqual((item["subject"], item["from_name"], item["ts"]), ("Ann Noel", "Sales", "2026-06-28T00:00:00Z"))
        self.assertEqual(item["text"], "Head of sales.\n\n# Ann Noel\n\nRuns sales.")
        self.assertEqual(item["payload"]["frontmatter"], {"date": "2026-06-28", "description": "Head of sales.", "tags": ["kb"]})
        self.assertEqual((doc["id"], doc["section"], doc["path"]), ("kb/Sales/people/Ann Noel.md", "Emery Yates", "kb/Sales/people/Ann Noel.md"))

    def test_product_docs_take_their_section_from_the_folder_under_docs(self):
        item, doc = kb_sync.record(PD, note("docs", "docs/desktop-client/about.md", "---\ntitle: About the client\n---\nBody."), NOW)
        self.assertEqual((item["from_name"], item["subject"], item["ts"]), ("Harper Lawson", "About the client", NOW))
        self.assertTrue(doc["body_md"].startswith("# About the client\n\nBody."))

    def test_include_fragments_and_other_files_are_not_read(self):
        self.assertEqual(kb_sync.to_read(["a.md", "docs/_shared/_x.md", "docs/b.mdx", "img.png"]), ["a.md", "docs/b.mdx"])


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        for s in ("acme-kb", "public-docs"):
            self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES (?, ?, ?)", (s, s, s))
        same = note("kb", "Same.md", "# Same\n\nNo change.")
        it, _ = kb_sync.record(KB, same, NOW)
        db.upsert_item(self.con, "acme-kb", "Same.md", "doc", "2026-06-01T00:00:00Z", text=it["text"])
        db.upsert_item(self.con, "acme-kb", "Edited.md", "doc", "2026-06-01T00:00:00Z", text="old text")
        db.upsert_item(self.con, "acme-kb", "Gone.md", "doc", "2026-06-01T00:00:00Z", text="gone")
        self.con.commit()
        self.notes = [same, note("kb", "Edited.md", "# Edited\n\nNew text."), note("kb", "New.md", "# New\n\nHello.")]

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def built(self, reads):
        calls = [listing("kb", ["Same.md", "Edited.md", "New.md"])] + [read(n) for n in reads]
        return kb_sync.build([KB], kb_sync.listed(calls), calls, self.con, NOW)["kb"]

    def test_only_new_and_changed_notes_are_written_and_missing_ones_removed(self):
        b = self.built(self.notes)
        self.assertEqual([i["external_id"] for i in b["items"]], ["Edited.md", "New.md"])
        self.assertEqual((b["unchanged"], b["gone"], b["failed"]), (1, ["Gone.md"], []))
        edited = b["items"][0]
        self.assertEqual(edited["ts"], "2026-06-01T00:00:00Z")   # the first sync keeps the date a note had
        self.assertIn("listed, 3 read", kb_sync.note(b))

    def test_after_the_first_sync_a_changed_note_is_dated_now(self):
        pid = db.start_pull(self.con, "acme-kb", kb_sync.AGENT)
        db.finish_pull(self.con, pid, 3, 3, 0, 1)
        self.assertEqual(self.built(self.notes)["items"][0]["ts"], NOW)

    def test_nothing_is_removed_when_a_note_could_not_be_read(self):
        b = self.built(self.notes[:2])
        self.assertEqual((b["failed"], b["gone"]), (["New.md"], []))

    def test_remove_takes_the_item_and_its_document(self):
        db.upsert_document(self.con, "kb/Gone.md", "Emery Yates", "Gone", "x")
        kb_sync.remove(self.con, "acme-kb", ["Gone.md"], "kb/")
        self.assertIsNone(self.con.execute("SELECT 1 FROM items WHERE external_id='Gone.md'").fetchone())
        self.assertIsNone(self.con.execute("SELECT 1 FROM documents WHERE id='kb/Gone.md'").fetchone())


class Hook(unittest.TestCase):
    def test_a_note_read_reaches_the_model_as_one_line_and_is_kept_in_full(self):
        n = note("kb", "A.md", "# A\n\n" + "x" * 500)
        ev = {"tool_name": "mcp__claude_ai_Mind__igxkb_read_note", "tool_input": {"repo": "kb", "path": "A.md"},
              "tool_response": [{"type": "text", "text": json.dumps(n)}]}
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([sys.executable, pull_hook.__file__], input=json.dumps(ev), capture_output=True, text=True,
                               env=dict(os.environ, ASSIST_CAPTURE=d))
            self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"], "Kept by SleePO: A.md, 505 characters.")
            calls = pull_hook.load(d)
        self.assertEqual(calls[0]["tool"], "igxkb_read_note")
        self.assertEqual(calls[0]["objs"][0]["content"], n["content"])

    def test_a_listing_reaches_the_model_unchanged(self):
        self.assertIsNone(pull_hook.brief("mcp__x__igxkb_list", [{"repo": "kb", "paths": ["a.md"]}]))


if __name__ == "__main__":
    unittest.main()
