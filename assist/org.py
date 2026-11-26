"""The organisation the user works for: the company layer of DESIGN-PERSONALISATION.md (16 Nov 2026).

Everything a colleague at the same company would set the same way lives in the org pack, one JSON file shared inside the
company: its name and domains, its org chart, products, mail rules and the mappings of its systems (CRM, Jira, roadmap).
Nothing about one company is written in the code; with no pack SleePO runs on the generic defaults below.

Where it comes from, later wins per key:
1. DEFAULTS
2. the pack file: settings 'org_pack' (a path), else env ASSIST_ORG_PACK, else <Assist folder>/org/pack.json
3. settings 'org' (a JSON object): this install's own overrides

Read at import by most modules, so a changed pack takes effect after a restart. Reads only, except save().
"""
import json
import os
import re
import sqlite3
import time
from pathlib import Path

DEFAULTS = {
    "name": "",                 # "Acme"
    "domains": [],              # the company's mail domains, the main one first
    "address_pattern": "",      # how a colleague's address is made: "{first}.{last}@example.com"
    "site": "",                 # the public site's host: "example.com"
    "company_names": [],        # how the company's own records start ("acme"), never a company SleePO links to
    "about": {},                # phrases about the company for prompts: {"what": ..., "strategy": ..., "review": ...}
}
TTL = 60
_cache = {}


def pack_path(con=None):
    """The org pack file this install reads."""
    from . import db
    p = None
    try:
        c = con
        if c is None:
            from .profile import read_only
            c = read_only(db.db_path())
        if c is not None:
            try:
                r = c.execute("SELECT value FROM settings WHERE key='org_pack'").fetchone()
                p = r[0] if r and r[0] else None
            finally:
                if con is None:
                    c.close()
    except sqlite3.Error:
        p = None
    return Path(os.path.expanduser(p or os.environ.get("ASSIST_ORG_PACK") or str(db.ASSIST / "org" / "pack.json")))


def _settings(con):
    try:
        r = con.execute("SELECT value FROM settings WHERE key='org'").fetchone()
        v = json.loads(r[0]) if r and r[0] else {}
        return v if isinstance(v, dict) else {}
    except (sqlite3.Error, ValueError):
        return {}


def _load(con):
    out = json.loads(json.dumps(DEFAULTS))
    p = pack_path(con)
    try:
        v = json.loads(p.read_text()) if p.exists() else {}
        out.update({k: x for k, x in (v if isinstance(v, dict) else {}).items() if not k.startswith("_")})
    except (OSError, ValueError):
        pass
    if con is not None:
        out.update({k: x for k, x in _settings(con).items() if x not in (None, "")})
    return out


def get(con=None):
    """The org: defaults, the pack, then this install's overrides."""
    if con is not None:
        return _load(con)
    from . import db
    from .profile import read_only
    key = str(db.db_path())
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    c = read_only(db.db_path())
    try:
        out = _load(c)
    finally:
        if c is not None:
            c.close()
    _cache[key] = (time.time(), out)
    return out


def section(key, default=None):
    """One part of the org pack (a list or dict), or default when the pack has none."""
    v = get().get(key)
    return default if v is None else v


def name(con=None):
    return get(con)["name"]


def domains():
    """The company's mail domains, lower case."""
    return [d.lower() for d in get()["domains"]]


def primary_domain():
    """The company's main mail domain ("acme.example"), or ""."""
    d = domains()
    return d[0] if d else ""


def is_primary_address(address):
    """True when an address is at the company's main domain."""
    d = primary_domain()
    return bool(d) and (address or "").lower().endswith("@" + d)


def sql_primary(col):
    """SQL: the column is an address at the company's main domain (false when there is none). Never a bare 0: in ORDER BY
    SQLite reads a number as a column position ("1st ORDER BY term out of range" without an org pack, 18 Nov 2026)."""
    d = primary_domain().replace("'", "''")
    return f"{col} LIKE '%@{d}'" if d else "(0=1)"


def address_for(full_name):
    """A colleague's likely address from their name and the pack's pattern, or "" ("Ann Noel" -> "ann.lee@example.com")."""
    pat = get()["address_pattern"]
    parts = (full_name or "").lower().split()
    if not pat or len(parts) < 2:
        return ""
    return pat.format(first=parts[0], last=parts[1])


def site_home():
    """A pattern for the company's own home page (a link to it is not a document), or one that matches nothing."""
    s = get()["site"]
    return re.compile(rf"^https?://(www\.)?{re.escape(s)}(/[a-z0-9-]*/?)?$" if s else r"(?!)", re.I)


def is_own_company(name):
    """True when a company record's name is the user's own company."""
    names = [re.escape(n) for n in get()["company_names"] if n]
    return bool(names) and bool(re.match(rf"(?:{'|'.join(names)})\b", name or "", re.I))


def own_prefixes():
    """Lower-case prefixes of the company's own names, for word lists ("acme")."""
    return tuple(n.lower() for n in get()["company_names"] if n)


def alt(key):
    """"|a|b": the pack's list of pattern fragments under key, to extend a generic pattern; "" when there are none."""
    return "".join("|" + x for x in (get().get(key) or []) if x)


def about(kind):
    """A phrase about the company for prompts, " (…)" with its brackets, or "" when the pack has none."""
    t = (get()["about"] or {}).get(kind) or ""
    return f" ({t})" if t else ""


def save(con, **fields):
    """Set this install's org overrides (settings 'org'); None removes one. Writes only when something changed."""
    r = con.execute("SELECT value FROM settings WHERE key='org'").fetchone()
    try:
        cur = json.loads(r[0]) if r and r[0] else {}
    except ValueError:
        cur = {}
    for k, v in fields.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown org field: {k}")
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    new = json.dumps(cur, ensure_ascii=False, sort_keys=True)
    if not r or r[0] != new:
        con.execute("INSERT INTO settings (key, value) VALUES ('org', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (new,))
        con.commit()
    _cache.clear()
    return cur
