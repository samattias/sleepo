"""Versions and updates (assist/updates.py; Sam, 26 Nov 2026): release names by date, the changelog notes since a release, the
daily check against GitHub (faked here), and the update itself on throwaway git repositories: it moves the code to the new
release's tag, refreshes the user's untouched templates and keeps the ones they edited, and stops, putting the code back,
when something goes wrong. Nothing here touches the live jobs/ folder, the database or the network.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import subprocess
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from assist import jobs, updates

URL = "https://github.com/example/sleepo.git"


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True, text=True).stdout.strip()


class Names(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(updates.parse("v2026.11.26"), (2026, 11, 26, 0))
        self.assertEqual(updates.parse("2026.11.26.2"), (2026, 11, 26, 2))
        self.assertIsNone(updates.parse("1.4"))
        self.assertTrue(updates.newer("2026.12.03", "2026.11.26"))
        self.assertTrue(updates.newer("2026.11.26.1", "2026.11.26"))
        self.assertFalse(updates.newer("2026.11.26", "2026.11.26"))
        self.assertTrue(updates.newer("2026.11.26", None))
        self.assertEqual(updates.version_for(date(2026, 12, 3)), "2026.12.03")
        self.assertEqual(updates.version_for(date(2026, 12, 3), ["v2026.12.03", "v2026.12.03.1"]), "2026.12.03.2")

    def test_notes_since_a_release(self):
        log = "# What's new\n\nNewest first.\n\n## 26 Nov 2026\n- **Updates.** One.\n\n## 25 Nov 2026\n- **Actions.** Two.\n\n## 20 Nov 2026\n- Three.\n"
        self.assertEqual(updates.notes_since(log, "2026.11.25"), "## 26 Nov 2026\n- **Updates.** One.")
        self.assertIn("## 20 Nov 2026", updates.notes_since(log))
        self.assertEqual(updates.notes_since(log, "2026.11.26"), "")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self._patch(updates, "STATE", self.tmp / "jobs" / "updates.json")
        self._patch(jobs, "LOCK_DIR", self.tmp / "jobs" / "locks")
        self._patch(updates, "MCP_RELAY", ("scripts/sleepo_mcp.py", self.tmp / "relay.py"))

    def _patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)


class Check(Base):
    def setUp(self):
        super().setUp()
        self.app = self.tmp / "app"
        self.app.mkdir()
        git(self.app, "init", "-q")
        git(self.app, "remote", "add", "origin", URL)
        (self.app / "VERSION").write_text("2026.11.20\n")
        self.calls = []

    def fetch(self, name):
        self.calls.append(name)
        return {"version": "2026.11.26", "tag": "v2026.11.26", "notes": "## 26 Nov 2026", "url": "u", "published": ""}

    def test_once_a_day_unless_asked(self):
        updates.check(app=self.app, fetch=self.fetch)
        updates.check(app=self.app, fetch=self.fetch)
        self.assertEqual(self.calls, ["example/sleepo"])
        updates.check(force=True, app=self.app, fetch=self.fetch)
        self.assertEqual(len(self.calls), 2)
        st = updates.status(app=self.app)
        self.assertEqual(st["version"], "2026.11.20")
        self.assertTrue(st["available"])
        self.assertEqual(st["latest"]["tag"], "v2026.11.26")

    def test_offline_keeps_what_was_known(self):
        updates.check(app=self.app, fetch=self.fetch)
        updates.check(force=True, app=self.app, fetch=mock.Mock(side_effect=OSError("offline")))
        st = updates.status(app=self.app)
        self.assertIn("Couldn't reach GitHub", st["error"])
        self.assertEqual(st["latest"]["version"], "2026.11.26")

    def test_a_development_copy_is_never_offered_an_update(self):
        (self.app / "VERSION").unlink()
        updates.check(app=self.app, fetch=self.fetch)
        st = updates.status(app=self.app)
        self.assertTrue(st["dev"])
        self.assertFalse(st["available"])
        self.assertIn("development copy", st["blocked"])

    def test_a_just_started_update_is_not_reported_as_stopped(self):
        updates._save(update={"running": True, "phase": "Starting", "started_ts": time.time()})
        self.assertTrue(updates.status(app=self.app)["running"])
        updates._save(update={"running": True, "phase": "Installing", "started_ts": time.time() - 600})   # its process is gone
        st = updates.status(app=self.app)
        self.assertFalse(st["running"])
        self.assertIn("stopped before it finished", st["update"]["error"])

    def test_the_daily_check_can_be_switched_off(self):
        con = mock.Mock()
        with mock.patch.object(updates.db, "get_setting", return_value="off"), mock.patch.object(updates, "check") as chk:
            updates.check_soon(con)
            time.sleep(0.05)
        chk.assert_not_called()


class Update(Base):
    """An origin with two releases, an install of the first one, and its data folder."""

    def setUp(self):
        super().setUp()
        self.origin = self.tmp / "origin"
        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        git(self.origin, "config", "user.email", "t@example.org")
        git(self.origin, "config", "user.name", "T")
        self.write(self.origin, {"VERSION": "2026.11.20\n", "requirements.txt": "fastapi\n",
                                 "templates/data/memory/context/about-me.md": "About you v1\n",
                                 "templates/data/memory/context/voice.md": "Voice v1\n",
                                 ".claude/skills/brief/SKILL.md": "Brief v1\n", "scripts/sleepo_mcp.py": "relay v1\n"})
        self.release("v2026.11.20")
        self.write(self.origin, {"VERSION": "2026.11.26\n", "templates/data/memory/context/about-me.md": "About you v2\n",
                                 "templates/data/memory/context/voice.md": "Voice v2\n", ".claude/skills/brief/SKILL.md": "Brief v2\n",
                                 ".claude/skills/week/SKILL.md": "Week v2\n", "scripts/sleepo_mcp.py": "relay v2\n"})
        self.release("v2026.11.26")
        self.app = self.tmp / "app"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.app)], check=True, capture_output=True)
        git(self.app, "-c", "advice.detachedHead=false", "checkout", "-q", "v2026.11.20")
        git(self.app, "remote", "set-url", "origin", URL)
        git(self.app, "config", f"url.{self.origin.as_uri()}.insteadOf", URL)   # "GitHub" is the local origin
        self.data = self.tmp / "data"   # what install.sh copied
        self.write(self.data, {"memory/context/about-me.md": "About you v1\n", "memory/context/voice.md": "My own voice\n",
                               ".claude/skills/brief/SKILL.md": "Brief v1\n"})
        (self.tmp / "relay.py").write_text("relay v1\n")
        self.pip = mock.Mock()
        self.migrate = mock.Mock()
        self.restart = mock.Mock()
        for name, value in (("_pip", self.pip), ("_migrate", self.migrate), ("_restart", self.restart),
                            ("_backup", mock.Mock(return_value="backup.db")), ("_refresh_running", mock.Mock(return_value=False))):
            self._patch(updates, name, value)

    def write(self, root, files):
        for rel, text in files.items():
            p = Path(root) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def release(self, tag):
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", tag)
        git(self.origin, "tag", tag)

    def run_update(self, tag=None):
        return updates.update(tag, log=lambda *_: None, app=self.app, data=self.data)

    def test_moves_to_the_new_release_and_keeps_what_the_user_changed(self):
        self.assertEqual(updates.current(self.app), "2026.11.20")
        self.assertTrue(self.run_update())
        self.assertEqual(updates.current(self.app), "2026.11.26")
        self.assertEqual((self.data / "memory/context/about-me.md").read_text(), "About you v2\n")   # untouched: refreshed
        self.assertEqual((self.data / "memory/context/voice.md").read_text(), "My own voice\n")     # edited: kept
        self.assertEqual((self.data / ".claude/skills/brief/SKILL.md").read_text(), "Brief v2\n")
        self.assertEqual((self.data / ".claude/skills/week/SKILL.md").read_text(), "Week v2\n")      # new: added
        self.assertEqual((self.tmp / "relay.py").read_text(), "relay v2\n")
        st = updates._state()["update"]
        self.assertTrue(st["ok"])
        self.assertEqual((st["from"], st["version"]), ("2026.11.20", "2026.11.26"))
        self.assertEqual(st["templates"]["kept"], ["memory/context/voice.md"])
        self.assertIn(".claude/skills/week/SKILL.md", st["templates"]["added"])
        self.migrate.assert_called_once()
        self.pip.assert_not_called()   # requirements.txt did not change
        self.restart.assert_called_once()

    def test_new_packages_are_installed(self):
        self.write(self.origin, {"VERSION": "2026.11.27\n", "requirements.txt": "fastapi\nfastembed\n"})
        self.release("v2026.11.27")
        self.assertTrue(self.run_update("v2026.11.27"))
        self.pip.assert_called_once()

    def test_local_edits_stop_it(self):
        (self.app / "requirements.txt").write_text("changed\n")
        self.assertFalse(self.run_update())
        self.assertIn("changed file", updates._state()["update"]["error"])
        self.assertEqual(updates.current(self.app), "2026.11.20")
        self.restart.assert_not_called()

    def test_never_goes_backwards_or_during_a_refresh(self):
        self.assertFalse(self.run_update("v2026.11.20"))
        self.assertIn("already", updates._state()["update"]["error"])
        updates._refresh_running.return_value = True
        self.assertFalse(self.run_update())
        self.assertIn("refresh is running", updates._state()["update"]["error"])

    def test_a_failure_puts_the_code_back(self):
        self.migrate.side_effect = updates.Stop("Updating the database failed: boom")
        self.assertFalse(self.run_update())
        st = updates._state()["update"]
        self.assertIn("put back", st["error"])
        self.assertEqual(updates.current(self.app), "2026.11.20")
        self.assertEqual((self.data / "memory/context/about-me.md").read_text(), "About you v1\n")
        self.restart.assert_not_called()

    def test_a_zip_download_cannot_update(self):
        (self.tmp / "zip").mkdir()
        (self.tmp / "zip" / "VERSION").write_text("2026.11.20\n")
        self.assertIn("without git", updates.blocked(self.tmp / "zip"))


if __name__ == "__main__":
    unittest.main()
