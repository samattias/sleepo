"""The SharePoint & OneDrive index built in code from the connector's search results (assist/sp_index.py; Sam, 17 Nov 2026:
"Update SharePoint and Drive: It was last synced 42 days ago"). Temp database; nothing runs Claude."""
import json
import tempfile
import unittest
from pathlib import Path

from assist import db, profile, sp_index


def hit(fid, name, path, modified="2026-11-10T09:00:00.000Z", summary="Some <c0>PLT</c0> text<ddd/>"):
    url = f"https://example.sharepoint.com{path}/{name}"
    return {"uri": f"file:///drive-1/{fid}", "driveId": "drive-1", "id": fid, "name": name, "webUrl": url,
            "summary": summary, "content": summary, "lastModifiedDateTime": modified}


def call(query, objs, more=None, total=None, author=None, ft=None):
    meta = [{"moreResults": True, "nextOffset": more, "totalResultCount": total}] if more is not None else (
        [{"totalResultCount": total}] if total is not None else [])
    inp = {"query": query, "afterDateTime": "2026-11-01", "limit": 50, "offset": 0}
    if author:
        inp["author"] = author
    if ft:
        inp["fileType"] = ft
    return {"tool": "sharepoint_search", "input": inp, "objs": objs + meta, "raw": []}


class Terms(unittest.TestCase):
    def test_plain_words_from_a_filing_pattern(self):
        self.assertEqual(sp_index.terms(r"\bAPF\b|\bICE ?9\b|Nova|agentic (?:process )?foundation|\bK8S\b"),
                         ["PLT", "NOVA", "Nova", "agentic foundation", "K8S"])
        self.assertEqual(sp_index.terms(r"contoso-?mart|Rule of (?:30|40)|\bSKUs?\b|\bPIA\b\+?|\bPeer\+|HR|[A-Z]{3}"),
                         ["contoso", "Rule of 30", "SKUs", "COPILOT"])

    def test_query_quotes_phrases_and_drops_repeats(self):
        self.assertEqual(sp_index.kql(["PLT", "NOVA", "Copilot", "COPILOT", "design partnership", "M&A"]),
                         'PLT OR "NOVA" OR Copilot OR "design partnership" OR "M&A"')


class Index(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(self.con)
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('sharepoint', 'sharepoint', 'SharePoint & OneDrive')")
        profile.use({**profile.DEFAULTS, "full_name": "Ann Noel", "first_name": "Ann", "emails": ["ann.lee@example.com"]})
        self.con.execute("INSERT INTO people(id, name) VALUES (1, 'Bob Stone'), (2, 'Reese Ito')")
        self.con.execute("INSERT INTO people_aliases(alias, person_id) VALUES ('bob.stone@example.com', 1)")
        self.con.execute("INSERT INTO initiatives(slug, name, weight, match_regex, active) VALUES "
                         "('plt', 'PLT', 5, '\\bAPF\\b|Reese|Project Delta', 1), ('old', 'Old', 3, 'old', 0)")
        self.con.commit()

    def tearDown(self):
        profile.use(None)
        self.con.close()
        self.tmp.cleanup()

    def test_searches_by_bet_without_first_names_and_the_users_own_files(self):
        s = sp_index.searches(self.con)
        self.assertEqual(s[0], {"label": "PLT", "input": {"query": sp_index.typed('PLT OR "Project Delta"')}})
        self.assertTrue(s[0]["input"]["query"].startswith('(PLT OR "Project Delta") AND (filetype:pptx OR filetype:docx'))
        self.assertNotIn("Old", [x["label"] for x in s])
        self.assertEqual(s[-1], {"label": "Your own files", "input": {"query": sp_index.typed("*"), "author": "Ann Noel"}})
        self.assertTrue(s[-1]["input"]["query"].startswith("filetype:pptx OR "))

    def test_starts_a_day_before_the_last_index(self):
        self.assertRegex(sp_index.since(self.con), r"^\d{4}-\d\d-\d\dT")   # none yet: FIRST_DAYS back
        pid = db.start_pull(self.con, "sharepoint", "claude-code:sharepoint-index", "2026-07-01T00:00:00Z", "2026-10-06T11:06:03Z")
        db.finish_pull(self.con, pid, 10, 10, 0, 0)
        self.assertEqual(sp_index.since(self.con), "2026-10-05T11:06:03Z")

    def test_builds_items_in_code_and_leaves_out_what_does_not_belong(self):
        db.upsert_item(self.con, "sharepoint", "same", "doc", "2026-11-10T09:00:00Z", subject="Same.pptx", text="x" * 900,
                       url="https://example.sharepoint.com/sites/a/Same.pptx?web=1")
        db.upsert_item(self.con, "sharepoint", "older", "doc", "2026-10-01T09:00:00Z", subject="Older.docx", text="x" * 900,
                       url="https://example.sharepoint.com/sites/a/Older.docx?web=1")
        calls = [
            call('PLT OR "Project Delta"', [
                hit("new", "PLT plan.pptx", "/personal/bob_stone_example_com/Documents/Plans"),
                hit("same", "Same.pptx", "/sites/a/Shared Documents"),
                hit("older", "Older.docx", "/sites/a/Shared Documents"),
                hit("img", "photo.png", "/sites/a/Shared Documents"),
                hit("own", "notes.md", "/personal/ann_lee_example_com/Documents/Assist/memory"),
                hit("hr", "Salary review 2027.xlsx", "/sites/a/Shared Documents"),
            ], more=50, total=120),
            call('PLT OR "Project Delta"', [hit("new", "PLT plan.pptx", "/personal/bob_stone_example_com/Documents/Plans")], total=120),
            call("*", [hit("mine", "Budget.xlsx", "/personal/ann_lee_example_com/Documents")], author="Ann Noel", ft="xlsx"),
            call("*", [hit("deck", "Deck.pptx", "/personal/ann_lee_example_com/Documents")], author="Ann Noel", ft="pptx", more=50, total=80),
            call("*", [hit("readme", "README.md", "/personal/ann_lee_example_com/Documents/Code/app/node_modules/x")], author="Ann Noel", ft="xlsx"),
        ]
        b = sp_index.build(calls, self.con, {'PLT OR "Project Delta"': "PLT", "* · author Ann Noel · fileType xlsx": "Your own files (xlsx)"})
        got = {i["external_id"]: i for i in b["items"]}
        self.assertEqual(set(got), {"new", "older", "mine", "deck"})
        new = got["new"]
        self.assertEqual((new["subject"], new["from_name"], new["thread"]), ("PLT plan.pptx", "Bob Stone", "/personal/bob_stone_example_com/Documents/Plans"))
        self.assertEqual(new["text"], "Some PLT text")
        self.assertEqual(new["payload"]["uri"], "file:///drive-1/new")
        self.assertLess(len(new["text"]), 400)   # a snippet: /docs-read still reads the file in full
        self.assertNotIn("url", got["older"])     # a file already held keeps its own link
        self.assertEqual(b["unchanged"], 1)
        self.assertEqual(b["skipped"], {"not a document": 1, "own": 1, "private": 1, "code": 1})
        s = b["searches"]
        self.assertEqual((s['PLT OR "Project Delta"']["pages"], s['PLT OR "Project Delta"']["total"], s['PLT OR "Project Delta"']["done"]), (2, 120, True))
        self.assertEqual((s["* · author Ann Noel · fileType xlsx"]["pages"], s["* · author Ann Noel · fileType xlsx"]["done"]), (2, True))
        self.assertFalse(s["* · author Ann Noel · fileType pptx"]["done"])   # its own search: one more page to read
        self.assertIn("left out 1 code, 1 not a document, 1 own, 1 private", sp_index.note(b, "2026-11-01T00:00:00Z"))

    def test_a_search_stopped_at_its_page_cap_is_not_complete(self):
        calls = [call("PLT", [hit(f"f{i}", f"F{i}.pdf", "/sites/a/Docs")], more=50 * (i + 1), total=900) for i in range(sp_index.PAGES)]
        b = sp_index.build(calls, self.con, {"PLT": "PLT"})
        self.assertFalse(b["searches"]["PLT"]["done"])
        self.assertIn(f"capped at {sp_index.PAGES * sp_index.LIMIT}: PLT", sp_index.note(b, "2026-11-01T00:00:00Z"))

    def test_an_error_is_reported_not_taken_for_an_empty_page(self):
        b = sp_index.build([{"tool": "sharepoint_search", "input": {"query": "PLT"}, "objs": [], "raw": ["Authentication required"]}],
                           self.con, {"PLT": "PLT"})
        self.assertEqual(b["errors"], ["PLT: Authentication required"])
        self.assertFalse(b["searches"]["PLT"]["done"])

    def test_prune_removes_code_and_own_folders_only(self):
        keep = db.upsert_item(self.con, "sharepoint", "k", "doc", "2026-11-10T09:00:00Z", subject="Plan.pptx", thread="/sites/a/Shared Documents")[0]
        code = db.upsert_item(self.con, "sharepoint", "c", "doc", "2026-11-10T09:00:00Z", subject="README.md",
                              thread="/personal/ann_lee_example_com/Documents/Code/app/node_modules/semver")[0]
        own = db.upsert_item(self.con, "sharepoint", "o", "doc", "2026-11-10T09:00:00Z", subject="x.md",
                             thread="/personal/ann_lee_example_com/Documents/Documents/Assist/memory")[0]
        self.con.execute("INSERT INTO doc_folders(doc_id, initiatives, by, filed_at) VALUES (?, '[]', 'claude', 'now')", (f"sp-{code}",))
        self.assertEqual(sp_index.prune(self.con), 2)
        left = {r[0] for r in self.con.execute("SELECT id FROM items WHERE source_id='sharepoint'")}
        self.assertEqual(left, {keep})
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM doc_folders").fetchone()[0], 0)
        self.assertEqual(sp_index.prune(self.con), 0)


class Hook(unittest.TestCase):
    def run_hook(self, response, folder):
        import os, subprocess, sys
        ev = {"tool_name": sp_index.TOOL, "tool_input": {"query": "PLT", "offset": 0}, "tool_response": response}
        p = subprocess.run([sys.executable, str(Path(sp_index.__file__).with_name("pull_hook.py"))], input=json.dumps(ev),
                           capture_output=True, text=True, env=dict(os.environ, ASSIST_CAPTURE=str(folder)))
        return json.loads(p.stdout) if p.stdout.strip() else None

    def test_keeps_every_result_and_shows_the_model_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            page = [{"type": "text", "text": json.dumps(hit("a", "A.pptx", "/sites/a")) + json.dumps(hit("b", "B.pptx", "/sites/a"))
                     + json.dumps({"moreResults": True, "nextOffset": 2, "totalResultCount": 9})}]
            out = self.run_hook(page, d)
            self.assertEqual(out["hookSpecificOutput"]["updatedToolOutput"],
                             "Kept by SleePO: 2 results on this page. nextOffset 2; totalResultCount 9.")
            calls = sp_index._load(d)
            self.assertEqual([o["id"] for o in calls[0]["objs"] if o.get("id")], ["a", "b"])
            self.assertEqual(calls[0]["input"], {"query": "PLT", "offset": 0})

    def test_an_error_reaches_the_model_as_it_is_and_is_kept_for_the_note(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(self.run_hook("Error: authentication required", d))
            self.assertEqual(sp_index._load(d)[0]["raw"], ["Error: authentication required"])
        from assist import pull_hook
        self.assertEqual(pull_hook.brief(sp_index.TOOL, pull_hook.objs([json.dumps(hit("a", "A.pptx", "/sites/a"))])),
                         "Kept by SleePO: 1 results on this page. No nextOffset: this was the last page.")


if __name__ == "__main__":
    unittest.main()
