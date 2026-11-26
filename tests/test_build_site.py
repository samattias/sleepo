"""SleePO's website (scripts/build_site.py; Sam, 25 Nov 2026): built from the GitHub README so the two never drift. The real
README must build; a section the site needs that is gone stops the build; the GitHub address is filled in; links between
the README's sections point at the site's; the changelog shows its newest entries.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402

URL = "https://github.com/example/sleepo"
MINI = """<h1 align="center">SleePO</h1>

<p align="center"><b>A chief of staff.</b><br>
It reads your mail.</p>

<p align="center">
  Runs on your Mac&nbsp;·&nbsp;Reads, never sends
</p>

<p align="center">
  Recommended to run with&nbsp;
  <a href="https://granola.ai"><img src="docs/apps/granola.png" width="20" height="20" alt="">&nbsp;Granola</a>
</p>

<p align="center">
  <img src="docs/screenshots/01-tasks.png" alt="The task list" width="900">
</p>

## Why SleePO

Attention runs out.

- **Nothing slips.** Promises are found.
- **Nothing goes out without you.** You send.

## What it does

### Your day on one page
The first page. See [why](#recommended-granola-and-fluidvoice).

### Replies written for you
Every email gets a reply.

<p align="center"><img src="docs/screenshots/03-inbox.png" alt="An email" width="900"></p>

### And more
- **Live calls.** Ask during a call.

## Recommended: Granola and FluidVoice

Two apps.

<table>
<tr>
<td width="96" align="center" valign="top"><a href="https://granola.ai"><img src="docs/apps/granola.png" width="72" alt=""></a></td>
<td valign="top">
<b><a href="https://granola.ai">Granola</a></b>: notes<br><br>
Granola takes notes.
</td>
</tr>
</table>

## Private by design

| | |
|---|---|
| **Runs locally** | On your Mac. |

---

## Quick start (no coding needed)

About 20 minutes.

### What you need
- **Access to [the code]({{REPO_URL}}).**

### Step 1: Install Claude Code
```sh
curl -fsSL https://claude.ai/install.sh | bash
```

### Step 2: Let Claude install SleePO
```text
1. Download the code from {{REPO_URL}} into a new folder.
```

## Questions

**Does it ever send anything?** No.

**What does it cost?** Your Claude plan.
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)

    def page(self, readme=MINI, changelog=None):
        (self.repo / "README.md").write_text(readme)
        if changelog:
            (self.repo / "CHANGELOG.md").write_text(changelog)
        return build_site.build(self.repo, URL).read_text()


class Site(Base):
    def test_the_real_readme_builds(self):
        shutil.copy(ROOT / "docs" / "github" / "README.md", self.repo / "README.md")
        if (ROOT / "docs" / "github" / "CHANGELOG.md").exists():
            shutil.copy(ROOT / "docs" / "github" / "CHANGELOG.md", self.repo / "CHANGELOG.md")
        html = build_site.build(self.repo, URL).read_text()
        for sid in ("why", "features", "apps", "private", "install", "faq"):
            self.assertIn(f'id="{sid}"', html)
        features = [h for h, _ in build_site.split(dict(build_site.split((self.repo / "README.md").read_text(), 2))["What it does"], 3)[1:]]
        self.assertGreater(len(features), 3)
        for h in features:   # every feature in the README is on the page
            self.assertIn(h, html)
        self.assertNotIn(build_site.TOKEN, html)
        self.assertIn(f"Download the code from {URL}", html)
        self.assertNotIn('src="docs/', html)
        self.assertTrue((self.repo / "docs" / ".nojekyll").exists())

    def test_sections_land_in_their_places(self):
        html = self.page()
        self.assertIn("<h1>A chief of staff.</h1>", html)
        self.assertIn("<li>Reads, never sends</li>", html)
        self.assertIn("Nothing slips.", html)
        self.assertIn('src="screenshots/03-inbox.png"', html)
        self.assertIn('class="feature solo" id="your-day-on-one-page"', html)
        self.assertIn('href="#apps"', html)                     # a link to a README section points at the site's
        self.assertIn("Runs locally", html)
        self.assertIn('<span class="num">1</span>', html)
        self.assertIn('<button type="button" class="copy">Copy</button>', html)
        self.assertIn("<summary>Does it ever send anything?</summary>", html)
        self.assertIn(f'href="{URL}#quick-start-no-coding-needed"', html)
        self.assertIn(f'href="{URL}"', html)
        self.assertIn('<p class="works">Recommended to run with <a href="https://granola.ai">', html)   # the README's words
        self.assertIn('<figure class="macbook"><div class="lid"><div class="screen"><img src="screenshots/01-tasks.png"', html)

    def test_the_logo_sleeps(self):
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect/>'
                                                     '<path d="M1"/><!-- zz --><path d="M2"/><path d="M3"/></svg>')
        html = self.page()
        self.assertIn('<svg class="mark" width="72" height="72" role="img"', html)
        self.assertIn('<path d="M1"/><!-- zz --><path class="z1" d="M2"/><path class="z2" d="M3"/>', html)

    def test_a_missing_section_stops_the_build(self):
        broken = MINI.replace("## Private by design", "## Privacy notes")
        with self.assertRaises(SystemExit) as e:
            self.page(broken)
        self.assertIn("Private by design", str(e.exception))
        self.assertFalse((self.repo / "docs" / "index.html").exists())

    def test_the_newest_changes_only(self):
        log = "# What's new\n\n" + "".join(f"## {d} Nov 2026\n- **Change {d}.** Text.\n\n" for d in (25, 23, 20, 19))
        html = self.page(changelog=log)
        self.assertIn("Change 25.", html)
        self.assertIn("Change 20.", html)
        self.assertNotIn("Change 19.", html)
        self.assertIn('id="new"', html)

    def test_no_changelog_no_section(self):
        self.assertNotIn('id="new"', self.page())

    def test_a_custom_domain_is_kept_and_shared(self):
        html = self.page()   # no domain: GitHub Pages' own address, and no CNAME (it would move the site)
        self.assertIn('<link rel="canonical" href="https://example.github.io/sleepo/">', html)
        self.assertFalse((self.repo / "docs" / "CNAME").exists())
        (self.repo / "README.md").write_text(MINI)
        html = build_site.build(self.repo, URL, "sleepo.example").read_text()
        self.assertEqual((self.repo / "docs" / "CNAME").read_text(), "sleepo.example\n")
        self.assertIn('<meta property="og:url" content="https://sleepo.example/">', html)
        self.assertIn('<meta property="og:image" content="https://sleepo.example/screenshots/01-tasks.png">', html)
        self.assertNotIn("$SHARE", html)
        self.assertNotIn("MIT licence", html)
        (self.repo / "LICENSE").write_text("MIT License\n")
        self.assertIn(f'<a href="{URL}/blob/main/LICENSE">MIT licence</a>', build_site.build(self.repo, URL).read_text())

    def test_the_address_comes_from_the_git_remote(self):
        self.assertIsNone(build_site.git_url(self.repo))
        with self.assertRaises(SystemExit):
            (self.repo / "README.md").write_text(MINI)
            build_site.build(self.repo)


class GitUrl(unittest.TestCase):
    def test_forms(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            for remote in ("https://github.com/a/b.git", "git@example.org:a/b.git", "https://github.com/a/b"):
                subprocess.run(["git", "-C", d, "remote", "remove", "origin"], capture_output=True)
                subprocess.run(["git", "-C", d, "remote", "add", "origin", remote], check=True)
                self.assertEqual(build_site.git_url(d), "https://github.com/a/b")


if __name__ == "__main__":
    unittest.main()
