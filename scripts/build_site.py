"""SleePO's website, built from its GitHub README (Sam, 25 Nov 2026: "a website for SleePO that I can use to promote it that
would link to the GitHub and installation instructions ... as the application also updates with new features and
capabilities, the website remains synchronized").

The README is the one source. The page lays out its sections (the tagline, Why SleePO, What it does, the recommended apps,
Private by design, Quick start, Questions) and the newest entries of CHANGELOG.md, and is written as docs/index.html beside
the images the README already uses (docs/screenshots, docs/apps, docs/logo.svg), so a static host serves the docs/ folder as
it is (GitHub Pages: deploy from a branch, main, /docs). scripts/export_code.py builds it on every export from the scrubbed
README, so the page pushed always says what the README pushed with it says, and it goes through the same check for private
terms. When the README no longer has a section the page needs, the build stops (the export exits 1) instead of leaving the
site behind; tests/test_build_site.py builds the real README.

  python3 scripts/build_site.py --repo DIR [--url https://github.com/OWNER/REPO]

DIR holds README.md (and CHANGELOG.md, docs/). Without --url the GitHub address comes from DIR's git remote. The README may
say {{REPO_URL}} where the address goes; the export fills it in. Needs markdown-it-py (installed in SleePO's venv).
"""
import html
import re
import struct
import subprocess
import sys
from datetime import date
from pathlib import Path

TOKEN = "{{REPO_URL}}"
# the README's "## " sections the page is made of: key -> how the heading starts
NEED = {"why": "Why", "features": "What it does", "apps": "Recommended", "private": "Private by design",
        "install": "Quick start", "faq": "Questions"}
CHANGES = 3   # newest changelog entries shown


def git_url(folder):
    """The repository's web address from its git remote, or None."""
    try:
        u = subprocess.run(["git", "-C", str(folder), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None
    m = re.match(r"(?:https://|git@)(github\.com)[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", u)
    return f"https://{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None


def fill(text, url):
    return text.replace(TOKEN, url)


def slug(heading):
    """GitHub's anchor for a heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def split(text, level):
    """[(heading, body)] at "## " or "### " headings (never inside a code block); the text before the first is under ""."""
    mark, parts, head, buf, code = "#" * level + " ", [], "", [], False
    for line in text.splitlines():
        if line.startswith("```"):
            code = not code
        if not code and line.startswith(mark):
            parts.append((head, "\n".join(buf)))
            head, buf = line[len(mark):].strip(), []
        else:
            buf.append(line)
    parts.append((head, "\n".join(buf)))
    return [(h, re.sub(r"(?m)^---\s*$", "", b).strip()) for h, b in parts]


def _md():
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        raise SystemExit("build_site: needs markdown-it-py (pip install markdown-it-py)")
    return MarkdownIt("commonmark", {"html": True}).enable("table")


def site_url(url, domain=None):
    """Where the page is served: the custom domain (docs/CNAME), else GitHub Pages' own address for the repository."""
    if domain:
        return f"https://{domain.strip().strip('/')}/"
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)$", url or "")
    return f"https://{m.group(1).lower()}.github.io/{m.group(2)}/" if m else None


class Page:
    def __init__(self, repo, url, domain=None):
        self.repo, self.url, self.md = Path(repo), url, _md()
        self.site = site_url(url, domain)
        self.anchors = {}

    # ------------------------------------------------------------ text
    def paths(self, s):
        s = re.sub(r'(src|href)="docs/', r'\1="', s)
        return re.sub(r'href="#([\w\-]+)"', lambda m: f'href="#{self.anchors.get(m.group(1), m.group(1))}"', s)

    def block(self, text):
        return self.paths(self.md.render(text))

    def inline(self, text):
        return self.paths(self.md.renderInline(text.strip()))

    def code(self, s):
        """Every code block gets a Copy button."""
        s = s.replace("<pre>", '<div class="code"><button type="button" class="copy">Copy</button><pre>')
        return s.replace("</pre>", "</pre></div>")

    def img(self, rel, alt, cls="", lazy=True):
        size = ""
        p = self.repo / "docs" / rel
        try:
            with open(p, "rb") as f:
                head = f.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                size = f' width="{w // 2}" height="{h // 2}"'
        except OSError:
            pass
        return (f'<img src="{html.escape(rel)}" alt="{html.escape(alt)}"{size}' + (' loading="lazy"' if lazy else "")
                + (f' class="{cls}"' if cls else "") + ">")

    def shot(self, rel, alt, lazy=True):
        return f'<figure class="shot"><div class="chrome"><i></i><i></i><i></i></div>{self.img(rel, alt, lazy=lazy)}</figure>'

    def macbook(self, rel, alt):
        """The main screenshot on a laptop drawn in CSS (Sam, 25 Nov 2026: "within a MacBook Pro type image"): no picture
        of Apple's to license, and it scales with the page."""
        return (f'<figure class="macbook"><div class="lid"><div class="screen">{self.img(rel, alt, lazy=False)}</div></div>'
                '<div class="base"></div></figure>')

    def mark(self):
        """The logo drawn inline, so its zz can drift up as it sleeps; the logo file as it is when it has no zz."""
        try:
            svg = (self.repo / "docs" / "logo.svg").read_text()
        except OSError:
            return '<img class="mark" src="logo.svg" alt="SleePO logo" width="72" height="72">'
        svg = re.sub(r"<\?xml[^>]*>\s*", "", svg).strip()
        head, sep, tail = svg.partition("<!-- zz -->")
        if sep:   # the two paths after the comment are the big z and the small one
            n = 0

            def tag(m):
                nonlocal n
                n += 1
                return f'<path class="z{n}" ' if n <= 2 else m.group(0)
            svg = head + sep + re.sub(r"<path ", tag, tail)
        return svg.replace("<svg ", '<svg class="mark" width="72" height="72" role="img" aria-label="SleePO logo: a sleeping face on a bright lime square" ', 1)

    # ------------------------------------------------------------ the README
    def read(self):
        readme = self.repo / "README.md"
        if not readme.exists():
            raise SystemExit(f"build_site: no README.md in {self.repo}")
        text = fill(readme.read_text(), self.url)
        top, *rest = split(text, 2)
        found = {}
        for key, start in NEED.items():
            hit = [(h, b) for h, b in rest if h.startswith(start)]
            if not hit:
                raise SystemExit(f"build_site: the README has no section starting \"## {start}\": the website needs it "
                                 "(rename it in scripts/build_site.py NEED if the heading changed)")
            found[key] = hit[0]
            self.anchors[slug(hit[0][0])] = key
        for h, _ in rest:
            self.anchors.setdefault(slug(h), slug(h))
        return top[1], found, dict(rest)

    def hero(self, top):
        m = re.search(r"<b>(.+?)</b>\s*<br>\s*(.+?)</p>", top, re.S)
        if not m:
            raise SystemExit("build_site: the README's opening has no <b>tagline</b><br>summary paragraph")
        tagline, lede = m.group(1).strip(), " ".join(m.group(2).split())
        badges = []
        b = re.search(r'<p align="center">\s*([^<]*·[^<]*?)\s*</p>', top)
        if b:
            badges = [x.strip() for x in b.group(1).replace("&nbsp;", " ").split("·") if x.strip()]
        shot = re.search(r'<img src="docs/(screenshots/[^"]+)" alt="([^"]*)"', top)
        # the words before the recommended apps' links ("Recommended to run with")
        lead = re.search(r'<p align="center">\s*([^<]*?)(?:&nbsp;|\s)*<a href=', top)
        lead = " ".join(lead.group(1).replace("&nbsp;", " ").split()) if lead and lead.group(1).strip() else "Recommended with"
        return tagline, lede, badges, shot.groups() if shot else None, lead

    def pillars(self, body):
        intro, _, items = body.partition("\n- ")
        cards = []
        for item in re.split(r"\n- ", "- " + items if items else ""):
            m = re.match(r"-?\s*\*\*(.+?)\*\*\s*(.*)", item.strip(), re.S)
            if m:
                cards.append(f'<div class="card"><h3>{self.inline(m.group(1))}</h3><p>{self.inline(" ".join(m.group(2).split()))}</p></div>')
        return self.block(intro), cards

    def features(self, body):
        out, more = [], []
        n = 0
        for head, text in split(body, 3)[1:]:
            if head.lower().startswith("and more"):
                for item in re.split(r"(?m)^- ", text)[1:]:
                    m = re.match(r"\*\*(.+?)\*\*\s*(.*)", item.strip(), re.S)
                    if m:
                        more.append(f'<div class="card"><h3>{self.inline(m.group(1))}</h3><p>{self.inline(" ".join(m.group(2).split()))}</p></div>')
                continue
            shot = re.search(r'<img src="docs/(screenshots/[^"]+)" alt="([^"]*)"', text)
            words = re.sub(r'<p align="center">.*?</p>', "", text, flags=re.S).strip()
            if shot:
                flip = " flip" if n % 2 else ""
                n += 1
                out.append(f'<article class="feature{flip}" id="{slug(head)}"><div class="text"><h3>{self.inline(head)}</h3>'
                           f'{self.block(words)}</div>{self.shot(*shot.groups())}</article>')
            else:
                out.append(f'<article class="feature solo" id="{slug(head)}"><div class="text"><h3>{self.inline(head)}</h3>'
                           f'{self.block(words)}</div></article>')
        if not out:
            raise SystemExit("build_site: \"What it does\" has no ### features")
        return out, more

    def apps(self, body):
        intro = body.split("<table", 1)[0]
        rows = []
        for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
            icon = re.search(r'src="docs/(apps/[^"]+)"', tr)
            link = re.search(r'href="([^"]+)"', tr)
            cell = re.search(r'<td valign="top">(.*?)</td>', tr, re.S)
            name = re.search(r"<b><a[^>]*>(.+?)</a></b>", tr)
            if not (cell and name):
                continue
            inner = cell.group(1).strip().replace("<br><br>", "</p><p>")
            rows.append({"icon": icon.group(1) if icon else None, "link": link.group(1) if link else "", "name": name.group(1),
                         "html": self.paths(f"<p>{inner}</p>")})
        if not rows:
            raise SystemExit("build_site: the recommended apps table has no rows")
        return self.block(intro), rows

    def private(self, body):
        cards = []
        for m in re.finditer(r"(?m)^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*$", body):
            cards.append(f'<div class="card"><h3>{self.inline(m.group(1))}</h3><p>{self.inline(m.group(2))}</p></div>')
        if not cards:
            raise SystemExit("build_site: \"Private by design\" has no | **point** | text | rows")
        return cards

    def install(self, body):
        parts = split(body, 3)
        intro, steps = self.block(parts[0][1]), []
        for head, text in parts[1:]:
            m = re.match(r"Step\s+(\d+):\s*(.+)", head)
            num, title = (m.group(1), m.group(2)) if m else ("", head)
            mark = f'<span class="num">{num}</span>' if num else '<span class="num dot"></span>'
            steps.append(f'<li class="step{" numbered" if num else ""}">{mark}<div><h3>{self.inline(title)}</h3>'
                         f'{self.code(self.block(text))}</div></li>')
        return intro, steps

    def faq(self, body):
        out = []
        for m in re.finditer(r"(?ms)^\*\*(.+?)\*\*\s*(.+?)(?=^\*\*|\Z)", body):
            out.append(f'<details><summary>{self.inline(m.group(1))}</summary><p>{self.inline(" ".join(m.group(2).split()))}</p></details>')
        return out

    def changes(self):
        p = self.repo / "CHANGELOG.md"
        if not p.exists():
            return []
        out = []
        for head, body in split(p.read_text(), 2)[1:CHANGES + 1]:
            out.append(f'<div class="change"><h3>{html.escape(head)}</h3>{self.block(body)}</div>')
        return out

    # ------------------------------------------------------------ the page
    def build(self):
        top, s, rest = self.read()
        tagline, lede, badges, hero_shot, lead = self.hero(top)
        why_intro, pillars = self.pillars(s["why"][1])
        features, more = self.features(s["features"][1])
        apps_intro, apps = self.apps(s["apps"][1])
        private = self.private(s["private"][1])
        start_intro, steps = self.install(s["install"][1])
        faq = self.faq(s["faq"][1])
        changes = self.changes()
        url = html.escape(self.url)
        guide = f'{url}#{slug(s["install"][0])}'
        works = " and ".join(f'<a href="{html.escape(a["link"])}">' + (self.img(a["icon"], "", "appicon", lazy=False) if a["icon"] else "")
                             + f'{a["name"]}</a>' for a in apps)
        plain = re.sub(r"<[^>]+>", "", lede)
        title = re.sub(r"<[^>]+>", "", tagline).rstrip(".")

        licence = f' · <a href="{url}/blob/main/LICENSE">MIT licence</a>' if (self.repo / "LICENSE").exists() else ""
        share = ""   # a link shared in Slack, Teams or LinkedIn shows the page's title, words and main screenshot
        if self.site:
            site = html.escape(self.site)
            share = f'<link rel="canonical" href="{site}">\n<meta property="og:url" content="{site}">\n'
            if hero_shot:
                share += (f'<meta property="og:image" content="{site}{html.escape(hero_shot[0])}">\n'
                          '<meta name="twitter:card" content="summary_large_image">\n')
        h = [HEAD.replace("$TITLE", html.escape(f"SleePO · {title}")).replace("$DESC", html.escape(plain)).replace("$SHARE\n", share)]
        h.append(f"""<header class="top"><div class="wrap bar">
<a class="brand" href="#"><img src="logo.svg" alt="" width="28" height="28"><span>SleePO</span></a>
<nav><a href="#features">Features</a><a href="#private">Privacy</a><a href="#install">Install</a><a href="#faq">Questions</a></nav>
<div class="cta"><a class="btn ghost" href="{url}">{GITHUB}<span>GitHub</span></a><a class="btn primary" href="#install">Install</a></div>
</div></header>
<main>
<section class="hero"><div class="wrap">
{self.mark()}
<h1>{tagline}</h1>
<p class="lede">{lede}</p>
<div class="actions"><a class="btn primary lg" href="#install">Install on your Mac</a><a class="btn outline lg" href="{url}">{GITHUB}View on GitHub</a></div>
{('<ul class="badges">' + "".join(f"<li>{html.escape(b)}</li>" for b in badges) + "</ul>") if badges else ""}
<p class="works">{html.escape(lead)} {works}</p>
{self.macbook(*hero_shot) if hero_shot else ""}
</div></section>

<section id="why"><div class="wrap">
<h2>{self.inline(s["why"][0])}</h2>
<div class="intro">{why_intro}</div>
<div class="grid three">{"".join(pillars)}</div>
</div></section>

<section id="features"><div class="wrap">
<h2>{self.inline(s["features"][0])}</h2>
{"".join(features)}
{('<h3 class="sub">And more</h3><div class="grid three">' + "".join(more) + "</div>") if more else ""}
</div></section>

<section id="apps" class="soft"><div class="wrap">
<h2>{self.inline(s["apps"][0])}</h2>
<div class="intro">{apps_intro}</div>
<div class="grid two">{"".join(f'<div class="card app">' + (f'<a href="{html.escape(a["link"])}">' + self.img(a["icon"], a["name"] + " app icon", "appbig") + "</a>" if a["icon"] else "") + f'<div>{a["html"]}</div></div>' for a in apps)}</div>
</div></section>

<section id="private" class="band"><div class="wrap">
<h2>{self.inline(s["private"][0])}</h2>
<div class="grid three">{"".join(private)}</div>
</div></section>

<section id="install"><div class="wrap">
<h2>{self.inline(s["install"][0])}</h2>
<div class="intro">{start_intro}</div>
<ol class="steps">{"".join(steps)}</ol>
<p class="more-link">The full guide, with what to do when something goes wrong, is in the <a href="{guide}">README on GitHub</a>.</p>
</div></section>
""")
        if changes:
            h.append(f"""<section id="new" class="soft"><div class="wrap">
<h2>What's new</h2>
<div class="changes">{"".join(changes)}</div>
<p class="more-link"><a href="{url}/blob/main/CHANGELOG.md">Everything that changed</a></p>
</div></section>
""")
        if faq:
            h.append(f"""<section id="faq"><div class="wrap narrow">
<h2>{self.inline(s["faq"][0])}</h2>
{"".join(faq)}
</div></section>
""")
        h.append(f"""<section class="final"><div class="wrap">
<h2>{tagline}</h2>
<div class="actions"><a class="btn dark lg" href="#install">Install on your Mac</a><a class="btn outline-dark lg" href="{url}">{GITHUB}View on GitHub</a></div>
</div></section>
</main>
<footer><div class="wrap foot">
<span class="brand small"><img src="logo.svg" alt="" width="20" height="20"><span>SleePO</span></span>
<span>Code only, no data{licence} · Updated {date.today().strftime("%-d %b %Y")}</span>
<a href="{url}">GitHub</a>
</div></footer>
<script>{SCRIPT}</script>
</body>
</html>
""")
        return "".join(h)


def build(repo, url=None, domain=None):
    """Write docs/index.html (and docs/.nojekyll) in the repository folder; returns the page's path. With a domain, also
    docs/CNAME, which is how GitHub Pages keeps a custom domain when it publishes from a branch (Sam, 25 Nov 2026: sleepo.ai):
    a push without it would take the domain off the site."""
    repo = Path(repo)
    url = url or git_url(repo)
    if not url:
        raise SystemExit("build_site: no GitHub address: pass --url or give the folder a git remote")
    page = Page(repo, url, domain).build()
    out = repo / "docs" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    (out.parent / ".nojekyll").write_text("")   # GitHub Pages serves the folder as it is
    if domain:
        (out.parent / "CNAME").write_text(domain.strip().strip("/") + "\n")
    return out


GITHUB = ('<svg class="gh" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 0 '
          '3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94'
          '-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89'
          '-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53'
          '-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07'
          '-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>')

SCRIPT = """
(function () {   // sections rise into view as you scroll
  if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var els = document.querySelectorAll('main section:not(.hero) h2, .intro, .card, .feature, .step, .change, details, h3.sub');
  var io = new IntersectionObserver(function (seen) {
    seen.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.06 });
  els.forEach(function (el) {   // cards in a row follow one another
    var same = Array.prototype.filter.call(el.parentElement.children, function (c) { return c.className === el.className; });
    var i = same.indexOf(el);
    if (i > 0) el.style.transitionDelay = Math.min(i, 5) * 80 + 'ms';
  });
  els.forEach(function (el) { el.classList.add('reveal'); io.observe(el); });
})();
document.querySelectorAll('.code .copy').forEach(function (b) {
  b.addEventListener('click', function () {
    var t = b.nextElementSibling.innerText;
    var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1600); };
    if (navigator.clipboard) navigator.clipboard.writeText(t).then(done, function () {});
  });
});
"""

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$TITLE</title>
<meta name="description" content="$DESC">
<meta property="og:title" content="SleePO">
<meta property="og:description" content="$DESC">
<meta property="og:type" content="website">
$SHARE
<meta name="theme-color" content="#c8ff00">
<link rel="icon" href="logo.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Unbounded:wght@500;700&display=swap" rel="stylesheet">
<style>
:root { color-scheme: light; --bg:#fafafa; --panel:#ffffff; --panel2:#f3f3f3; --ink:#0a0a0a; --ink2:#1c1c1c; --ink3:#555; --line:#e4e4e4;
  --accent:#c8ff00; --hot:#e0006f; --band:#0a0a0a; --bandink:#f4f4f4; --shadow: 0 24px 60px -24px rgba(0,0,0,.28); }
@media (prefers-color-scheme: dark) {
  :root { color-scheme: dark; --bg:#17181a; --panel:#1e1f22; --panel2:#26272b; --ink:#ececec; --ink2:#dcdcdc; --ink3:#a6a6a8; --line:#34353a;
    --band:#0d0d0e; --bandink:#ececec; --shadow: 0 24px 60px -24px rgba(0,0,0,.7); }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 72px; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.6 "Inter", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased; }
img { max-width: 100%; height: auto; }
a { color: inherit; font-weight: 500; text-decoration: underline; text-decoration-color: var(--accent); text-decoration-thickness: .38em;
  text-underline-offset: -.2em; text-decoration-skip-ink: none; }
a:hover { background: var(--accent); color: #0a0a0a; text-decoration: none; }
::selection { background: var(--accent); color: #0a0a0a; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 0 24px; }
.wrap.narrow { max-width: 820px; }
h1, h2 { font-family: "Unbounded", "Inter", sans-serif; letter-spacing: -.02em; line-height: 1.12; }
h1 { font-size: clamp(34px, 6vw, 64px); font-weight: 700; margin: 18px auto 18px; max-width: 900px; }
h2 { font-size: clamp(26px, 3.6vw, 38px); font-weight: 700; margin: 0 0 20px; }
h3 { font-size: 19px; font-weight: 650; margin: 0 0 8px; line-height: 1.3; }
p { margin: 0 0 12px; }
code { font: 14px ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--panel2); padding: 1px 5px; }
kbd { font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; border: 1px solid var(--line); border-bottom-width: 2px; padding: 1px 6px;
  background: var(--panel); border-radius: 6px; }
section { padding: 88px 0; }
section.soft { background: var(--panel2); }
.intro { max-width: 760px; font-size: 18px; color: var(--ink2); margin-bottom: 32px; }

/* header */
.top { position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--bg) 86%, transparent); backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
.bar { display: flex; align-items: center; gap: 24px; height: 60px; }
.brand { display: inline-flex; align-items: center; gap: 10px; font: 700 18px "Unbounded", sans-serif; text-decoration: none; }
.brand:hover { background: none; color: inherit; }
.brand.small { font-size: 14px; gap: 8px; }
nav { display: flex; gap: 22px; margin-left: 12px; }
nav a { font-weight: 500; text-decoration: none; color: var(--ink2); padding: 2px 0; }
nav a:hover { background: none; color: var(--ink); box-shadow: inset 0 -.38em 0 var(--accent); }
.cta { margin-left: auto; display: flex; gap: 8px; }

/* pills */
.btn { display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; padding: 8px 16px; font-weight: 600; font-size: 15px;
  text-decoration: none; border: 1px solid transparent; white-space: nowrap; line-height: 1.2; }
.btn.lg { padding: 13px 24px; font-size: 16px; }
.btn.primary { background: var(--accent); color: #0a0a0a; }
.btn.primary:hover { background: #b4e600; }
.btn.ghost { color: var(--ink); }
.btn.ghost:hover { background: var(--panel2); color: var(--ink); }
.btn.outline { border-color: var(--ink); color: var(--ink); background: transparent; }
.btn.outline:hover { background: var(--ink); color: var(--bg); }
.btn.dark { background: #0a0a0a; color: #c8ff00; }
.btn.dark:hover { background: #222; color: #c8ff00; }
.btn.outline-dark { border-color: #0a0a0a; color: #0a0a0a; }
.btn.outline-dark:hover { background: #0a0a0a; color: #c8ff00; }
.gh { flex: none; }

/* hero */
.hero { text-align: center; padding: 72px 0 40px; }
.hero .mark { display: block; margin: 0 auto; box-shadow: 6px 6px 0 var(--ink); overflow: visible; }
.lede { font-size: clamp(17px, 2vw, 21px); color: var(--ink2); max-width: 760px; margin: 0 auto 28px; }
.actions { display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; }
.badges { list-style: none; padding: 0; margin: 28px 0 10px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.badges li { border: 1px solid var(--line); background: var(--panel); border-radius: 999px; padding: 5px 13px; font-size: 14px; font-weight: 500; }
.works { color: var(--ink3); font-size: 15px; margin: 0 0 44px; }
.works a { display: inline-flex; align-items: center; gap: 6px; vertical-align: middle; }
.appicon { width: 20px; height: 20px; max-width: none; flex: none; }   /* max-width: 100% let a flex row squash the icons */

/* screenshots */
.shot { margin: 0; background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); }
.shot .chrome { display: flex; gap: 6px; padding: 9px 12px; border-bottom: 1px solid var(--line); background: var(--panel2); }
.shot .chrome i { width: 10px; height: 10px; border-radius: 50%; background: var(--line); }
.shot img { display: block; width: 100%; }
/* the main screenshot on a laptop, drawn in CSS */
.macbook { position: relative; isolation: isolate; max-width: 1080px; margin: 0 auto; padding: 0 5.5% 12px; perspective: 2200px; }
.macbook::before { content: ""; position: absolute; z-index: -1; left: 0; right: 0; top: 6%; bottom: -6%;
  background: radial-gradient(closest-side, rgba(200,255,0,.5), rgba(200,255,0,0)); filter: blur(56px); }
.macbook .lid { position: relative; background: #0b0b0c; padding: 2.3% 2.3% 2.9%; transform-origin: 50% 100%;
  border-radius: clamp(10px, 1.7vw, 22px) clamp(10px, 1.7vw, 22px) 0 0;
  box-shadow: inset 0 0 0 1px #3b3c41, 0 0 0 1.5px #a9abb0, 0 30px 60px -30px rgba(0,0,0,.45); }
.macbook .lid::before { content: ""; position: absolute; top: 0.9%; left: 50%; width: 0.6%; aspect-ratio: 1; border-radius: 50%;
  background: #24262b; transform: translateX(-50%); box-shadow: inset 0 0 0 1px #34363c; }
.macbook .screen { overflow: hidden; background: #000; aspect-ratio: 16 / 10; border-radius: 2px; }
.macbook .screen img { display: block; width: 100%; height: 100%; object-fit: cover; object-position: top; }
.macbook .base { position: relative; margin: 0 -5.5%; padding-bottom: 2.3%;
  background: linear-gradient(180deg, #f4f4f6 0%, #dcdde0 30%, #b3b5ba 72%, #85878c 100%);
  border-radius: 2px 2px 50% 50% / 2px 2px 100% 100%; box-shadow: 0 22px 34px -16px rgba(0,0,0,.5); }
.macbook .base::before { content: ""; position: absolute; top: 0; left: 50%; width: 12%; height: 40%; transform: translateX(-50%);
  background: linear-gradient(180deg, #a9abb0, #cfd0d4); border-radius: 0 0 10px 10px; }
.macbook .base::after { content: ""; position: absolute; top: 0; left: 5.5%; right: 5.5%; height: 1px; background: rgba(0,0,0,.28); }

/* cards */
.grid { display: grid; gap: 16px; }
.grid.three { grid-template-columns: repeat(3, 1fr); }
.grid.two { grid-template-columns: repeat(2, 1fr); }
.card { background: var(--panel); border: 1px solid var(--line); padding: 24px; }
.card h3 { display: flex; gap: 10px; align-items: baseline; }
.card h3::before { content: ""; flex: none; width: 10px; height: 10px; background: var(--accent); transform: translateY(-1px); }
.card p:last-child { margin-bottom: 0; }
.card p { color: var(--ink2); }
h3.sub { font: 700 22px "Unbounded", sans-serif; margin: 72px 0 20px; }

/* features */
.feature { display: grid; grid-template-columns: 5fr 7fr; gap: 48px; align-items: center; margin: 0 0 88px; }
.feature.flip .text { order: 2; }
.feature .text h3 { font: 700 24px/1.2 "Unbounded", sans-serif; margin-bottom: 14px; }
.feature .text p { font-size: 17px; color: var(--ink2); }
.feature.solo { grid-template-columns: 1fr; border-left: 6px solid var(--accent); padding: 4px 0 4px 24px; max-width: 820px; }
.feature:last-of-type { margin-bottom: 0; }

/* apps */
.app { display: flex; gap: 20px; align-items: flex-start; }
.app > a { flex: none; line-height: 0; }
.app > a:hover { background: none; }
.appbig { width: 64px; height: 64px; flex: none; max-width: none; border-radius: 14px; }
.app ul { padding-left: 20px; margin: 0 0 12px; color: var(--ink2); }
.app li { margin: 4px 0; }

/* privacy band */
.band { background: var(--band); color: var(--bandink); }
.band h2 { color: #fff; }
.band .card { background: transparent; border-color: #2e2f33; }
.band .card h3 { color: #fff; }
.band .card p { color: #c9c9cc; }
.band a { color: #fff; }

/* install */
.steps { list-style: none; padding: 0; margin: 0; display: grid; gap: 16px; }
.step { display: grid; grid-template-columns: 44px 1fr; gap: 16px; background: var(--panel); border: 1px solid var(--line); padding: 24px; }
.step .num { width: 36px; height: 36px; border-radius: 50%; background: var(--accent); color: #0a0a0a; display: grid; place-items: center;
  font: 700 16px "Unbounded", sans-serif; }
.step .num.dot { background: transparent; border: 2px solid var(--ink); width: 20px; height: 20px; margin: 8px; }
.step ul, .step ol { padding-left: 22px; color: var(--ink2); }
.step ul { list-style: disc; }
.step li { margin: 6px 0; }
.step > div > :last-child { margin-bottom: 0; }
.code { position: relative; margin: 12px 0 16px; }
.code pre { margin: 0; background: #0f0f10; color: #ececec; padding: 18px 20px; padding-right: 88px; overflow-x: auto;
  font: 13.5px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; word-break: break-word; }
.code pre code { background: none; padding: 0; font: inherit; color: inherit; }
.code .copy { position: absolute; top: 10px; right: 10px; border: 0; border-radius: 999px; background: var(--accent); color: #0a0a0a;
  font: 600 13px "Inter", sans-serif; padding: 6px 13px; cursor: pointer; }
.more-link { margin-top: 24px; color: var(--ink3); }

/* what's new */
.changes { display: grid; gap: 16px; grid-template-columns: repeat(3, 1fr); }
.change { background: var(--panel); border: 1px solid var(--line); padding: 24px; }
.change h3 { font-size: 15px; color: var(--ink3); font-weight: 600; }
.change ul { padding-left: 18px; margin: 0; }
.change li { margin: 8px 0; color: var(--ink2); font-size: 15px; }
.change strong { color: var(--ink); }

/* questions */
details { border-bottom: 1px solid var(--line); padding: 18px 0; }
summary { cursor: pointer; font-weight: 650; font-size: 18px; list-style: none; display: flex; justify-content: space-between; gap: 16px; }
summary::-webkit-details-marker { display: none; }
summary::after { content: "+"; font: 500 22px/1 "Inter", sans-serif; color: var(--ink3); }
details[open] summary::after { content: "–"; }
details p { margin: 12px 0 0; color: var(--ink2); }

/* closing call to action and footer */
.final { background: var(--accent); color: #0a0a0a; text-align: center; padding: 72px 0; }
.final h2 { color: #0a0a0a; margin-bottom: 28px; }
.final a:hover { background: #0a0a0a; }
footer { border-top: 1px solid var(--line); padding: 28px 0; color: var(--ink3); font-size: 14px; }
.foot { display: flex; flex-wrap: wrap; gap: 16px 28px; align-items: center; }
.foot a { margin-left: auto; }

/* a little life: the logo sleeps, the laptop opens, sections rise into view (none when motion is reduced) */
@media (prefers-reduced-motion: no-preference) {
  .hero .mark { animation: breathe 5s ease-in-out infinite; }
  .mark .z1, .mark .z2 { animation: snooze 2.6s ease-in-out infinite; }
  .mark .z2 { animation-delay: .7s; }
  .hero h1, .hero .lede, .hero .actions, .hero .badges, .hero .works { animation: rise .8s cubic-bezier(.2,.7,.2,1) both; }
  .hero h1 { animation-delay: .05s; } .hero .lede { animation-delay: .15s; } .hero .actions { animation-delay: .25s; }
  .hero .badges { animation-delay: .32s; } .hero .works { animation-delay: .38s; }
  .macbook { animation: rise 1s cubic-bezier(.2,.7,.2,1) .35s both; }
  .macbook .lid { animation: lid-open 1.6s cubic-bezier(.16,.8,.24,1) .45s both; }
  .macbook .screen img { animation: screen-on 1s ease 1.3s both; }
  .macbook::before { animation: glow 2.4s ease 1.4s both; }
  .btn.primary { transition: transform .15s ease, background .15s ease; }
  .btn.primary:hover { transform: translateY(-1px); }
  .reveal { opacity: 0; transform: translateY(18px); transition: opacity .7s ease, transform .7s cubic-bezier(.2,.7,.2,1); }
  .reveal.in { opacity: 1; transform: none; }
}
@keyframes breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.04); } }
@keyframes snooze { 0%, 100% { transform: translate(0, 0); opacity: 1; } 55% { transform: translate(1.4px, -2px); opacity: .2; } }
@keyframes rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
@keyframes lid-open { from { transform: rotateX(-34deg); } to { transform: rotateX(0); } }
@keyframes screen-on { from { opacity: 0; filter: brightness(1.6); } to { opacity: 1; filter: none; } }
@keyframes glow { from { opacity: 0; } to { opacity: 1; } }

@media (max-width: 900px) {
  nav { display: none; }
  .grid.three, .grid.two, .changes { grid-template-columns: 1fr; }
  .feature, .feature.flip { grid-template-columns: 1fr; gap: 24px; margin-bottom: 64px; }
  .feature.flip .text { order: 0; }
  section { padding: 64px 0; }
}
@media (max-width: 560px) {
  .wrap { padding: 0 16px; }
  .cta .btn.ghost span { display: none; }
  .step { grid-template-columns: 1fr; padding: 20px 16px; }
  .app { flex-direction: column; }
  .code pre { padding-right: 20px; padding-top: 48px; }
  .foot a { margin-left: 0; }
}
</style>
</head>
<body>
"""


if __name__ == "__main__":
    args = sys.argv[1:]
    repo = Path(args[args.index("--repo") + 1]).expanduser() if "--repo" in args else Path.cwd()
    url = args[args.index("--url") + 1] if "--url" in args else None
    domain = args[args.index("--domain") + 1] if "--domain" in args else None
    print(f"build_site: wrote {build(repo, url, domain)}")
