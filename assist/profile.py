"""Who SleePO works for: the user's profile, the one place that knows their name, addresses and time zone
(16 Nov 2026, DESIGN-PERSONALISATION.md: nothing in the code names a person; every identity check reads this).

Each field comes from the first of these that has it:
1. an override set with use(): tests, or a run on someone else's behalf
2. settings key 'profile' (a JSON object), what the user set on System > Personalisation
3. the person marked is_me in people: their name, role, aliases and addresses
4. defaults: no identity, the Mac's time zone

The patterns below (ADDRESS, STRICT, LOOSE, NAME, GREETING, ADDRESSED) are built from the profile when used, so a module
may hold one at import (`SAM = db.ME_ADDRESS`) and still follow the profile. They never match anything until the profile
has a name or an address.

Reads only: nothing here writes to the database.
"""
import json
import os
import re
import sqlite3
import threading
import time

DEFAULTS = {
    "full_name": "",       # "Sam Doe"
    "first_name": "",      # from full_name when empty
    "emails": [],          # every address of the user's (work and personal), lower case
    "aliases": [],         # other names others use for them ("sam doe", "sam"), lower case
    "speaker_label": "",   # how Granola labels the user's microphone; full_name when empty
    "role": "",            # "Chief Product Officer"
    "role_short": "",      # "CPO"; role when empty
    "pronouns": "",        # "he/him", "she/her", "they/them"; prompts use the name when empty
    "timezone": "",        # IANA name; the Mac's time zone when empty
    "locale": "en-GB",
    "signoff": "",         # how emails are signed: "-Sam"; "-<first name>" when empty
    "spelling": "",        # "British" or "American"; from the locale when empty
    "meeting_days": "mon,tue,wed,thu,fri",   # days the user takes meetings
    "meeting_hours": "09:00-17:00",          # local hours the user takes meetings
    "meeting_minutes": 30,                   # their usual meeting length
    "second_timezone": "",                   # a second clock for proposed times ("America/Los_Angeles")
    "second_timezone_label": "",             # its short label ("PT"); the zone's abbreviation when empty
    "role_soul_file": "",                    # the page that says what good looks like in their role
    "role_soul_title": "",                   # its heading in prompts
    "manager": "",                           # their manager's name; from the people table (is_me's manager) when empty
    "manager_title": "",                     # their manager's title ("CEO"); likewise
    "manager_pronouns": "",                  # "he/him", "she/her"; prompts use the manager's name when empty
    "personal_meetings": "",                 # a pattern for meeting titles that are personal, not work ("robin|terry")
    "personal_meetings_title": "",           # how the prompts name them ("Sam <> Robin/Terry sync")
    "sensitive_names": "",                   # a pattern of names that make a meeting title an HR matter (kept as hr_legal)
    "private_files": "",                     # extra words that mark a local file private (never read)
    "forwarded_mailboxes": [],               # mailboxes forwarded to the user: mail only to them is noise ("pat")
    "plan_file": "",                         # the user's plan for the year (a V2MOM or OKRs); memory/context/plan.md when empty
    "plan_title": "",                        # its name in prompts ("V2MOM 2026"); "Plan" when empty
    "mail_since": "",                        # where the user's mail history starts (YYYY-MM-DD); 90 days back when empty
}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
AMERICAN = ("en-US", "en-CA", "en-PH")
TTL = 60   # seconds a profile read from the database is reused (use reload() after saving one)

_lock = threading.Lock()
_cache = {}        # database path -> (loaded at, profile)
_override = None


def system_timezone():
    """The Mac's time zone (IANA name), from TZ or /etc/localtime; UTC when neither says."""
    if os.environ.get("TZ") and "/" in os.environ["TZ"]:
        return os.environ["TZ"]
    try:
        p = os.path.realpath("/etc/localtime")
    except OSError:
        return "UTC"
    i = p.find("zoneinfo/")
    return p[i + len("zoneinfo/"):] if i >= 0 else "UTC"


def _lower_list(v):
    return [str(x).strip().lower() for x in (v or []) if str(x).strip()]


def complete(p):
    """The profile with every field present and the derived ones filled in."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (p or {}).items() if v not in (None, "")})
    out["full_name"] = (out["full_name"] or "").strip()
    out["emails"] = sorted(set(_lower_list(out["emails"])))
    out["aliases"] = sorted(set(_lower_list(out["aliases"])))
    out["first_name"] = (out["first_name"] or (out["full_name"].split()[0] if out["full_name"] else "")).strip()
    out["speaker_label"] = out["speaker_label"] or out["full_name"]
    out["role_short"] = out["role_short"] or out["role"]
    out["timezone"] = out["timezone"] or system_timezone()
    out["signoff"] = out["signoff"] or (f"-{out['first_name']}" if out["first_name"] else "")
    out["spelling"] = out["spelling"] or ("American" if out["locale"] in AMERICAN else "British")
    return out


def from_db(con):
    """The profile as stored: settings 'profile', with identity fields the user has not set taken from the is_me person."""
    out = {}
    try:
        r = con.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
        if r and r[0]:
            v = json.loads(r[0])
            out = v if isinstance(v, dict) else {}
    except (sqlite3.Error, ValueError):
        out = {}
    try:
        me = con.execute("SELECT id, name, role FROM people WHERE is_me=1 ORDER BY id LIMIT 1").fetchone()
        aliases = [a[0] for a in con.execute("SELECT alias FROM people_aliases WHERE person_id=?", (me[0],))] if me else []
    except sqlite3.Error:
        me, aliases = None, []
    try:
        mgr = con.execute("SELECT m.name, m.title FROM people p JOIN people m ON m.id=p.manager_id WHERE p.is_me=1 ORDER BY p.id LIMIT 1").fetchone() if me else None
    except sqlite3.Error:
        mgr = None
    if me:
        derived = {"full_name": me[1], "role": me[2], "emails": [a for a in aliases if "@" in a],
                   "aliases": [a for a in aliases if "@" not in a], "manager": mgr[0] if mgr else "", "manager_title": mgr[1] if mgr else ""}
        for k, v in derived.items():
            if v and not out.get(k):
                out[k] = v
    return out


def get(con=None):
    """The user's profile (complete). With con, read from that database now; without, from the default database, cached."""
    if _override is not None:
        return _override
    if con is not None:
        return complete(from_db(con))
    from . import db   # here, not at import: db imports this module for its ME_* patterns
    key = str(db.db_path())
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    c = read_only(db.db_path())
    if c is None:
        p = complete({})
    else:
        try:
            p = complete(from_db(c))
        except sqlite3.Error:
            p = complete({})
        finally:
            c.close()
    with _lock:
        _cache[key] = (time.time(), p)
    return p


def read_only(path):
    """A read-only connection to the database at path, or None when it does not exist: reading the profile never creates
    or changes a database (open tabs reload on every write, and a test's temporary folder must stay deletable)."""
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        return None
    try:
        return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def reload():
    """Forget the cached profile (after it was saved)."""
    with _lock:
        _cache.clear()
    _patterns.clear()


def use(p):
    """Override the profile for this process (tests; a CLI run for someone else). use(None) goes back to the database."""
    global _override
    _override = None if p is None else complete(p)
    _patterns.clear()


def name(con=None):
    return get(con)["full_name"]


def first_name(con=None):
    return get(con)["first_name"]


def zone(con=None):
    """The user's time zone as a ZoneInfo (UTC when the name is unknown)."""
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(get(con)["timezone"])
    except Exception:
        return ZoneInfo("UTC")


def meeting_window(con=None):
    """(weekday numbers the user meets on, (start hour, minute), (end hour, minute), minutes) from the profile."""
    p = get(con)
    days = [DAYS.index(d.strip()[:3].lower()) for d in str(p["meeting_days"]).split(",") if d.strip()[:3].lower() in DAYS]
    try:
        a, b = str(p["meeting_hours"]).split("-")
        start, end = tuple(int(x) for x in a.strip().split(":")), tuple(int(x) for x in b.strip().split(":"))
    except ValueError:
        start, end = (9, 0), (17, 0)
    return days or [0, 1, 2, 3, 4], start, end, int(p["meeting_minutes"] or 30)


def save(con, **fields):
    """Set profile fields (settings 'profile'); a value of None removes the field. Returns the stored fields."""
    r = con.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
    try:
        cur = json.loads(r[0]) if r and r[0] else {}
    except ValueError:
        cur = {}
    for k, v in fields.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown profile field: {k}")
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    new = json.dumps(cur, ensure_ascii=False, sort_keys=True)
    if not r or r[0] != new:   # an unchanged profile writes nothing (open tabs reload on every write)
        con.execute("INSERT INTO settings (key, value) VALUES ('profile', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (new,))
        con.commit()
    reload()
    return cur


def mic_label(con=None):
    """The speaker label Granola gives the user's own microphone."""
    return get(con)["speaker_label"]


# ---------------------------------------------------------------- patterns
NEVER = r"(?!)"


def _locals(p):
    """The local parts of the user's addresses ('sam.doe'), longest first."""
    return sorted({e.split("@", 1)[0] for e in p["emails"] if "@" in e and e.split("@", 1)[0]}, key=lambda s: (-len(s), s))


def _names(p):
    """Every name the user goes by, lower case, longest first: the full name, aliases, the first name."""
    ns = {p["full_name"].lower(), p["first_name"].lower(), p["speaker_label"].lower(), *p["aliases"]}
    return sorted({n for n in ns if n}, key=lambda s: (-len(s), s))


def _alt(xs):
    return "|".join(xs) if xs else NEVER


def build(kind, p):
    """The regular expression source for one kind of identity pattern, from a complete profile."""
    lb = r"(?<![\w.+-])"   # an address part starts a word ("milo" is not inside "alexander" or "xalex")
    locals_ = [lb + re.escape(x) for x in _locals(p)]
    full = [re.escape(n) for n in _names(p) if " " in n]      # whole names: "sam doe"
    single = [re.escape(n) for n in _names(p) if " " not in n]  # one word: "sam"
    first = re.escape(p["first_name"].lower()) if p["first_name"] else None
    if kind == "address":     # their address anywhere in a string
        return _alt([x + r"(?![\w-])" for x in locals_])
    if kind == "strict":      # their address, or a field that is exactly their full name
        return _alt([x + "@" for x in locals_] + [f"^{n}$" for n in full])
    if kind == "loose":       # also a field that is exactly one of their one-word names (speaker labels, attendees)
        return _alt([x + "@" for x in locals_] + [f"^{n}$" for n in full + single])
    if kind == "name":        # their full name or address anywhere (a name field, an author, a line of text)
        return _alt([rf"\b{n}\b" for n in full] + [x + r"(?![\w-])" for x in locals_])
    if kind == "greeting":    # their first name used to address them: "Hi Sam", "Sam-san", "Milo, Sam"; not inside an address
        return rf"(?<![\w.@]){first}(?:[- ]san|[- ]sama)?\b(?![.@]\w)" if first else NEVER
    if kind == "addressed":   # spoken to in a message body ("Sam, can you…", "@Sam", "Sam-san: …"), not spoken about
        if not first:
            return NEVER
        s = rf"{first}(?:[- ]san|[- ]sama)?"
        return (rf"@\s?{first}\b|(?:^|[.!?;]\s+){s}\s*[,:]|(?<![\w.@]){s}\s+(?:can|could|would|will|do|did|are|please|pls)\b"
                rf"|,\s*{s}\s*[?!]")
    if kind == "one_to_one":  # a 1:1 title: "Sam <> Milo", "Sam / Milo", "1:1", "1on1"
        lead = rf"^\s*{first}\s*(<>|/|-|&|x|and)\s*|" if first else ""
        return lead + r"\s*1\s*:\s*1\s*|\s*1on1\s*"
    if kind == "signature":   # a signature line of theirs at the end of an email: "-Sam", "Sam Doe", their role
        alts = ([rf"-?\s*{first}"] if first else []) + full + ([re.escape(p["role"].lower())] if p["role"] else [])
        return r"^\s*(" + "|".join(alts + [r"ceo", r"vp\b", r"director\b"]) + ")"
    raise ValueError(kind)


FLAGS = {"addressed": re.I | re.M}


_patterns = {}


def pattern(kind):
    """The compiled pattern of that kind for the current profile (case-insensitive)."""
    p = get()
    key = (kind, p["full_name"], p["first_name"], tuple(p["emails"]), tuple(p["aliases"]))
    hit = _patterns.get(key)
    if hit is None:
        hit = re.compile(build(kind, p), FLAGS.get(kind, re.I))
        _patterns[key] = hit
    return hit


class Pattern:
    """A compiled-regex stand-in whose pattern follows the profile. Has the methods the code uses on the old constants."""

    def __init__(self, kind):
        self.kind = kind

    @property
    def pattern(self):
        return pattern(self.kind).pattern

    def search(self, s, *a):
        return pattern(self.kind).search(s, *a)

    def match(self, s, *a):
        return pattern(self.kind).match(s, *a)

    def fullmatch(self, s, *a):
        return pattern(self.kind).fullmatch(s, *a)

    def sub(self, repl, s, count=0):
        return pattern(self.kind).sub(repl, s, count)

    def findall(self, s, *a):
        return pattern(self.kind).findall(s, *a)

    def __repr__(self):
        return f"profile.Pattern({self.kind!r})"


class FieldPattern:
    """A profile field that holds a pattern (case-insensitive), compiled when used; matches nothing when the field is empty."""

    def __init__(self, field, prefix="", suffix=""):
        self.field, self.prefix, self.suffix = field, prefix, suffix

    def _re(self):
        v = get()[self.field] or ""
        src = (self.prefix + ("|" if self.prefix and v else "") + v + self.suffix) if (v or self.prefix) else NEVER
        hit = _patterns.get(("field", src))
        if hit is None:
            hit = _patterns[("field", src)] = re.compile(src, re.I)
        return hit

    @property
    def pattern(self):
        return self._re().pattern

    def search(self, s, *a):
        return self._re().search(s, *a)

    def match(self, s, *a):
        return self._re().match(s, *a)


PERSONAL = FieldPattern("personal_meetings")   # personal meetings: out of scope everywhere


def forwarded_only(addresses):
    """True when some address is a mailbox forwarded to the user (the profile) and none is the user's own."""
    fw = [f.lower() for f in get()["forwarded_mailboxes"] if f]
    xs = [(a or "").lower() for a in addresses]
    return bool(fw) and any(f in x for x in xs for f in fw) and not any(ADDRESS.search(x) for x in xs)


ADDRESS = Pattern("address")
STRICT = Pattern("strict")
LOOSE = Pattern("loose")
NAME = Pattern("name")
GREETING = Pattern("greeting")
ADDRESSED = Pattern("addressed")
ONE_TO_ONE = Pattern("one_to_one")
SIGNATURE = Pattern("signature")


def names(con=None):
    """Every name the user goes by, lower case (full name, first name, speaker label, aliases)."""
    return _names(get(con))


def strip_address(text):
    """Text without a leading form of address to the user ("@Sam Doe, can you…" -> "can you…")."""
    p = get()
    if not p["first_name"]:
        return text
    rest = " ".join(p["full_name"].split()[1:])
    tail = rf"(?:\s+{re.escape(rest)})?" if rest else ""
    return re.sub(rf"^@?{re.escape(p['first_name'])}{tail}\b[,:]?\s*", "", text, flags=re.I)


def is_me(s):
    """True when a name, label or address is the user's (an exact name, or their address in it)."""
    s = (s or "").strip()
    return bool(s) and bool(LOOSE.search(s))


def mentions_me(s):
    """True when their full name or address appears anywhere in s."""
    return bool(s) and bool(NAME.search(s))


def _q(s):
    return "'" + s.replace("'", "''") + "'"


def sql_author(col, con=None):
    """A SQL condition: column `col` is the user (an exact name they go by, or their address in it)."""
    p = get(con)
    parts = []
    names = _names(p)
    if names:
        parts.append(f"lower(trim({col})) IN ({', '.join(_q(n) for n in names)})")
    parts += [f"lower({col}) LIKE {_q('%' + x + '@%')}" for x in _locals(p)]
    return "(" + " OR ".join(parts) + ")" if parts else "0"


def sql_mentions(col, con=None):
    """A SQL condition: their full name or address appears in column `col` (LIKE is case-insensitive for ASCII)."""
    p = get(con)
    parts = [f"{col} LIKE {_q('%' + n + '%')}" for n in _names(p) if " " in n] + [f"{col} LIKE {_q('%' + x + '@%')}" for x in _locals(p)]
    return "(" + " OR ".join(parts) + ")" if parts else "0"
