"""Steps on the Mac that Ask SleePO asks to do and the user allows first (assist/desktop.py). Everything runs in a temporary
home folder and job folder: nothing here touches the real Downloads, OneDrive or jobs/."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from assist import claude_open, desktop

HOSTS = {"contoso.sharepoint.com", "contoso-my.sharepoint.com"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.home = root / "home"
        for d in ("Downloads", "Desktop", "Documents", "Library/CloudStorage/OneDrive-Contoso/Board", "Library/Keychains",
                  ".ssh", "SleePO Workspace/2026-11-23 chat data room"):
            (self.home / d).mkdir(parents=True)
        self.ws = self.home / "SleePO Workspace" / "2026-11-23 chat data room"
        self.od = self.home / "Library/CloudStorage/OneDrive-Contoso/Board"
        (self.ws / "Deck.pptx").write_bytes(b"deck")
        (self.ws / "Inventory.xlsx").write_bytes(b"inv")
        (self.od / "Board deck.pptx").write_bytes(b"board")
        self.patches = [mock.patch.object(desktop, "HOME", self.home), mock.patch.object(desktop, "JOB_DIR", root / "jobs"),
                        mock.patch.object(desktop, "POLL", 0.02), mock.patch.object(desktop, "BEAT", 0.05),
                        mock.patch.object(desktop, "OPENER", lambda target: self.opened.append(target))]
        self.opened = []
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def plan(self, *steps):
        return {"why": "Data room", "steps": list(steps)}

    def request(self, *steps, run="r1"):
        st, err = desktop.prepare(self.plan(*steps), self.ws, HOSTS)
        self.assertEqual(err, [])
        req = {"id": "d" + os.urandom(6).hex(), "thread": "t1", "run": run, "created_at": desktop._now(), "beat": time.time(),
               "why": "Data room", "status": "pending", "steps": st}
        desktop._write(req)
        return req

    def answer_later(self, rid, approve=True, steps=None, after=0.1):
        def go():
            time.sleep(after)
            desktop.decide(rid, approve, steps)
        t = threading.Thread(target=go)
        t.start()
        return t


class Where(Base):
    def test_only_inside_home_and_never_library_hidden_or_home_itself(self):
        for bad in ("/etc/hosts", "relative/path.txt", str(self.home / "Library/Keychains"), str(self.home / ".ssh"),
                    str(self.home), str(self.home / "Downloads/../../outside")):
            with self.assertRaises(ValueError, msg=bad):
                desktop.check(bad, must_exist=False)
        self.assertEqual(desktop.check(str(self.od / "Board deck.pptx")), self.od / "Board deck.pptx")   # OneDrive can be read
        self.assertTrue(desktop.onedrive(self.od / "Board deck.pptx"))
        self.assertFalse(desktop.onedrive(self.home / "Downloads"))

    def test_sleepo_own_folders_are_refused(self):
        with mock.patch.object(desktop, "_protected", lambda: [self.home / "Documents"]):
            with self.assertRaises(ValueError):
                desktop.check(str(self.home / "Documents" / "x.txt"), must_exist=False)

    def test_plain_words(self):
        self.assertEqual(desktop.where(self.home / "Downloads" / "Data room", self.ws), "Downloads › Data room")
        self.assertEqual(desktop.where(self.od, self.ws), "OneDrive › Board")
        self.assertEqual(desktop.where(self.ws / "Deck.pptx", self.ws), "this conversation's folder › Deck.pptx")


class Plans(Base):
    def test_folder_then_copy_is_a_valid_plan(self):
        dest = "~/Downloads/Data room 6.2"
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            st, err = desktop.prepare(self.plan({"do": "folder", "path": str(self.home / "Downloads/Data room 6.2")},
                                                {"do": "copy", "from": [str(self.ws / "Deck.pptx"), str(self.od / "Board deck.pptx")],
                                                 "to": str(self.home / "Downloads/Data room 6.2")}), self.ws, HOSTS)
        self.assertEqual(err, [], dest)
        self.assertEqual(st[0]["label"], "Make the folder “Data room 6.2” in Downloads")
        self.assertEqual(st[1]["label"], "Copy 2 files into Downloads › Data room 6.2")
        self.assertIn("Board deck.pptx · from OneDrive › Board", st[1]["detail"])

    def test_copy_into_a_missing_folder_needs_a_folder_step(self):
        _, err = desktop.prepare(self.plan({"do": "copy", "from": [str(self.ws / "Deck.pptx")], "to": str(self.home / "Downloads/New")}),
                                 self.ws, HOSTS)
        self.assertIn("does not exist", err[0])

    def test_onedrive_files_are_copied_never_moved_renamed_or_trashed(self):
        f = str(self.od / "Board deck.pptx")
        for step in ({"do": "move", "from": [f], "to": str(self.home / "Downloads")}, {"do": "rename", "path": f, "name": "x.pptx"},
                     {"do": "trash", "path": [f]}):
            _, err = desktop.prepare(self.plan(step), self.ws, HOSTS)
            self.assertTrue(err and "OneDrive" in err[0], step)

    def test_copy_into_onedrive_warns_that_it_uploads(self):
        st, err = desktop.prepare(self.plan({"do": "copy", "from": [str(self.ws / "Deck.pptx")], "to": str(self.od)}), self.ws, HOSTS)
        self.assertEqual(err, [])
        self.assertIn("SharePoint", st[0]["warn"])

    def test_never_opens_apps_or_scripts(self):
        for name in ("Installer.pkg", "run.command", "evil.app", "go.sh"):
            (self.home / "Downloads" / name).write_text("x")
            _, err = desktop.prepare(self.plan({"do": "open", "path": str(self.home / "Downloads" / name)}), self.ws, HOSTS)
            self.assertTrue(err, name)
        _, err = desktop.prepare(self.plan({"do": "open", "path": str(self.ws / "Deck.pptx")}), self.ws, HOSTS)
        self.assertEqual(err, [])

    def test_links_open_only_over_https_and_outside_ones_are_flagged(self):
        _, err = desktop.prepare(self.plan({"do": "open", "url": "http://example.com"}), self.ws, HOSTS)
        self.assertTrue(err)
        st, err = desktop.prepare(self.plan({"do": "open", "url": "https://example.com/x"}), self.ws, HOSTS)
        self.assertEqual(err, [])
        self.assertIn("outside", st[0]["warn"])

    def test_unknown_step_and_bad_json(self):
        _, err = desktop.prepare(self.plan({"do": "format_disk"}), self.ws, HOSTS)
        self.assertIn("not a step", err[0])
        _, err = desktop.prepare("{not json", self.ws, HOSTS)
        self.assertIn("JSON", err[0])


class Links(unittest.TestCase):
    def test_download_addresses(self):
        u = desktop.download_url("https://contoso-my.sharepoint.com/:v:/g/personal/kim_contoso_com/EaBc123?e=xyz", HOSTS)
        self.assertEqual(u, "https://contoso-my.sharepoint.com/:v:/g/personal/kim_contoso_com/EaBc123?e=xyz&download=1")
        u = desktop.download_url("https://contoso.sharepoint.com/sites/PLT/Shared%20Documents/Demos/Demo%201.mp4", HOSTS)
        self.assertEqual(u, "https://contoso.sharepoint.com/sites/PLT/_layouts/15/download.aspx?SourceUrl=/sites/PLT/Shared%20Documents/Demos/Demo%201.mp4")
        u = desktop.download_url("https://contoso.sharepoint.com/sites/PLT/_layouts/15/Doc.aspx?sourcedoc=%7B1B2C3D4E-0000-1111-2222-333344445555%7D&file=Deck.pptx", HOSTS)
        self.assertEqual(u, "https://contoso.sharepoint.com/sites/PLT/_layouts/15/download.aspx?UniqueId=1B2C3D4E-0000-1111-2222-333344445555")
        u = desktop.download_url("https://contoso-my.sharepoint.com/personal/kim_contoso_com/_layouts/15/stream.aspx?id=%2Fpersonal%2Fkim_contoso_com%2FDocuments%2FDemo.mp4", HOSTS)
        self.assertEqual(u, "https://contoso-my.sharepoint.com/personal/kim_contoso_com/_layouts/15/download.aspx?SourceUrl=/personal/kim_contoso_com/Documents/Demo.mp4")
        self.assertEqual(desktop.link_name("https://contoso.sharepoint.com/sites/PLT/Shared%20Documents/Demo%201.mp4"), "Demo 1.mp4")

    def test_refused_links(self):
        for bad in ("https://contoso-my.sharepoint.com/:f:/g/personal/parker/EaFolder", "https://evil.sharepoint.com/sites/x/a.pptx",
                    "http://contoso.sharepoint.com/sites/x/a.pptx", "https://contoso.sharepoint.com/sites/PLT/Shared%20Documents/Demos",
                    "https://contoso.sharepoint.com/sites/PLT/SitePages/Home.aspx"):
            with self.assertRaises(ValueError, msg=bad):
                desktop.download_url(bad, HOSTS)


class Gate(Base):
    def test_nothing_happens_until_allowed_then_only_the_ticked_steps(self):
        dl = self.home / "Downloads"
        (dl / "Deck.pptx").write_bytes(b"older")   # already there: the copy becomes "Deck 2.pptx"
        req = self.request({"do": "copy", "from": [str(self.ws / "Deck.pptx")], "to": str(dl)},
                           {"do": "copy", "from": [str(self.ws / "Inventory.xlsx")], "to": str(dl)})
        self.assertFalse((dl / "Deck 2.pptx").exists())
        t = self.answer_later(req["id"], True, [0])
        out = desktop.run_request(req, self.ws, wait=5)
        t.join()
        self.assertEqual(out["status"], "done")
        self.assertEqual((dl / "Deck 2.pptx").read_bytes(), b"deck")
        self.assertEqual((dl / "Deck.pptx").read_bytes(), b"older")       # nothing overwritten
        self.assertFalse((dl / "Inventory.xlsx").exists())                 # left unticked
        self.assertEqual([s["state"] for s in out["steps"]], ["done", "skipped"])
        text = desktop.report(out)
        self.assertIn("✓ Copy “Deck.pptx” into Downloads", text)
        self.assertIn("– Copy “Inventory.xlsx”", text)
        self.assertIn("left out", text)
        self.assertEqual(desktop.get(req["id"])["answer"]["steps"], [0])

    def test_declined_does_nothing(self):
        req = self.request({"do": "folder", "path": str(self.home / "Desktop/New")})
        t = self.answer_later(req["id"], False)
        out = desktop.run_request(req, self.ws, wait=5)
        t.join()
        self.assertEqual(out["status"], "declined")
        self.assertFalse((self.home / "Desktop/New").exists())
        self.assertIn("declined", desktop.report(out))

    def test_unanswered_expires_and_cannot_be_allowed_after(self):
        req = self.request({"do": "folder", "path": str(self.home / "Desktop/New")})
        out = desktop.run_request(req, self.ws, wait=0.1)
        self.assertEqual(out["status"], "expired")
        with self.assertRaises(ValueError):
            desktop.decide(req["id"], True)
        self.assertFalse((self.home / "Desktop/New").exists())

    def test_a_stopped_turn_stops_its_request(self):
        req = self.request({"do": "folder", "path": str(self.home / "Desktop/New")}, run="run-9")
        threading.Timer(0.1, lambda: desktop.stop_run("run-9")).start()
        out = desktop.run_request(req, self.ws, wait=5)
        self.assertEqual(out["status"], "stopped")
        self.assertFalse((self.home / "Desktop/New").exists())

    def test_answered_once(self):
        req = self.request({"do": "folder", "path": str(self.home / "Desktop/New")})
        desktop.decide(req["id"], False)
        with self.assertRaises(ValueError):
            desktop.decide(req["id"], True)
        with self.assertRaises(ValueError):
            desktop.decide(req["id"], True, [])

    def test_a_request_whose_process_is_gone_reads_as_expired(self):
        req = self.request({"do": "folder", "path": str(self.home / "Desktop/New")})
        req["beat"] = time.time() - 3600
        desktop._write(req)
        got = desktop.get(req["id"])
        self.assertEqual((got["status"], got["lost"]), ("expired", True))
        self.assertEqual([r["id"] for r in desktop.for_thread("t1")], [req["id"]])

    def test_trash_and_rename_outside_onedrive(self):
        (self.home / "Desktop" / "old.txt").write_text("x")
        (self.home / "Desktop" / "name.txt").write_text("y")
        req = self.request({"do": "trash", "path": [str(self.home / "Desktop/old.txt")]},
                           {"do": "rename", "path": str(self.home / "Desktop/name.txt"), "name": "new name.txt"})
        t = self.answer_later(req["id"])
        out = desktop.run_request(req, self.ws, wait=5)
        t.join()
        self.assertEqual([s["state"] for s in out["steps"]], ["done", "done"])
        self.assertTrue((self.home / ".Trash" / "old.txt").exists())
        self.assertTrue((self.home / "Desktop" / "new name.txt").exists())


class Download(Base):
    def test_the_browser_downloads_it_and_it_is_moved_into_place(self):
        dl = self.home / "Downloads"

        def browser(target):   # what Chrome does: a partial file, then the file
            self.opened.append(target)

            def go():
                (dl / "Demo.mp4.crdownload").write_bytes(b"12")
                time.sleep(0.15)
                (dl / "Demo.mp4.crdownload").rename(dl / "Demo.mp4")
            threading.Thread(target=go).start()

        (self.home / "Desktop" / "Room").mkdir()
        req = self.request({"do": "download", "url": "https://contoso.sharepoint.com/sites/PLT/Shared%20Documents/Demo.mp4",
                            "to": str(self.home / "Desktop/Room")})
        with mock.patch.object(desktop, "OPENER", browser):
            t = self.answer_later(req["id"])
            out = desktop.run_request(req, self.ws, wait=5)
            t.join()
        self.assertEqual(out["steps"][0]["state"], "done", out["steps"][0].get("error"))
        self.assertIn("download.aspx?SourceUrl=", self.opened[0])
        self.assertEqual((self.home / "Desktop/Room/Demo.mp4").read_bytes(), b"12")
        self.assertFalse((dl / "Demo.mp4").exists())

    def test_nothing_arrives(self):
        req = self.request({"do": "download", "url": "https://contoso.sharepoint.com/sites/PLT/Shared%20Documents/Demo.mp4"})
        with mock.patch.object(desktop, "DL_START", 0.3):
            t = self.answer_later(req["id"])
            out = desktop.run_request(req, self.ws, wait=5)
            t.join()
        self.assertEqual(out["steps"][0]["state"], "failed")
        self.assertIn("nothing arrived", out["steps"][0]["error"])
        self.assertIn("✗", desktop.report(out))


class Ask(Base):
    def test_ask_do_from_the_chat_with_a_plan_file(self):
        (self.ws / ".plan.json").write_text(json.dumps(self.plan({"do": "folder", "path": str(self.home / "Downloads/Data room")})))
        env = {"ASSIST_CHAT_THREAD": "t1", "ASSIST_CHAT_RUN": "r1"}
        result = {}
        with mock.patch.object(claude_open, "WORKSPACE", self.home / "SleePO Workspace"), \
                mock.patch.dict(os.environ, {"ASSIST_CHAT_WORKSPACE": str(self.ws)}), \
                mock.patch.object(desktop, "tenant_hosts", lambda: HOSTS):
            t = threading.Thread(target=lambda: result.update(out=desktop.ask(".plan.json", env)))
            t.start()
            for _ in range(100):
                ids = desktop.ids_for_run("r1")
                if ids:
                    break
                time.sleep(0.02)
            self.assertEqual(desktop.get(ids[0])["status"], "pending")
            self.assertFalse((self.home / "Downloads/Data room").exists())
            desktop.decide(ids[0], True)
            t.join(5)
        text, code = result["out"]
        self.assertEqual(code, 0)
        self.assertIn("✓ Make the folder", text)
        self.assertTrue((self.home / "Downloads/Data room").is_dir())

    def test_refused_outside_a_conversation_or_with_a_bad_plan(self):
        self.assertEqual(desktop.ask('{"steps": []}', {})[1], 1)
        with mock.patch.object(claude_open, "WORKSPACE", self.home / "SleePO Workspace"), \
                mock.patch.dict(os.environ, {"ASSIST_CHAT_WORKSPACE": str(self.ws)}), \
                mock.patch.object(desktop, "tenant_hosts", lambda: HOSTS):
            text, code = desktop.ask(json.dumps(self.plan({"do": "copy", "from": ["/etc/hosts"], "to": "~/Downloads"})),
                                     {"ASSIST_CHAT_THREAD": "t1"})
            self.assertEqual(code, 1)
            self.assertIn("outside your home folder", text)
            text, code = desktop.ask("/etc/passwd", {"ASSIST_CHAT_THREAD": "t1"})   # a plan file outside the workspace
            self.assertEqual(code, 1)
        self.assertEqual(desktop.for_thread("t1"), [])


class SharePointLookup(unittest.TestCase):
    """ask-sharepoint (assist/sp_index.py): the arguments, and a folder's listing read into links. No connector is called."""
    def test_arguments(self):
        from assist import sp_index
        self.assertEqual(sp_index.parse_args(["demo", "--type", "pptx", "--in", "Demos", "--author", "Parker Barker"]),
                         ("demo", {"fileType": "pptx", "folderName": "Demos", "author": "Parker Barker"}))
        self.assertEqual(sp_index.parse_args(["--folder", "Demo_Recordings"]), ("", {"folder": "Demo_Recordings"}))

    def test_a_folder_listing_becomes_files_with_their_links(self):
        from assist import sp_index
        listing = ("Outline.docx (file, 1446132 bytes) file:///b!abc-DEF_1/01XLXYLJY5OU4EDAL7L5CYKSPATYMTTJVB"
                   " Demo Recording.mp4 (file, 78154968 bytes) file:///b!abc-DEF_1/01XLXYLJ3W5HWBPLNOHNEZQOF6L5BJ3MSY")
        folder = {"name": "Demo_Recordings", "uri": "file:///b!abc-DEF_1/01XLXYLJ4GHHZOW7EWHJD3FKK3NIAVNOV6",
                  "webUrl": "https://contoso-my.sharepoint.com/personal/kim_contoso_com/Documents/Demo_Recordings"}
        page = {"name": "Other.mp4", "uri": "file:///b!abc-DEF_1/01XLXYLJ6JY5S2EBAAWZCIR3BHOYRYK4DW",
                "webUrl": "https://contoso-my.sharepoint.com/personal/kim_contoso_com/Documents/Forms/DispForm.aspx?ID=1"}
        runs = [([{"tool": "sharepoint_folder_search", "input": {}, "objs": [folder, page], "raw": []}], "done"),
                ([{"tool": "read_resource", "input": {"uri": folder["uri"]}, "objs": [], "raw": [listing]},
                  {"tool": "read_resource", "input": {"uri": page["uri"]}, "objs": [{"webUrl": folder["webUrl"] + "/Sub/Other.mp4", "file": {"size": 7040004}}], "raw": []}], "done")]
        with mock.patch.object(sp_index, "_once", lambda *a, **k: runs.pop(0)), \
                mock.patch.object(sp_index, "_setup", lambda: ("haiku", {"kim_contoso_com": "Parker Noel"})):
            out = sp_index.folder_lookup("Demo_Recordings")
        self.assertIn("Folder “Demo_Recordings” · OneDrive of Parker Noel › Documents › Demo_Recordings · 2 items", out)
        self.assertIn("  - Demo Recording.mp4 · 78.2 MB\n    " + folder["webUrl"] + "/Demo Recording.mp4", out)
        self.assertIn(folder["webUrl"] + "/Sub/Other.mp4", out)            # a page link resolved to the file's own address
        u = desktop.download_url(folder["webUrl"] + "/Demo Recording.mp4", HOSTS)
        self.assertTrue(u.endswith("download.aspx?SourceUrl=/personal/kim_contoso_com/Documents/Demo_Recordings/Demo%20Recording.mp4"))


class Cli(unittest.TestCase):
    def test_ask_do_exits_cleanly_after_its_wait(self):   # 23 Nov 2026: an expired request crashed on main's closing commit
        from assist import cli
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(d) / "t.db")}), \
                mock.patch.object(desktop, "ask", lambda arg: ("Allowed 1 of 1 steps", 0)), mock.patch("builtins.print"):
            with self.assertRaises(SystemExit) as e:
                cli.main(["ask-do", "{}"])
        self.assertEqual(e.exception.code, 0)


class ChatWiring(unittest.TestCase):
    def test_the_chat_may_run_ask_do_and_ask_sharepoint_and_labels_them(self):
        from assist import chat
        self.assertTrue(any("ask-do" in a for a in chat.ALLOWED))
        self.assertTrue(any("ask-sharepoint" in a for a in chat.ALLOWED))
        self.assertEqual(chat._tool_label("Bash", {"command": f"{chat.CLI} ask-do .plan.json"}), "Asking you to allow steps on your Mac")
        self.assertIn("SharePoint", chat._tool_label("Bash", {"command": f'{chat.CLI} ask-sharepoint "filename:Demo"'}))
        self.assertIn("ask-do", chat.SYSTEM)


if __name__ == "__main__":
    unittest.main()
