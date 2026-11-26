"""The code base (assist/codebase.py, Sam, 20 Nov 2026): the company's code read from the git clones on this Mac, for the Code
base page and Ask SleePO's ask-code. Everything here runs on throwaway repositories in a temporary folder: never the real
clones, the live database or the live jobs/ folder.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import chat, codebase, jobs

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def commit(path, files, msg):
    for name, text in files.items():
        f = Path(path) / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", msg)
    return git(path, "rev-parse", "HEAD")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.origin = self.home / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True, env=ENV)
        self.repo = self.home / "code" / "widget"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "remote", "add", "origin", "https://gitlab.com/acme/widget.git")   # as a real clone's remote reads,
        git(self.repo, "config", f"url.{self.origin}.insteadOf", "https://gitlab.com/acme/widget.git")   # served from the folder
        self.first = commit(self.repo, {
            "src/roles/RoleManager.java": "public class RoleManager {\n  // Admins grant the Architect role\n  void grant() {}\n}\n",
            "src/test/RoleManagerTest.java": "class RoleManagerTest { RoleManager m; }\n",
            "config/app.properties": "db.password=supersecret123\nmode=cloud\n",
            "config/.env": "ROLE_TOKEN=abc123456789\n",
            "certs/server.pem": "-----BEGIN PRIVATE KEY----- RoleManager\n",
            "README.md": "# Widget\n",
        }, "first")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "fetch", "-q", "origin")
        git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        for p in (mock.patch.object(codebase, "HOME", self.home), mock.patch.object(codebase, "JOB", self.home / "jobs" / "code_fetch.json"),
                  mock.patch.object(jobs, "LOCK_DIR", self.home / "jobs" / "locks"),
                  mock.patch.object(codebase, "_settings", return_value={"add": [], "hide": []}),
                  mock.patch.object(codebase, "config", return_value={"hosts": ["gitlab.com/acme/"], "host_name": "GitLab",
                                                                        "repos": {"widget": {"label": "The widget", "about": "Widgets."}}})):
            p.start()
            self.addCleanup(p.stop)
        codebase._cache.clear()
        self.addCleanup(codebase._cache.clear)


class Urls(unittest.TestCase):
    def test_web_and_ssh_forms(self):
        self.assertEqual(codebase.web_url("git@gitlab.com:acme/ice-nine.git"), "https://gitlab.com/acme/ice-nine")
        self.assertEqual(codebase.web_url("https://token@example.org/acme/central-webapp.git"), "https://gitlab.com/acme/central-webapp")
        self.assertEqual(codebase.ssh_url("https://gitlab.com/acme/central-webapp.git"), "git@gitlab.com:acme/central-webapp.git")
        self.assertIsNone(codebase.ssh_url("git@gitlab.com:acme/x.git"))


class Clones(Base):
    def test_found_by_their_remote_and_only_ours(self):
        other = self.home / "Developer" / "mine"
        other.mkdir(parents=True)
        git(other, "init", "-q")
        git(other, "remote", "add", "origin", "git@github.com:someone/mine.git")
        got = codebase.clones()
        self.assertEqual([r["path"] for r in got], [str(self.repo)])

    def test_described_from_the_remote_tracking_branch(self):
        d = codebase.describe(codebase.clones()[0])
        self.assertEqual((d["branch"], d["ref"], d["tracking"]), ("main", "refs/remotes/origin/main", True))
        self.assertEqual(d["sha"], self.first)
        self.assertEqual(d["label"], "The widget")
        self.assertIn(("Java", 2), d["languages"])
        self.assertEqual(d["guide"], "README.md")


class Reading(Base):
    def test_search_reads_the_branch_not_local_edits(self):
        commit(self.repo, {"src/roles/Local.java": "class LocalOnlyCommit {}\n"}, "local commit, not pushed")
        (self.repo / "src" / "roles" / "Draft.java").write_text("class UncommittedDraft {}\n")
        self.assertEqual(codebase.search("LocalOnlyCommit|UncommittedDraft")["repos"][0]["total"], 0)
        r = codebase.search("rolemanager")["repos"][0]
        self.assertEqual([f["path"] for f in r["files"]], ["src/roles/RoleManager.java", "src/test/RoleManagerTest.java"])   # tests last
        self.assertTrue(r["files"][1]["test"])
        self.assertIn(f"/-/blob/{self.first}/src/roles/RoleManager.java#L1", r["files"][0]["lines"][0]["link"])

    def test_keys_and_env_files_are_never_searched_and_values_are_masked(self):
        r = codebase.search("token|private key|password")["repos"][0]
        self.assertEqual([f["path"] for f in r["files"]], ["config/app.properties"])
        self.assertEqual(r["files"][0]["lines"][0]["text"], "db.password=[hidden]")
        self.assertIn("keys or credentials", codebase.read("widget", "certs/server.pem")["error"])
        self.assertIn("keys or credentials", codebase.read("widget", "config/.env")["error"])
        self.assertNotIn("supersecret", codebase.read("widget", "config/app.properties")["text"])

    def test_read_with_line_numbers_and_a_path_filter(self):
        d = codebase.read("widget", "src/roles/RoleManager.java", 2, 3)
        self.assertEqual(d["text"].splitlines(), ["    2    // Admins grant the Architect role", "    3    void grant() {}"])
        self.assertIn("Did you mean", codebase.read("widget", "RoleManager.java")["error"])
        self.assertEqual([f["path"] for f in codebase.search("rolemanager", path_glob="*.java")["repos"][0]["files"]],
                         ["src/roles/RoleManager.java", "src/test/RoleManagerTest.java"])
        self.assertEqual([f["path"] for f in codebase.search("rolemanager", path_glob="roles")["repos"][0]["files"]], ["src/roles/RoleManager.java"])

    def test_the_chat_tool(self):
        self.assertIn("## widget: The widget", codebase.ask(["repos"]))
        out = codebase.ask(["search", "architect"])
        self.assertIn("src/roles/RoleManager.java  (1 line)", out)
        self.assertIn("  2: // Admins grant the Architect role", out)
        self.assertIn("RoleManager.java", codebase.ask(["files", "roles", "java"]))
        self.assertIn("lines 1-4 of 4", codebase.ask(["read", "widget", "src/roles/RoleManager.java"]))
        self.assertIn("ask-code repos", codebase.ask(["nonsense"]))
        self.assertIn("ask-code", chat.TOOLS)
        self.assertTrue(any("ask-code" in a for a in chat.ALLOWED))


class Updating(Base):
    def test_fetch_moves_only_the_remote_tracking_branch(self):
        other = self.home / "elsewhere" / "other"   # not under a scanned folder's second level with our remote
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True, env=ENV)
        new = commit(other, {"src/roles/Viewer.java": "class ViewerRole {}\n"}, "viewer role")
        git(other, "push", "-q", "origin", "main")
        (self.repo / "README.md").write_text("# Widget, edited locally\n")
        head = git(self.repo, "rev-parse", "HEAD")
        self.assertTrue(codebase.fetch(log=lambda *_: None))
        self.assertEqual(git(self.repo, "rev-parse", "refs/remotes/origin/main"), new)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)                       # the local branch is left alone
        self.assertEqual((self.repo / "README.md").read_text(), "# Widget, edited locally\n")   # and the working tree
        st = codebase.state()
        self.assertTrue(st["ok"])
        self.assertEqual(st["repos"][str(self.repo)]["new_commits"], 1)
        self.assertFalse(codebase.due())
        self.assertEqual(codebase.search("ViewerRole")["repos"][0]["total"], 1)


class Known(unittest.TestCase):
    def test_the_knowledge_base_map(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE documents (id TEXT, body_md TEXT)")
        con.execute("INSERT INTO documents VALUES ('kb/map.md', ?)", (
            "- **[acme.jvm](https://gitlab.com/acme/acme.jvm)** — Kotlin monorepo; hosts **SCIM**\n"
            "| [acme/central-webapp](https://gitlab.com/acme/central-webapp) | Process Design — primary application | [[Process Design]] |\n"
            "See [GitLab docs](https://docs.gitlab.com/x) | not ours |\n",))
        with mock.patch.object(codebase, "config", return_value={"map_doc": "kb/map.md", "hosts": ["gitlab.com/acme/"]}):
            got = codebase.known(con)
        self.assertEqual([(x["path"], x["about"]) for x in got], [("acme/acme.jvm", "Kotlin monorepo; hosts SCIM"),
                                                                  ("acme/central-webapp", "Process Design — primary application")])


if __name__ == "__main__":
    unittest.main()
