"""Company logos (Sam, 23 Oct 2026): each company's real mark on People › Companies.

Looked up by the company's web domain (its Salesforce website, else a domain it holds in org_domains) and cached as a file,
one per domain (table org_logos, files under Application Support/Assist/logos). Where from, best first: the icon the company's
own site declares (apple-touch-icon, or the largest icon it lists; a vector one counts as large), its /apple-touch-icon.png
only when it declares none (a WordPress server answers that address with WordPress's own logo), then Google's and
DuckDuckGo's site-icon services. A content management system's default icon (WordPress's "W") is never a company's logo. The largest image wins, early once one is 120 px or more; nothing usable
leaves the initials and is tried again after 30 days. Only the domain leaves the Mac (company domains are not personal data);
free-mail domains and Acme are never looked up, and nothing is fetched but images and the site's home page.

  assist company-logos [--redo] [--limit N]
"""
import hashlib
import re
import struct
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import entities

LOGO_DIR = Path.home() / "Library" / "Application Support" / "Assist" / "logos"
RETRY_DAYS = 30
GOOD = 120          # stop looking once a logo this large is found
SMALLEST = 16
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      "Accept": "text/html,image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5"}
EXT = {"png": "png", "ico": "ico", "jpeg": "jpg", "gif": "gif", "webp": "webp", "svg": "svg"}
# default icons of content management systems, by MD5 (found 23 Oct 2026: WordPress's "W" on three sites, another on two)
GENERIC = {"dcab89b8e04bf53fcd7f6a44a8cb4fae", "000bf649cc8f6bf27cfb04d1bcdcd3c7", "e8f5f175ac4ba5f256cfc0a59dad15cb", "6ff1009e1215a17f2ac9420bed6a164d"}
TYPES = {"png": "image/png", "ico": "image/x-icon", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def host_of(url):
    """'https://company480.co.uk/' -> 'company480.co.uk' (None for anything that is not a web address)."""
    u = (url or "").strip().lower()
    if not u:
        return None
    if "//" not in u:
        u = "https://" + u
    h = (urllib.parse.urlsplit(u).hostname or "").strip(".")
    return h if "." in h and re.fullmatch(r"[a-z0-9.-]+", h) else None


def _usable(domain):
    return bool(domain) and domain not in entities.FREE_MAIL and domain not in entities.INTERNAL


def domains(con, orgs, groups):
    """{company id: (domain, host)} for each company: the website of one of its Salesforce records (the company's own first),
    else a domain one of its records holds (mail domain, Salesforce mail domain). host is where its site is fetched from."""
    held = {}
    for d, o, s in con.execute("SELECT domain, org_id, source FROM org_domains"):
        held.setdefault(o, []).append((0 if s == "salesforce" else 1, d))
    out = {}
    for rid, members in groups.items():
        ordered = [rid] + [m for m in members if m != rid]
        site = next((orgs[m].get("website") for m in ordered if orgs[m].get("website")), None)
        if site and _usable(entities.registrable(site)):
            out[rid] = (entities.registrable(site), site)
            continue
        for m in ordered:
            ds = [d for _, d in sorted(held.get(m, [])) if _usable(d)]
            if ds:
                out[rid] = (ds[0], ds[0])
                break
    return out


def cached(con):
    """{domain: (file name, width, fetched_at)} for the logos on disk."""
    return {d: (f, w, t) for d, f, w, t in con.execute("SELECT domain, file, width, fetched_at FROM org_logos WHERE file IS NOT NULL")
            if (LOGO_DIR / f).exists()}


# ---------------------------------------------------------------- fetching (network only; no database in the threads)
def _get(url, limit=2_000_000):
    if not url.startswith(("https://", "http://")):
        raise ValueError("not a web address")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=8) as r:
        return r.geturl(), r.status, r.read(limit)


def kind_and_size(b):
    """(kind, size in px) of an image by its bytes; (None, 0) for anything else (an HTML error page, a redirect body)."""
    if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24:
        w, h = struct.unpack(">II", b[16:24])
        return "png", min(w, h)
    if b[:4] == b"\x00\x00\x01\x00" and len(b) >= 6:
        n = struct.unpack("<H", b[4:6])[0]
        sizes = [(b[6 + 16 * i] or 256) for i in range(n) if len(b) >= 8 + 16 * i]
        return "ico", max(sizes, default=0)
    if b[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                break
            marker, seg = b[i + 1], struct.unpack(">H", b[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", b[i + 5:i + 9])
                return "jpeg", min(w, h)
            i += 2 + seg
        return "jpeg", 0
    if b[:6] in (b"GIF87a", b"GIF89a") and len(b) >= 10:
        w, h = struct.unpack("<HH", b[6:10])
        return "gif", min(w, h)
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp", 64
    head = b[:1000].lstrip().lower()
    if head.startswith((b"<svg", b"<?xml")) and b"<svg" in b[:2000].lower():
        return "svg", 512
    return None, 0


def _site_icons(host):
    """The icons a site's home page declares, best first (the usual guesses when it declares none), and whether all it
    declares is WordPress's built-in icon: such a site has no logo of its own, and the icon services only repeat WordPress's."""
    found, wordpress = [], False
    for base in dict.fromkeys([f"https://{host}/", f"https://www.{host}/" if not host.startswith("www.") else None]):
        if not base:
            continue
        try:
            final, status, page = _get(base, 800_000)
        except Exception:
            continue
        html = page.decode("utf-8", "ignore")
        for tag in re.findall(r"<link\b[^>]*>", html, re.I):
            rel = (re.search(r"""rel\s*=\s*["']?([^"'>]+)""", tag, re.I) or [None, ""])[1].lower()
            href = (re.search(r"""href\s*=\s*["']([^"']+)""", tag, re.I) or [None, ""])[1]
            if "icon" not in rel or not href or href.startswith("data:"):
                continue
            if "wp-includes" in href:
                wordpress = True
                continue
            sz = re.search(r"""sizes\s*=\s*["']?(\d+)""", tag, re.I)
            score = 512 if href.lower().split("?")[0].endswith(".svg") else int(sz[1]) if sz else (180 if "apple" in rel else 32)
            found.append((score, urllib.parse.urljoin(final, href)))
        if not found and not wordpress:   # guesses only for a site that declares nothing
            root = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(final))
            found += [(180, root + "/apple-touch-icon.png"), (16, root + "/favicon.ico")]
        break
    return [u for _, u in sorted(found, key=lambda x: -x[0])], wordpress and not found


def fetch(domain, host):
    """The best logo for one company: (bytes, kind, size, source) or None."""
    google = ("https://t1.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL"
              f"&url=https://{urllib.parse.quote(host)}&size=256")
    site, generic = _site_icons(host)
    tries = [(u, "site") for u in site] + ([] if generic else [(google, "google"), (f"https://icons.duckduckgo.com/ip3/{urllib.parse.quote(domain)}.ico", "duckduckgo")])
    best, seen = None, set()
    for url, source in tries:
        if url in seen:
            continue
        seen.add(url)
        try:
            _, status, b = _get(url)
        except Exception:
            continue
        kind, size = kind_and_size(b)
        if status != 200 or not kind or size < SMALLEST or hashlib.md5(b).hexdigest() in GENERIC:
            continue
        if not best or size > best[2]:
            best = (b, kind, size, source)
        if size >= GOOD:
            break
    return best


# ---------------------------------------------------------------- the run
def wanted(con):
    """{domain: host} for every listed company but Acme."""
    from . import companies
    orgs = companies._orgs(con)
    listed = {c["id"] for c in companies.listing(con, logos=False) if c["relation"] != "ours"}
    groups = {}
    for oid in orgs:
        groups.setdefault(companies.root(orgs, oid), []).append(oid)
    return dict(domains(con, orgs, {r: groups[r] for r in listed if r in groups}).values())


def prune(con, want):
    """Logos no listed company uses any more (a company merged away, a domain corrected) go, file and row."""
    gone = [(d, f) for d, f in con.execute("SELECT domain, file FROM org_logos") if d not in want]
    for d, f in gone:
        if f and (LOGO_DIR / f).exists():
            (LOGO_DIR / f).unlink()
        con.execute("DELETE FROM org_logos WHERE domain=?", (d,))
    return len(gone)


def plan(con, redo=False, want=None):
    """(domain, host) of every listed company whose logo is missing (never tried, or not found more than 30 days ago)."""
    want = wanted(con) if want is None else want
    if redo:
        return sorted(want.items())
    retry = (datetime.now(timezone.utc) - timedelta(days=RETRY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    have = cached(con)
    tried = {d for d, t in con.execute("SELECT domain, fetched_at FROM org_logos WHERE file IS NULL AND fetched_at >= ?", (retry,))}
    return sorted((d, h) for d, h in want.items() if d not in have and d not in tried)


def run(con, redo=False, limit=None, workers=8, log=print, only=None):
    want = wanted(con)
    pruned = prune(con, want)
    todo = plan(con, redo or bool(only), want)
    todo = [x for x in todo if not only or x[0] in only][:limit] if limit else [x for x in todo if not only or x[0] in only]
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    found = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (domain, host), got in zip(todo, pool.map(lambda x: _safe_fetch(*x), todo)):
            if got:
                b, kind, size, source = got
                name = f"{domain}.{EXT[kind]}"
                for old in LOGO_DIR.glob(f"{domain}.*"):
                    old.unlink()
                (LOGO_DIR / name).write_bytes(b)
                found += 1
            else:
                name, size, source = None, None, None
                for old in LOGO_DIR.glob(f"{domain}.*"):   # a redo that finds nothing usable drops the old file too
                    old.unlink()
            con.execute("INSERT INTO org_logos (domain, file, width, source, fetched_at) VALUES (?,?,?,?,?) ON CONFLICT(domain) DO UPDATE SET "
                        "file=excluded.file, width=excluded.width, source=excluded.source, fetched_at=excluded.fetched_at",
                        (domain, name, size, source, _now()))
    con.commit()
    log(f"company logos: {len(todo)} looked up · {found} found · {len(todo) - found} without one" + (f" · {pruned} no longer used" if pruned else ""))
    return {"looked_up": len(todo), "found": found}


def _safe_fetch(domain, host):
    try:
        return fetch(domain, host)
    except Exception:
        return None
