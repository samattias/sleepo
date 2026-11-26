"""Entity linking: every item is tied to the people, organisations and initiatives it is about, when it comes in.

Links live in `mentions` (ref_type='item'), so a person, an account or an initiative has one timeline across mail,
chat, meetings, calendar, documents and Salesforce, and prep, the brief and search can pull in everything connected.

How each link is made (strongest first; confidence in brackets):
- People: email addresses on mail (from/to/cc) and calendar invites, resolved through people_aliases (1.0); the sender
  already resolved at ingest (1.0); chat authors by full name (0.9); a meeting inherits its calendar event's people (1.0).
  A name written in the text: a full name or another full name they go by (KNOWN_ALIASES: Quinn Dalton, Sage Gilmore) anywhere (0.7); a first name only when one person has it and it is not an ordinary word, in notes, chats,
  invites and subject lines (0.6). Never "Glen" or "Finley": the company has four Daniels and two Scotts. Shared mailboxes
  (jira@, gitlab@, lists) are nobody's alias; the person named on a Jira or GitLab notification is a hint only (0.5).
- Organisations: Salesforce accounts become orgs (kind 'account'); an opportunity links to its account (1.0). External
  email domains map to an org: to the Salesforce account whose name matches the domain (e.g. paulmann-licht.de ->
  Company 245), otherwise to an org named after the domain (kind 'external'). Mail and invites link to the orgs of
  their addresses (0.9). An account named in a subject or text links at 0.6. Acme itself is never linked (internal).
- Initiatives: the initiative's match_regex over subject and text (0.6), as commitments and decisions already are.

Incremental: items newer than the last pass (by id) or re-pulled since it are linked; `link(con, full=True)` redoes all.
Company and deal data only from Salesforce (org policy): orgs carry the account name, nothing about individuals.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from . import db
from . import org
from .promptkit import USER   # the user in prompt text (assist/profile.py)

ME = db.ME_STRICT   # the one definition, assist/db.py
DM_KINDS = ("dm", "oneOnOne")
CONVERSATION_KINDS = DM_KINDS + ("group", "meeting")   # chats with members; channels are broadcast and link by author only


def conversation_names(name, kind):
    """The people a chat is named after: "DM Noel Osborne", "Noel Osborne DM", "group chat Gray, Noel", "Sam / Noel",
    "Rowan Lowell + 4 (group chat)". Meeting chats are named after the meeting, not its people."""
    n = (name or "").strip()
    if kind == "meeting" or n.lower().startswith("meeting chat"):
        return []
    n = re.sub(r"^(dm|chat with|group chat)\s+|\s+dm$|\s*\+\s*\d+.*$|\s*\(group chat\)$", "", n, flags=re.I)
    return [x.strip() for x in re.split(r",|&|/|\band\b", n) if x.strip()]
INTERNAL = set(org.domains())   # the company's own mail domains (the org pack)
# senders that are systems, not organisations (their domains never become orgs)
SYSTEM = re.compile(r"no-?reply|notifications?|mailer|bounce|digest|calendar|marketing|newsletter|news\.|^e\.|^mg\.|^mail\.|^email\.|"
                    r"microsoft|office365|sharepoint|teams\.mail|gitlab|atlassian|jira|salesforce|granola|surveymonkey|"
                    r"linkedin|google|zoom|docusign|slack|hubspot|mailchimp|sendgrid|amazonses|intralinks" + org.alt("noise_senders"), re.I)
FREE_MAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "me.com", "live.com", "aol.com", "proton.me",
             "protonmail.com", "gmx.de", "gmx.net", "web.de", "orange.fr", "free.fr", "btinternet.com"}
LEGAL = re.compile(r"\b(gmbh|ag|inc|llc|ltd|limited|plc|sa|sas|s\.a\.|srl|bv|nv|ab|as|oy|kk|k\.k\.|co|corp|corporation|company|group|"
                   r"holding|holdings|the|of|and|und|et)\b\.?", re.I)
TWO_LEVEL = {"co.uk", "co.jp", "com.au", "co.nz", "com.br", "co.in", "ne.jp", "or.jp", "ac.uk", "gov.uk", "com.sg", "com.cn"}
# under a two-letter country code these are suffixes too (gov.za, com.pl, ac.ae, org.uk): the company is the label before them
SLD = {"com", "co", "org", "net", "gov", "edu", "ac", "or", "ne", "go", "mil", "gob", "gouv", "nic", "ltd", "plc", "sch", "nhs", "gv", "govt"}
STEM_STOP = {"group", "global", "consulting", "services", "systems", "solutions", "partners", "international", "digital",
             "technologies", "technology", "software", "bank", "insurance", "health", "energy", "capital", "data", "process"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# How a person, organisation or initiative is linked to an item, strongest first. Shown on timelines ("from", "spoke",
# "mentioned") and used to keep one role per link when several apply.
ROLE_RANK = {"from": 10, "author": 10, "speaker": 9, "dm": 9, "organizer": 8, "to": 8, "attendee": 7, "cc": 6, "invitee": 6,
             "account": 6, "discussed": 7, "owner": 8, "filed": 5, "shared": 7, "member": 4, "domain": 4, "actor": 3, "mentioned": 2, "keyword": 1}


def ensure_schema(con):
    have_m = {r[1] for r in con.execute("PRAGMA table_info(mentions)")}
    for col in ("role", "source", "verdict", "reason", "updated_at"):
        if have_m and col not in have_m:
            con.execute(f"ALTER TABLE mentions ADD COLUMN {col} TEXT")
    con.execute("CREATE TABLE IF NOT EXISTS org_domains (domain TEXT PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES orgs(id), source TEXT)")
    con.execute("CREATE INDEX IF NOT EXISTS mentions_entity ON mentions(entity_type, entity_id)")
    have = {r[1] for r in con.execute("PRAGMA table_info(orgs)")}
    for col, typ in (("source", "TEXT"), ("region", "TEXT"), ("updated_at", "TEXT")):
        if col not in have:
            con.execute(f"ALTER TABLE orgs ADD COLUMN {col} {typ}")


def public_suffix(domain):
    """'gov.za', 'co.uk': a suffix many organisations share, never one company's domain."""
    parts = (domain or "").lower().strip(".").split(".")
    return len(parts) == 2 and (domain.lower() in TWO_LEVEL or (len(parts[1]) == 2 and parts[0] in SLD))


def registrable(domain):
    parts = (domain or "").lower().strip(".").split(".")
    if len(parts) >= 3 and public_suffix(".".join(parts[-2:])):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else (domain or "").lower()


def domain_of(addr):
    m = re.search(r"@([A-Za-z0-9.\-]+)$", (addr or "").strip())
    return m.group(1).lower() if m else ""


def core_name(name):
    """'Company 245' -> 'paulmann licht'; used to match accounts to domains and to text."""
    n = re.sub(r"\(.*?\)", " ", name or "")
    n = LEGAL.sub(" ", n)
    n = re.sub(r"[^A-Za-z0-9& ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip().lower()


def _org(con, name, kind, source, region=None):
    row = con.execute("SELECT id FROM orgs WHERE name=?", (name,)).fetchone()
    if row:
        con.execute("UPDATE orgs SET kind=COALESCE(kind, ?), source=COALESCE(source, ?), region=COALESCE(?, region), updated_at=? WHERE id=?",
                    (kind, source, region, _now(), row["id"]))
        return row["id"]
    return con.execute("INSERT INTO orgs (name, kind, source, region, updated_at) VALUES (?,?,?,?,?)", (name, kind, source, region, _now())).lastrowid


def sync_orgs(con):
    """Salesforce accounts -> orgs (kind 'account'). Returns {core name: org id} for matching."""
    accounts = {}
    for (p,) in con.execute("SELECT payload FROM items WHERE source_id='salesforce' AND kind='opportunity'"):
        d = json.loads(p or "{}")
        a = (d.get("account") or "").strip()
        if a:
            accounts.setdefault(a, d.get("account_region"))
    cores = {}
    for name, region in accounts.items():
        oid = _org(con, name, "account", "salesforce", region)
        c = core_name(name)
        if len(c) >= 3:
            cores.setdefault(c, oid)
    for r in con.execute("SELECT id, name FROM orgs WHERE kind NOT IN ('account', 'external', 'internal')"):   # partners, investors, advisors
        c = core_name(r["name"])
        if len(c) >= 3:
            cores[c] = r["id"]
    _KINDS.clear()
    _KINDS.update({r["id"]: r["kind"] for r in con.execute("SELECT id, kind FROM orgs")})
    return cores


_KINDS = {}


def _match_account(stem, cores):
    """Domain stem -> org id. An exact name match wins; then a partner/investor/advisor record; otherwise only a unique match."""
    if len(stem) < 4 or stem in STEM_STOP:
        return None
    exact = {oid for c, oid in cores.items() if c.replace(" ", "") == stem}
    if len(exact) == 1:
        return next(iter(exact))
    hits = {oid for c, oid in cores.items()
            if c.replace(" ", "").startswith(stem) or c.split(" ")[0] == stem or stem.startswith(c.replace(" ", ""))}
    hits |= {oid for c, oid in cores.items() if len(stem) >= 6 and stem in c.replace(" ", "")}
    if len(hits) > 1:
        rel = {h for h in hits if _KINDS.get(h) not in (None, "account", "external", "internal")}
        hits = rel if len(rel) == 1 else hits
    return next(iter(hits)) if len(hits) == 1 else None


def org_for_domain(con, domain, cores, create=True):
    if not domain:
        return None
    reg = registrable(domain)
    if reg in INTERNAL or reg in FREE_MAIL or SYSTEM.search(domain):
        return None
    row = con.execute("SELECT org_id FROM org_domains WHERE domain=?", (reg,)).fetchone()
    if row:
        return row["org_id"]
    stem = reg.split(".")[0]
    oid = _match_account(stem.replace("-", ""), cores) or _match_account(stem.split("-")[0], cores)
    src = "salesforce-match"
    if not oid:
        if not create:
            return None
        oid, src = _org(con, stem.replace("-", " ").title(), "external", "domain"), "domain"
    con.execute("INSERT OR IGNORE INTO org_domains (domain, org_id, source) VALUES (?,?,?)", (reg, oid, src))
    return oid


# Names people go by that their profile name does not give: the display name on their mailbox, a nickname, a second mailbox.
# Checked against mail, chat and invites and confirmed by Sam on 12 Oct 2026; add a line when someone turns up under another name.
KNOWN_ALIASES = org.section("people_aliases", {})   # other full names and addresses people go by (the org pack)
# Mailboxes that send on behalf of many people (Jira, GitLab, distribution lists): never an alias of one person.
WARNING = re.compile(r"\s*(WARNING! Possible Impersonation|\[?External\]?\s*WARNING)", re.I)   # AppRiver banners name whoever is impersonated
SHARED = re.compile(r"^(jira|gitlab|confluence|bitbucket|github|noreply|no-reply|donotreply\w*|notifications?|hr|"
                    r"support|info|sales|admin" + org.alt("shared_mailboxes") + r")@", re.I)   # the company's own lists: the org pack
_LOWER_WORDS = None


def _common_words():
    """Ordinary words (lower-case dictionary entries): 'mark', 'will', 'lane'. Proper names like 'Rowan' or 'Gray' are not in it."""
    global _LOWER_WORDS
    if _LOWER_WORDS is None:
        try:
            with open("/usr/share/dict/words") as f:
                _LOWER_WORDS = {w.strip() for w in f if w[:1].islower()}
        except OSError:
            _LOWER_WORDS = set()
    return _LOWER_WORDS


def personal_address(addr):
    a = (addr or "").strip().lower()
    return "@" in a and not SHARED.search(a) and not SYSTEM.search(a.split("@", 1)[1])


def ascii_name(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def clean_name(s):
    """A display name as a person's name: 'Gray Selby (Jira)', 'Dex Norwood (@mcintken)', 'Group: ELT', 'Irving, Quinn', 'Quinn.irving'."""
    s = re.sub(r"\s*\((?:jira|confluence|@[^)]*|external|guest)\)\s*$", "", (s or "").strip().strip("'\""), flags=re.I)
    s = re.sub(r"^group:\s*", "", s, flags=re.I)
    if s.count(",") == 1 and "@" not in s:
        last, first = [x.strip() for x in s.split(",")]
        s = f"{first} {last}"
    if re.fullmatch(r"[A-Za-z]+\.[A-Za-z][A-Za-z\-]+", s):
        s = s.replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


def sync_aliases(con, log=print):
    """Keep people_aliases honest: drop shared mailboxes someone's name got attached to (a Jira mail 'from Ash Rowe' is from
    jira@), add the known other names, the plain-letter spelling of every name, and any firstname.lastname@ address seen on
    mail or invites for a person who has it. Returns (added, removed)."""
    removed = 0
    for (a,) in con.execute("SELECT alias FROM people_aliases WHERE alias LIKE '%@%'").fetchall():
        if not personal_address(a):
            con.execute("DELETE FROM people_aliases WHERE alias=?", (a,))
            removed += 1
    before = con.execute("SELECT COUNT(*) FROM people_aliases").fetchone()[0]
    people = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM people")}
    for name, alts in KNOWN_ALIASES.items():
        if name in people:
            for a in alts:
                con.execute("INSERT OR IGNORE INTO people_aliases (alias, person_id) VALUES (?, ?)", (a.lower(), people[name]))
    by_local = {}
    for name, pid in people.items():
        plain = ascii_name(name).lower()
        for v in {plain, plain.replace("-", " ")}:
            con.execute("INSERT OR IGNORE INTO people_aliases (alias, person_id) VALUES (?, ?)", (v, pid))
        parts = plain.split()
        if len(parts) >= 2:
            for local in {f"{parts[0]}.{''.join(parts[1:])}", f"{parts[0]}.{'-'.join(parts[1:])}", f"{parts[0]}.{parts[-1]}"}:
                by_local.setdefault(local, set()).add(pid)
    alias = _people_by_alias(con)
    seen = set()
    for r in con.execute("SELECT from_address, to_json, cc_json FROM mail_messages"):
        seen.add((r["from_address"] or "").lower())
        for col in ("to_json", "cc_json"):
            seen |= {(x.get("address") or "").lower() for x in json.loads(r[col] or "[]")}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='meeting_people'").fetchone():
        seen |= {r["email"].lower() for r in con.execute("SELECT email FROM meeting_people WHERE email IS NOT NULL")}
    for r in con.execute("SELECT payload FROM items WHERE kind='event' AND payload LIKE '%attendees%'"):
        try:
            seen |= {a.lower() for a in json.loads(r["payload"]).get("attendees") or [] if isinstance(a, str)}
        except (ValueError, AttributeError):
            pass
    for a in seen:
        if a in alias or not personal_address(a) or domain_of(a) not in INTERNAL:
            continue
        local = ascii_name(a.split("@")[0])
        for key in (local, re.sub(r"\.([a-z])[a-z]*\.", r".", local)):   # first.middle.last
            pids = by_local.get(key) or set()
            if not pids and alias.get(key.replace(".", " ")):   # noel.barker@ for someone also known as Noel Barker
                pids = {alias[key.replace(".", " ")]}
            if len(pids) == 1:
                con.execute("INSERT OR IGNORE INTO people_aliases (alias, person_id) VALUES (?, ?)", (a, next(iter(pids))))
                break
    added = con.execute("SELECT COUNT(*) FROM people_aliases").fetchone()[0] - before
    if added or removed:
        log(f"entities: aliases +{added} -{removed}")
    return added, removed


def _people_by_alias(con):
    return {r["alias"]: r["person_id"] for r in con.execute("SELECT alias, person_id FROM people_aliases")}


def _me_id(con):
    r = con.execute("SELECT id FROM people WHERE is_me=1").fetchone()
    return r["id"] if r else None


_WORDS = None


def _words():
    global _WORDS
    if _WORDS is None:
        try:
            _WORDS = {w.strip().lower() for w in open("/usr/share/dict/words")}
        except OSError:
            _WORDS = set()
    return _WORDS


def bounded(pattern):
    """Each top-level alternative of an initiative regex as a whole word: 'org' must not match inside 'organisation'."""
    alts, depth, cur = [], 0, ""
    for ch in pattern:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            alts.append(cur); cur = ""
        else:
            cur += ch
    alts.append(cur)
    return "|".join(rf"(?<![A-Za-z0-9])(?:{a})(?![A-Za-z0-9])" for a in alts if a)


def _account_regex(con):
    """One regex over distinctive account names (as written), for text mentions."""
    names = {}
    for r in con.execute("SELECT id, name FROM orgs WHERE kind='account'"):
        core = re.sub(LEGAL, " ", re.sub(r"\(.*?\)", " ", r["name"]))
        core = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9& .\-]+", " ", core)).strip(" .-")
        if len(core) >= 5 and core.lower() not in STEM_STOP and not core.lower().startswith(org.own_prefixes() + ("test",)) \
                and not (" " not in core and core.lower() in _words()):   # "Pilot", "Challenge": ordinary words, not evidence
            names.setdefault(core, r["id"])
    if not names:
        return None, {}
    pat = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![A-Za-z0-9])")
    return pat, names


def link(con, full=False, log=print):
    ensure_schema(con)
    cores = sync_orgs(con)
    sync_aliases(con, log=log)
    alias = _people_by_alias(con)
    me = _me_id(con)
    first_counts = {}
    for (n,) in con.execute("SELECT name FROM people"):
        first_counts[n.split(" ")[0].lower()] = first_counts.get(n.split(" ")[0].lower(), 0) + 1
    full_names = {r["name"].lower(): r["id"] for r in con.execute("SELECT id, name FROM people")}
    inis = []
    has_active = "active" in {r[1] for r in con.execute("PRAGMA table_info(initiatives)")}
    for r in con.execute("SELECT id, match_regex FROM initiatives WHERE match_regex IS NOT NULL AND match_regex != ''" + (" AND COALESCE(active, 1)=1" if has_active else "")):
        try:
            inis.append((r["id"], re.compile(bounded(r["match_regex"]))))
        except re.error:
            pass
    acct_re, acct_ids = _account_regex(con)

    mark = con.execute("SELECT value FROM settings WHERE key='entities:mark'").fetchone()
    mark = json.loads(mark["value"]) if mark and not full else {"id": 0, "at": ""}
    rows = con.execute("SELECT id, source_id, kind, from_person_id, from_name, subject, text, payload, pulled_at FROM items "
                       "WHERE noise=0 AND (id > ? OR pulled_at > ?)", (mark["id"], mark["at"] or "")).fetchall()
    mail = {r["item_id"]: r for r in con.execute("SELECT item_id, from_address, to_json, cc_json FROM mail_messages")}
    chat = {r["item_id"]: r for r in con.execute("SELECT item_id, source_id, COALESCE(conversation_id, conversation_name) AS conv, conversation_kind, author "
                                                  "FROM chat_messages")}
    msrc = True   # ensure_schema() adds source/role/verdict/reason
    has_speakers = bool(con.execute("SELECT 1 FROM sqlite_master WHERE name='meeting_speakers'").fetchone())
    if full:   # re-resolve domains from scratch (matching rules may have improved)
        con.execute("DELETE FROM org_domains WHERE source IN ('domain', 'salesforce-match')")
    if full:   # only this linker's own rows; links someone confirmed or set by hand (verdict) stay
        con.execute("DELETE FROM mentions WHERE ref_type='item'" + (" AND COALESCE(source, 'entities')='entities' AND verdict IS NULL" if msrc else ""))

    def person(addr_or_name):
        k = (addr_or_name or "").strip().lower()
        if not k or ("@" in k and not personal_address(k)):   # jira@, gitlab@, a distribution list: nobody in particular
            return None
        if "@" not in k:
            k = clean_name(addr_or_name).lower()
        pid = alias.get(k) or full_names.get(k) or alias.get(ascii_name(k))
        if not pid and "@" in k:   # firstname.lastname@ -> "firstname lastname"
            pid = full_names.get(re.sub(r"@.*$", "", k).replace(".", " ").replace("_", " "))
        return pid if pid and pid != me else None

    # Names that can be found in text: every full name and other full-length name (Quinn Dalton, Dale
    # Bristow), and a first name as written ("Noel") when only one person has it and it is not an ordinary word.
    note_names = {n: pid for n, pid in alias.items() if "@" not in n and " " in n and pid != me}
    firsts = {}
    for n, pid in full_names.items():
        firsts.setdefault(n.split(" ")[0], set()).add(pid)
    # Sam's crosses teach it: a first name he has rejected twice as a link to that person is no longer matched on its own
    taught = {r[0] for r in con.execute("SELECT entity_id FROM mentions WHERE entity_type='person' AND verdict='rejected' AND role='mentioned' "
                                        "AND reason LIKE 'first name:%' GROUP BY entity_id HAVING COUNT(*) >= 2")}
    note_firsts = {f.capitalize(): next(iter(ids)) for f, ids in firsts.items()
                   if len(ids) == 1 and next(iter(ids)) not in taught and len(f) >= 3 and f not in _common_words() and next(iter(ids)) != me
                   and f == ascii_name(f) and any(full.split(" ")[0] == f for full in full_names if full_names[full] in ids)}
    note_names_plain = {ascii_name(n): pid for n, pid in note_names.items()}
    name_re = re.compile(r"(?<![a-z])(" + "|".join(map(re.escape, sorted(note_names_plain, key=len, reverse=True))) + r")(?![a-z])") if note_names_plain else None
    first_re = re.compile(r"(?<![A-Za-z])(" + "|".join(map(re.escape, sorted(note_firsts, key=len, reverse=True))) + r")(?![A-Za-z])") if note_firsts else None

    def named(nm):   # a name in a chat's title: a full name, or a first name nobody else has ("Glen" could be four people)
        nm = (nm or "").strip()
        if not nm:
            return None
        if " " not in nm:
            hits = [i for n, i in full_names.items() if n.split(" ")[0] == nm.lower()]
            return hits[0] if len(hits) == 1 and hits[0] != me else None
        return person(nm)

    # Who is in each DM and group chat: everyone who has written in it and the people it is named after. A message then links
    # to all of them (Sam's own messages included), like an email links to everyone on To and Cc, not only to its author.
    members, titles = {}, {}
    for r in con.execute("SELECT source_id, COALESCE(conversation_id, conversation_name) AS conv, conversation_name, conversation_kind, author "
                         f"FROM chat_messages WHERE conversation_kind IN ({','.join('?' * len(CONVERSATION_KINDS))})", CONVERSATION_KINDS):
        m = members.setdefault((r["source_id"], r["conv"]), set())
        m.add(person(r["author"]))
        key = (r["conversation_name"], r["conversation_kind"])
        if key not in titles:
            titles[key] = {named(nm) for nm in conversation_names(*key)}
        m |= titles[key]
    members = {k: {p for p in v if p} for k, v in members.items()}

    # Documents (working files: SharePoint/OneDrive and local; not the product docs or the emery yates). A document is
    # linked to its owner, to whoever shared it in a chat or an email (file name or link title), and to the initiative it
    # is filed under; the chat, email or meeting that shared or named it is linked to the document (entity_type 'doc').
    docs_by_name, doc_rows = {}, {}
    for r in con.execute("SELECT id, subject, source_id FROM items WHERE kind='doc' AND noise=0 AND source_id IN ('sharepoint', 'local')"):
        nm = (r["subject"] or "").strip().lower()
        if len(nm) >= 8:
            docs_by_name.setdefault(nm, []).append(r["id"])
            doc_rows[r["id"]] = r["subject"]
    shares = {}   # item id of a chat or email -> [(doc file name, sharer address or name)]
    for r in con.execute("SELECT item_id, author, links_json FROM chat_messages WHERE links_json IS NOT NULL AND links_json != '[]'"):
        for l in json.loads(r["links_json"] or "[]"):
            if (l.get("title") or "").strip().lower() in docs_by_name:
                shares.setdefault(r["item_id"], []).append(((l.get("title") or "").strip().lower(), r["author"]))
    for r in con.execute("SELECT a.item_id, a.name, c.author FROM chat_attachments a JOIN chat_messages c ON c.item_id=a.item_id"):
        if (r["name"] or "").strip().lower() in docs_by_name:
            shares.setdefault(r["item_id"], []).append(((r["name"] or "").strip().lower(), r["author"]))
    for r in con.execute("SELECT a.item_id, a.name, m.from_address, m.subject FROM mail_attachments a JOIN mail_messages m ON m.item_id=a.item_id WHERE a.is_inline=0"):
        if (r["name"] or "").strip().lower() in docs_by_name:
            shares.setdefault(r["item_id"], []).append(((r["name"] or "").strip().lower(), r["from_address"]))
    shared_by = {}   # doc item id -> [(sharer, sharing item id)]
    for iid, lst in shares.items():
        for nm, who_ in lst:
            for d in docs_by_name[nm]:
                shared_by.setdefault(d, []).append((who_, iid))
    # titles specific enough to recognise when a meeting's notes name them ("PLT market context 2-pager"): no extension,
    # at least 3 words or 18 characters, not a common phrase
    doc_titles = {}
    for d, subj in doc_rows.items():
        t = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", subj or "").replace("_", " ").strip()
        if (len(t.split()) >= 3 or len(t) >= 18) and not re.fullmatch(r"(document|presentation|book|untitled|copy of|new)[\w\s()-]*", t, re.I):
            doc_titles.setdefault(t.lower(), d)
    doc_title_re = re.compile(r"(?<![\w])(" + "|".join(map(re.escape, sorted(doc_titles, key=len, reverse=True))) + r")(?![\w])") if doc_titles else None
    slug_ids = {r["slug"]: r["id"] for r in con.execute("SELECT id, slug FROM initiatives")}
    filed = {}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='doc_folders'").fetchone():
        for r in con.execute("SELECT doc_id, initiatives, by FROM doc_folders WHERE initiatives != '[]'"):
            pre, _, num = r["doc_id"].partition("-")
            if pre in ("sp", "lf") and num.isdigit():
                filed[int(num)] = ([slug_ids[x] for x in json.loads(r["initiatives"]) if x in slug_ids], r["by"])

    from . import refs   # products, roadmap items, Jira issues
    ref_res, ticket_re, ticket_id = refs.matchers(con, _now())

    n_links, max_id = 0, mark["id"]
    for it in rows:
        max_id = max(max_id, it["id"])
        links = {}   # (entity_type, id) -> confidence

        def add(t, i, c, role, why=""):
            """Keep the strongest evidence per entity: highest confidence, then the role that says most (sender over
            mentioned); `why` is the evidence shown with the link (an address, a quoted line)."""
            if not i:
                return
            old = links.get((t, i))
            if not old or (c, ROLE_RANK.get(role, 0)) > (old[0], ROLE_RANK.get(old[1], 0)):
                links[(t, i)] = (c, role, why[:200])

        def around(src, hit, n=70):   # the words around a name, as evidence
            k = src.lower().find(hit.lower())
            return "…" + re.sub(r"\s+", " ", src[max(0, k - n):k + len(hit) + n]).strip() + "…" if k >= 0 else hit
        pay = {}
        if it["payload"]:
            try:
                pay = json.loads(it["payload"])
            except ValueError:
                pay = {}
        addrs = []   # (address, role)
        if it["id"] in mail:
            m = mail[it["id"]]
            addrs.append((m["from_address"] or "", "from"))
            for col, role in (("to_json", "to"), ("cc_json", "cc")):
                addrs += [(x.get("address") or "", role) for x in json.loads(m[col] or "[]")]
        elif it["kind"] in ("mail", "sent") and isinstance(pay, dict) and pay.get("envelope"):   # connector envelope (Jul–Sep): no mail_messages row
            rec = pay.get("recipients") or []
            if isinstance(rec, str):
                rec = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", rec)
            addrs += [(pay.get("sender") or "", "from")] + [(a, "to") for a in rec if isinstance(a, str)]
        if it["kind"] == "event" and isinstance(pay, dict):
            addrs += [(a, "invitee") for a in (pay.get("attendees") or []) if isinstance(a, str)] + [(pay.get("organizer") or "", "organizer")]
        for a, role in addrs:
            if not a or ME.search(a):
                continue
            add("person", person(a), 1.0, role, a)
            add("org", org_for_domain(con, domain_of(a), cores, create=it["kind"] in ("mail", "sent", "event")), 0.9, "domain", domain_of(a))
        sender = mail[it["id"]]["from_address"] if it["id"] in mail else (pay.get("sender") if isinstance(pay, dict) and pay.get("envelope") else None)
        shared = bool(sender) and not personal_address(sender)
        if it["from_person_id"] and it["from_person_id"] != me and not shared:
            add("person", it["from_person_id"], 1.0, "author" if it["id"] in chat else "from", it["from_name"] or "")
        if shared and it["from_name"]:   # a Jira or GitLab notification names who acted ("Gray Selby (Jira)"): a hint, not shown
            add("person", person(it["from_name"]), 0.5, "actor", f"{it['from_name']} via {sender}")
        if it["id"] in chat:
            ch = chat[it["id"]]
            add("person", person(ch["author"]), 0.9, "author", ch["author"] or "")
            dm = ch["conversation_kind"] in DM_KINDS
            for pid in members.get((ch["source_id"], ch["conv"]), ()):   # a DM is between Sam and them; a group chat is like Cc
                add("person", pid, 1.0 if dm else 0.6, "dm" if dm else "member", "direct message" if dm else f"member of {ch['conv'] or 'the chat'}")
        if it["source_id"] == "salesforce" and isinstance(pay, dict) and pay.get("account"):
            r = con.execute("SELECT id FROM orgs WHERE name=?", (pay["account"].strip(),)).fetchone()
            add("org", r["id"] if r else None, 1.0, "account", "Salesforce account")
        text = f"{it['subject'] or ''}\n{it['text'] or ''}"
        if it["kind"] == "note":   # a Granola meeting: its calendar event's people and orgs, its attendees, who spoke
            mt = con.execute("SELECT id, event_item_id, attendees FROM meetings WHERE note_item_id=?", (it["id"],)).fetchone()
            if mt and mt["event_item_id"]:
                for r in con.execute("SELECT entity_type, entity_id FROM mentions WHERE ref_type='item' AND ref_id=? AND entity_type IN ('person','org') "
                                     "AND COALESCE(verdict, '') != 'rejected'", (mt["event_item_id"],)):
                    add(r["entity_type"], r["entity_id"], 1.0, "invitee" if r["entity_type"] == "person" else "domain", "on the calendar invite")
            for nm in json.loads((mt["attendees"] if mt else None) or "[]"):
                add("person", person(nm), 1.0, "attendee", "attendee")
            if mt and has_speakers:
                for r in con.execute("SELECT person_id, words, share FROM meeting_speakers WHERE meeting_id=? AND is_me=0 AND person_id IS NOT NULL AND words >= 40", (mt["id"],)):
                    add("person", r["person_id"] if r["person_id"] != me else None, 1.0, "speaker", f"spoke {round(100 * (r['share'] or 0))}% ({r['words']} words)")
        if it["kind"] == "doc" and it["id"] in doc_rows:
            if it["source_id"] == "sharepoint" and it["from_name"]:   # the OneDrive owner (a site name resolves to nobody)
                add("person", person(it["from_name"]), 1.0, "owner", f"owner on SharePoint: {it['from_name']}")
            for who_, via in shared_by.get(it["id"], []):
                add("person", person(who_), 1.0, "shared", f"shared it ({KIND_LABEL.get(con.execute('SELECT kind FROM items WHERE id=?', (via,)).fetchone()[0], 'message')})")
            ids_, by = filed.get(it["id"], ([], None))
            for iid in ids_:
                add("initiative", iid, 1.0 if by == "sam" else 0.8, "filed", f"filed by {USER.first}" if by == "sam" else "filed by the assistant")
        for nm, _ in shares.get(it["id"], []):   # this chat or email shared a document
            for d in docs_by_name.get(nm, []):
                add("doc", d, 1.0, "shared", doc_rows[d])
        if it["kind"] == "note" and doc_title_re is not None:   # a meeting's notes name a document
            for hit in set(doc_title_re.findall((it["text"] or "")[:20000].lower())):
                add("doc", doc_titles[hit], 0.6, "mentioned", around(it["text"] or "", hit))
        # Names written in it. Full names (and other full names: Quinn Dalton) anywhere in a note, chat or invite, in an
        # email's subject or body, a document's title; a first name only one person has in a note, a chat or a subject line.
        if not WARNING.match(it["subject"] or ""):
            scope = it["subject"] or "" if it["kind"] in ("doc", "opportunity") else text[:20000]
            if name_re is not None:
                plain = ascii_name(scope)
                for hit in set(name_re.findall(plain.lower())):
                    add("person", note_names_plain[hit], 0.7, "mentioned", around(plain, hit))
            if first_re is not None:
                firsts_in = text[:20000] if it["kind"] in ("note", "chat", "channel", "teams", "event") else it["subject"] or ""
                for hit in set(first_re.findall(firsts_in)):
                    add("person", note_firsts[hit], 0.6, "mentioned", "first name: " + around(firsts_in, hit))
        if acct_re is not None and it["source_id"] != "salesforce":
            for hit in set(acct_re.findall(text[:20000])):
                add("org", acct_ids.get(hit), 0.6, "mentioned", around(text[:20000], hit))
        for iid, rx in inis:
            hit = rx.search(text[:20000])
            if hit:   # keyword only: 0.5 puts it in the initiative page's "suggested" tray, not the timeline
                add("initiative", iid, 0.5, "keyword", f"keyword “{hit.group(0)}”")
        if it["kind"] not in ("opportunity",) and it["source_id"] != "public-docs":
            body = text[:20000]
            for typ, eid, rx, conf in ref_res:
                hit = rx.search(body)
                if hit:
                    add(typ, eid, conf, "mentioned", around(body, hit.group(0)))
            if ticket_re is not None:
                for key in {f"{a}-{b}" for a, b in ticket_re.findall(body)}:
                    add("ticket", ticket_id(key), 1.0, "mentioned", around(body, key))
        for (t, i), (c, role, why) in links.items():
            con.execute("INSERT INTO mentions (ref_type, ref_id, entity_type, entity_id, confidence, source, role, reason, updated_at) "
                        "VALUES ('item',?,?,?,?,'entities',?,?,?) ON CONFLICT(ref_type, ref_id, entity_type, entity_id) DO UPDATE SET "
                        "role=CASE WHEN COALESCE(mentions.source, 'entities')='entities' OR mentions.role IS NULL THEN excluded.role ELSE mentions.role END, "
                        "reason=CASE WHEN COALESCE(mentions.source, 'entities')='entities' OR mentions.reason IS NULL THEN excluded.reason ELSE mentions.reason END, "
                        "confidence=MAX(mentions.confidence, excluded.confidence)",
                        (it["id"], t, i, c, role, why, _now()))
            n_links += 1
    if full:   # generic orgs made from a domain that nothing points at any more
        con.execute("DELETE FROM orgs WHERE source='domain' AND id NOT IN (SELECT org_id FROM org_domains) "
                    "AND id NOT IN (SELECT entity_id FROM mentions WHERE entity_type='org') AND id NOT IN (SELECT org_id FROM people WHERE org_id IS NOT NULL) "
                    "AND id NOT IN (SELECT org_id FROM loops WHERE org_id IS NOT NULL)")
    con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('entities:mark', ?)", (json.dumps({"id": max_id, "at": _now()}),))
    con.commit()
    log(f"entities: linked {len(rows)} items · {n_links} links · {len(cores)} accounts")
    try:   # graph memory (DESIGN-GRAPH-MEMORY.md): mark the records the new items touch; never blocks linking
        from . import graph_memory
        g = graph_memory.propagate(con)
        con.commit()
        if g["touches"]:
            log(f"graph memory: {g['items']} items touched {g['touches']} records")
    except Exception as e:
        con.rollback()
        log(f"graph memory skipped: {e}")
    return {"items": len(rows), "links": n_links}


# ------------------------------------------------------------------------------------------------ reading
KIND_LABEL = {"mail": "Email", "sent": "Email (sent)", "chat": "Chat", "channel": "Channel", "teams": "Teams", "event": "Calendar",
              "note": "Meeting", "doc": "Document", "opportunity": "Opportunity"}


def item_link(it):
    if it["kind"] in ("mail", "sent"):
        return f"#/mail?open={it['id']}"
    if it["kind"] == "note":
        r = it.get("meeting_id")
        return f"#/meetings/m-{r}" if r else "#/meetings"
    if it["kind"] in ("chat", "channel", "teams"):
        return it.get("url") or f"#/messages?open={it['id']}"
    if it["kind"] == "opportunity":
        return "#/pipeline"
    return it.get("url") or ""


def _shown():
    """The display rule shared with the initiative page: confirmed, or unreviewed with confidence >= 0.6; never rejected."""
    return "(COALESCE(m.verdict, '') = 'confirmed' OR (m.verdict IS NULL AND m.confidence >= 0.6))"


def _has_verdict(con):
    return "verdict" in {r[1] for r in con.execute("PRAGMA table_info(mentions)")}


def timeline(con, entity_type, entity_id, limit=60, since=None):
    """Everything linked to one person, org or initiative, newest first. For a person, each email says how they were on it
    (from / to / cc) and whether Sam sent it; each chat message gives its conversation and whether Sam wrote it."""
    q = ("SELECT i.id, i.source_id, i.kind, i.ts, i.from_name, i.subject, i.text, i.url, m.confidence, m.role AS link_role, m.reason, m.verdict, mt.id AS meeting_id, "
         "mm.folder, mm.from_address, mm.to_json, mm.cc_json, cm.author, cm.conversation_name, cm.conversation_kind FROM mentions m "
         "JOIN items i ON i.id=m.ref_id LEFT JOIN meetings mt ON mt.note_item_id=i.id "
         "LEFT JOIN mail_messages mm ON mm.item_id=i.id LEFT JOIN chat_messages cm ON cm.item_id=i.id "
         "WHERE m.ref_type='item' AND m.entity_type=? AND m.entity_id=? AND i.noise=0 AND i.kind != 'opportunity' AND i.ts <= ?" + (" AND i.ts >= ?" if since else "") +
         (" AND " + _shown() if _has_verdict(con) else " AND m.confidence >= 0.6") +
         " ORDER BY i.ts DESC LIMIT ?")
    horizon = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")   # upcoming meetings yes, far-future records no
    args = [entity_type, entity_id, horizon] + ([since] if since else []) + [limit]
    mine = {a for (a,) in con.execute("SELECT alias FROM people_aliases WHERE person_id=? AND alias LIKE '%@%'", (entity_id,))} if entity_type == "person" else set()

    def on(col):
        return any((x.get("address") or "").lower() in mine for x in json.loads(col or "[]"))
    out = []
    for r in con.execute(q, args):
        d = dict(r)
        x = {"id": d["id"], "kind": d["kind"], "label": KIND_LABEL.get(d["kind"], d["kind"]), "source": d["source_id"], "ts": d["ts"],
             "from": d["from_name"] or "", "title": d["subject"] or "", "snippet": re.sub(r"\s+", " ", d["text"] or "")[:240],
             "url": item_link(d), "confidence": d["confidence"], "link": {"role": d["link_role"], "reason": d["reason"], "verdict": d["verdict"]}}
        if d["folder"]:
            x["mine"] = d["folder"] == "sentitems" or bool(ME.search(d["from_address"] or ""))
            if mine:
                x["role"] = "from" if (d["from_address"] or "").lower() in mine else "to" if on(d["to_json"]) else "cc" if on(d["cc_json"]) else None
        if d["conversation_name"] is not None:
            x["mine"] = bool(ME.search(d["author"] or ""))
            x["where"] = d["conversation_name"]
            x["dm"] = d["conversation_kind"] in DM_KINDS
            x["title"] = x["title"] or x["snippet"]
        out.append(x)
    return out


def set_verdict(con, ref_type, ref_id, entity_type, entity_id, verdict, role=None):
    """Sam's tick or cross on one link (None undoes it). A tick on a link that does not exist adds it (source 'sam').
    The linker never removes or re-scores a link Sam has judged, and never shows a rejected one."""
    if verdict not in ("confirmed", "rejected", None):
        raise ValueError(verdict)
    row = con.execute("SELECT 1 FROM mentions WHERE ref_type=? AND ref_id=? AND entity_type=? AND entity_id=?", (ref_type, ref_id, entity_type, entity_id)).fetchone()
    if row:
        con.execute("UPDATE mentions SET verdict=?, updated_at=? WHERE ref_type=? AND ref_id=? AND entity_type=? AND entity_id=?",
                    (verdict, _now(), ref_type, ref_id, entity_type, entity_id))
    elif verdict == "confirmed":
        con.execute("INSERT INTO mentions (ref_type, ref_id, entity_type, entity_id, confidence, source, role, reason, verdict, updated_at) "
                    "VALUES (?,?,?,?,1.0,'sam',?,?,'confirmed',?)", (ref_type, ref_id, entity_type, entity_id, role or "mentioned", f"added by {USER.first}", _now()))
    elif verdict is None:
        return False
    else:   # a cross on a link nobody made: remember it, so the linker never adds it
        con.execute("INSERT INTO mentions (ref_type, ref_id, entity_type, entity_id, confidence, source, verdict, updated_at) VALUES (?,?,?,?,0,'sam','rejected',?)",
                    (ref_type, ref_id, entity_type, entity_id, _now()))
    return True


def review_sample(con, n=20, days=90):
    """Links for Sam to check (the Check links page): unreviewed, shown, recent, spread across roles so the weak kinds
    (first names, chat membership, domains) are sampled as often as the strong ones. His ticks and crosses become the
    golden set for evals.eval_links()."""
    import random
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute("SELECT m.ref_id, m.entity_type, m.entity_id, m.role, m.reason, m.confidence, i.kind, i.ts, i.subject, i.text, i.url, i.from_name, "
                       "mt.id AS meeting_id, COALESCE(p.name, o.name) AS name FROM mentions m JOIN items i ON i.id=m.ref_id "
                       "LEFT JOIN meetings mt ON mt.note_item_id=i.id LEFT JOIN people p ON m.entity_type='person' AND p.id=m.entity_id "
                       "LEFT JOIN orgs o ON m.entity_type='org' AND o.id=m.entity_id WHERE m.ref_type='item' AND m.entity_type IN ('person','org') "
                       "AND m.verdict IS NULL AND m.confidence >= 0.6 AND i.noise=0 AND i.kind != 'opportunity' AND i.ts >= ? AND i.ts <= ?",
                       (since, _now())).fetchall()
    by = {}
    for r in rows:
        by.setdefault(r["role"] or "?", []).append(r)
    rnd = random.Random(datetime.now().strftime("%Y%m%d%H"))   # stable for an hour, so a reload does not reshuffle
    for v in by.values():
        rnd.shuffle(v)
    out, k = [], 0
    while len(out) < n and any(by.values()):
        for role in sorted(by, key=lambda x: -ROLE_RANK.get(x, 0)):
            if by[role] and len(out) < n:
                out.append(by[role].pop())
        k += 1
    return [{"item_id": r["ref_id"], "entity_type": r["entity_type"], "entity_id": r["entity_id"], "name": r["name"], "role": r["role"], "reason": r["reason"],
             "confidence": r["confidence"], "kind": r["kind"], "label": KIND_LABEL.get(r["kind"], r["kind"]), "ts": r["ts"], "from": r["from_name"] or "",
             "title": r["subject"] or "", "snippet": re.sub(r"\s+", " ", r["text"] or "")[:200], "url": item_link(dict(r, id=r["ref_id"]))} for r in out]


def last_activity(con, entity_type, entity_id, kinds=("mail", "sent", "chat", "note", "event")):
    shown = _shown() if _has_verdict(con) else "m.confidence >= 0.6"
    r = con.execute("SELECT MAX(i.ts) FROM mentions m JOIN items i ON i.id=m.ref_id WHERE m.ref_type='item' AND m.entity_type=? AND m.entity_id=? "
                    f"AND {shown} AND i.noise=0 AND i.kind IN ({','.join('?' * len(kinds))}) AND i.ts <= ?",
                    [entity_type, entity_id, *kinds, _now()]).fetchone()
    return r[0]


def entities_of(con, item_id):
    return [dict(r) for r in con.execute(
        "SELECT m.entity_type, m.entity_id, m.confidence, m.role, m.reason, m.verdict, "
        "COALESCE(p.name, o.name, ini.name, d.subject, CASE WHEN r.type='ticket' THEN r.key || COALESCE(' ' || r.name, '') ELSE r.name END) AS name FROM mentions m "
        "LEFT JOIN people p ON m.entity_type='person' AND p.id=m.entity_id LEFT JOIN orgs o ON m.entity_type='org' AND o.id=m.entity_id "
        "LEFT JOIN initiatives ini ON m.entity_type='initiative' AND ini.id=m.entity_id LEFT JOIN items d ON m.entity_type='doc' AND d.id=m.entity_id "
        "LEFT JOIN ref_entities r ON m.entity_type IN ('product','roadmap','ticket') AND r.id=m.entity_id "
        "WHERE m.ref_type='item' AND m.ref_id=? AND COALESCE(m.verdict, '') != 'rejected' ORDER BY m.entity_type, m.confidence DESC", (item_id,))]


def org_summary(con, org_id):
    o = con.execute("SELECT * FROM orgs WHERE id=?", (org_id,)).fetchone()
    if not o:
        return None
    opps = []
    for (p,) in con.execute("SELECT i.payload FROM mentions m JOIN items i ON i.id=m.ref_id WHERE m.ref_type='item' AND m.entity_type='org' "
                            "AND m.entity_id=? AND i.source_id='salesforce'", (org_id,)):
        d = json.loads(p or "{}")
        opps.append({k: d.get(k) for k in ("name", "stage", "close_date", "acv", "currency", "net_forecast_usd", "sale_type", "is_open", "forecast_category")})
    domains = [r["domain"] for r in con.execute("SELECT domain FROM org_domains WHERE org_id=?", (org_id,))]
    people = [dict(r) for r in con.execute(
        "SELECT p.id, p.name, COUNT(*) AS n FROM mentions m JOIN mentions m2 ON m2.ref_type='item' AND m2.ref_id=m.ref_id AND m2.entity_type='person' "
        "JOIN people p ON p.id=m2.entity_id WHERE m.ref_type='item' AND m.entity_type='org' AND m.entity_id=? AND p.is_me=0 GROUP BY p.id ORDER BY n DESC LIMIT 8",
        (org_id,))]
    return {"id": o["id"], "name": o["name"], "kind": o["kind"], "region": o["region"] if "region" in o.keys() else None, "domains": domains,
            "opportunities": opps, "people": people, "last_activity": last_activity(con, "org", org_id)}
