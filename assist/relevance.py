"""Shared helpers that make meeting prep and reply drafts more relevant.

- People are matched by identity (email address, full name or person id), never by a shared first name: the company
  has four Daniels and two Scotts. A first name alone is only trusted when nobody else has it.
- The meeting's own invite text (agenda) is read; Teams join blocks, meeting ids and passcodes are stripped.
- A meeting without the assistant's digest falls back to Granola's own summary.
- Previous occurrences of a recurring meeting are found through the calendar subject, not Granola's generated title.
- Topic search across everything (mail, chat, meetings, transcripts, documents) via the unified search index.
- Free afternoon slots that follow Sam's meeting preferences, for replies that propose a time.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import db
from . import org
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from . import profile

try:
    from zoneinfo import ZoneInfo
    LONDON = profile.zone()
except Exception:  # pragma: no cover
    LONDON = None

SAM = db.ME_STRICT   # the one definition, assist/db.py
STOP = set("""a an and are as at be by for from in into is it of on or our the to with without this that these those your you we i
sync meeting call review weekly update catch catchup check 1 2 3 1:1 re fw fwd teams microsoft discussion session follow up followup
suggesting suggest proposing propose regular recurring convenient time times slot lmk let know please
connect touch base works work rescheduled resheduled reschedule automatically recorded optional attendees included agenda
thanks thank hope""".split()) | {w for n in profile.names() for w in n.split()} | set(org.own_prefixes())   # the user and their own company say nothing


# ------------------------------------------------------------------------------------------------ people
def first_name_counts(con):
    counts = {}
    for (n,) in con.execute("SELECT name FROM people"):
        f = (n or "").split(" ")[0].lower()
        counts[f] = counts.get(f, 0) + 1
    return counts


def resolve(con, who):
    """Person row for an email address or a name, or None. Never guesses on an ambiguous first name."""
    if not who:
        return None
    w = who.strip().lower()
    if " " not in w and "@" not in w and first_name_counts(con).get(w, 0) > 1:
        return None                      # "Glen" could be any of four people: do not guess
    row = con.execute("SELECT person_id FROM people_aliases WHERE alias=?", (w,)).fetchone()
    if not row and "@" in w:
        local, dom = w.split("@", 1)
        local = local.replace(".", " ").replace("_", " ").strip()
        from .entities import INTERNAL, registrable
        # the part before the @ names a colleague only on a company domain, or as a full name; pat@vendor.com is not
        # Pat at Acme, and glen@acme.example could be any of four Daniels
        if " " in local or (registrable(dom) in INTERNAL and first_name_counts(con).get(local, 0) <= 1):
            row = con.execute("SELECT person_id FROM people_aliases WHERE alias=?", (local,)).fetchone()
            if not row:
                row = con.execute("SELECT id AS person_id FROM people WHERE lower(name)=?", (local,)).fetchone()
    if not row and " " not in w and first_name_counts(con).get(w, 0) == 1:
        row = con.execute("SELECT id AS person_id FROM people WHERE lower(name) LIKE ?", (w + " %",)).fetchone()
    return con.execute("SELECT * FROM people WHERE id=?", (row["person_id"],)).fetchone() if row else None


class Matcher:
    """Does a piece of text or a counterparty refer to one of these people? Full names always; a first name only when unique."""
    def __init__(self, con, people):
        counts = first_name_counts(con)
        self.ids = {p["id"] for p in people}
        self.full = {p["name"].lower() for p in people}
        self.first = {p["name"].split(" ")[0].lower() for p in people if counts.get(p["name"].split(" ")[0].lower(), 0) == 1}
        for p in people:
            for (a,) in con.execute("SELECT alias FROM people_aliases WHERE person_id=? AND alias NOT LIKE '%@%'", (p["id"],)):
                if " " in a:
                    self.full.add(a.lower())

    def name(self, who):
        w = (who or "").strip().lower()
        return bool(w) and (w in self.full or (" " not in w and w in self.first) or (w.split(" ")[0] in self.first and len(w.split(" ")) == 1))

    def text(self, t):
        t = (t or "").lower()
        return any(n in t for n in self.full) or any(re.search(rf"\b{re.escape(f)}\b", t) for f in self.first if len(f) > 2)

    def person_id(self, pid):
        return pid in self.ids


# ------------------------------------------------------------------------------------------------ meetings
def agenda(payload):
    """The invite's own text: what the organiser wrote, without the Teams join block, ids, passcodes or dial-ins."""
    s = (payload or {}).get("summary") or ""
    s = re.split(r"_{8,}|Microsoft Teams (?:meeting|Need help)|Join:\s*https?://|Join the meeting now|This email and any files|CONFIDENTIALITY", s)[0]
    # cut at the sign-off and drop anything that looks like contact details (phones, addresses, emails)
    lines = []
    for l in s.splitlines():
        if re.match(r"^\s*(thanks|thank you|best|regards|kind regards|cheers|br|rgds)[,.!]?\s*$", l, re.I):
            break
        if re.search(r"\+?\d[\d ()./-]{7,}\d", l):
            continue
        lines.append(l)
    while lines and (re.search(r"@|^\s*(www\.|https?://|[\w.-]+\.(com|net|org|jp|fr)\s*$)", lines[-1], re.I)
                     or profile.SIGNATURE.match(lines[-1]) or not lines[-1].strip()):
        lines.pop()
    s = "\n".join(lines)
    s = re.sub(r"(?i)(meeting id|passcode|dial in|phone conference id)[^\n]*", "", s)
    s = re.sub(r"\s+\n", "\n", s).strip()
    return s if len(s) > 15 else ""


def digest_summary(digest):
    """The meeting's summary only. A Granola digest also carries a header line and a "Candidates for triage" checklist (lines
    lifted from the summary for the old /triage step); open items are now extracted automatically, so neither is shown or reused."""
    d = digest or ""
    if "### AI summary" in d:
        d = d.split("### AI summary", 1)[1]
    else:
        d = re.sub(r"### Candidates for triage\n.*?(?=\n### |\n# |\Z)", "", d, flags=re.S)
        d = re.sub(r"^\*\*With:\*\*.*$", "", d, flags=re.M)
    return d.strip()


def meeting_notes(con, meeting_row, n=1400):
    """Assistant digest, else Granola's own summary (labelled), else nothing."""
    d = digest_summary(meeting_row["digest_md"])
    if d:
        return d[:n]
    r = con.execute("SELECT text FROM items WHERE id=?", (meeting_row["note_item_id"],)).fetchone()
    g = (r["text"] or "").strip() if r else ""
    return ("_Granola's own summary (not yet analysed by the assistant):_\n" + g[:n]) if g else ""


def previous_occurrences(con, subject, before_iso, matcher=None, limit=3):
    """Earlier meetings of the same calendar series (same subject), newest first. With a matcher, a recording only counts
    when it shares an attendee (time-based matching sometimes pins a different call onto a recurring slot)."""
    if not subject:
        return []
    out = []
    for m in con.execute("SELECT m.* FROM meetings m JOIN items e ON e.id=m.event_item_id WHERE lower(trim(e.subject))=lower(trim(?)) "
                         "AND m.status != 'personal' AND m.starts_at < ? ORDER BY m.starts_at DESC LIMIT 12", (subject, before_iso)):
        att = [a for a in json.loads(m["attendees"] or "[]") if not SAM.search(a or "")]
        if matcher is None or any(matcher.name(a) for a in att) or matcher.text(m["title"]):
            out.append(m)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------------------------------ topic
def keywords(*texts, n=8, con=None):
    names = set(first_name_counts(con)) if con is not None else set()
    words = []
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", t or ""):
            lw = w.lower()
            if lw not in STOP and lw not in names and lw not in words and not re.match(r"^(re|fw|fwd)$", lw):
                words.append(lw)
    return words[:n]


def topic_lines(con, query_words, exclude_refs=(), kinds=None, limit=10):
    """Top search hits for the topic words (any-word match), as 'kind · title · date · snippet · link' lines."""
    if not query_words:
        return []
    from . import search
    from itertools import combinations
    w = [x for x in query_words if len(x) > 2][:6]
    queries = [" ".join(w[:3]), " ".join(w[:2])] + [" ".join(p) for p in combinations(w[:5], 2)] + [x for x in w[:4] if len(x) > 4]
    hits, seen = [], set()
    for q in dict.fromkeys(q for q in queries if q.strip()):   # search requires every word of a query, so: many small ones, merged
        try:
            res = search.search(con, q, limit=15, kinds=kinds)
        except Exception:
            continue
        for h in res.get("results", []):
            if (h["kind"], h["ref"]) not in seen:
                seen.add((h["kind"], h["ref"]))
                hits.append(h)
        if len(hits) >= 60:
            break
    res = {"results": hits}
    out = []
    for r in res.get("results", []):
        if r["kind"] == "event":
            continue
        if r.get("ref") in exclude_refs or str(r.get("ref", "")).startswith(("prep/", "drafts/prep")) or (r.get("title") or "").startswith("Prep ·"):
            continue
        if r["kind"] == "email" and re.match(r"(?i)^(accepted|declined|tentative|canceled|cancelled|updated invitation|invitation)\b", r.get("title") or ""):
            continue
        sn = re.sub(r"[\x02\x03]", "", r.get("snippet") or "")
        out.append(f"- {r['kind']} · {r['title'][:140]} · {(r.get('ts') or '')[:10]}" + (f" · {sn[:220]}" if sn else "") + (f" · [open](#{r['url']})" if r.get("url") else ""))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------------------------------ calendar
def free_slots(con, days=6, per_day=3):
    """Free slots of the user's usual length inside their meeting days and hours (the profile: for Sam 30 minutes,
    14:00-18:00, Mon-Thu) over the next working days, preferring slots next to existing meetings so they cluster. Returns
    lines like 'Thu 08 Oct 15:30-16:00 BST (07:30 PT)', with the second clock when the profile has one."""
    if not LONDON:
        return []
    meet_days, (h0, m0), (h1, m1), mins = profile.meeting_window()
    p2 = profile.get()
    second = None
    if p2["second_timezone"]:
        try:
            second = ZoneInfo(p2["second_timezone"])
        except Exception:
            second = None
    now = datetime.now(timezone.utc).astimezone(LONDON)
    busy = []
    for r in con.execute("SELECT ts, payload FROM items WHERE kind='event' AND noise=0 AND ts >= ? AND ts <= ?",
                         ((now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"), (now + timedelta(days=days + 4)).strftime("%Y-%m-%dT%H:%M"))):
        p = json.loads(r["payload"] or "{}")
        if (p.get("showAs") or "busy") == "free":
            continue
        try:
            st = datetime.fromisoformat(r["ts"].replace("Z", "")[:19]).replace(tzinfo=timezone.utc).astimezone(LONDON)
            en = datetime.fromisoformat(str(p.get("end", r["ts"])).split(".")[0].replace("Z", "")[:19]).replace(tzinfo=timezone.utc).astimezone(LONDON)
        except ValueError:
            continue
        busy.append((st, en))
    out, d, made = [], now.date(), 0
    while made < days:
        d += timedelta(days=1)
        if d.weekday() not in meet_days:   # days the user takes no meetings
            continue
        made += 1
        cands = []
        t = datetime(d.year, d.month, d.day, h0, m0, tzinfo=LONDON)
        while t + timedelta(minutes=mins) <= datetime(d.year, d.month, d.day, h1, m1, tzinfo=LONDON):
            e = t + timedelta(minutes=mins)
            if not any(s < e and t < x for s, x in busy):
                adjacent = any(abs((x - t).total_seconds()) < 60 or abs((s - e).total_seconds()) < 60 for s, x in busy)
                cands.append((0 if adjacent else 1, t))
            t += timedelta(minutes=30)
        for _, t in sorted(cands)[:per_day]:
            line = f"{t.strftime('%a %d %b %H:%M')}-{(t + timedelta(minutes=mins)).strftime('%H:%M')} {t.tzname()}"
            if second:
                s = t.astimezone(second)
                line += f" ({s.strftime('%H:%M')} {p2['second_timezone_label'] or s.tzname()})"
            out.append(line)
    return out


def company_facts(root, n=2500):
    p = root / "memory" / "context" / "company.md"
    if not p.exists():
        return ""
    t = re.sub(r"^---.*?---\s*", "", p.read_text(), flags=re.S)
    return t[:n]


def topic_hits(con, query_words, kinds=None, limit=30):
    """Like topic_lines, but the raw hits (kind, ref, title, ts, url), for callers that fetch more detail themselves."""
    from . import search
    from itertools import combinations
    w = [x for x in query_words if len(x) > 2][:6]
    queries = [" ".join(w[:3]), " ".join(w[:2])] + [" ".join(p) for p in combinations(w[:5], 2)] + [x for x in w[:4] if len(x) > 4]
    hits, seen = [], set()
    for q in dict.fromkeys(q for q in queries if q.strip()):
        try:
            res = search.search(con, q, limit=15, kinds=kinds)
        except Exception:
            continue
        for h in res.get("results", []):
            if (h["kind"], h["ref"]) not in seen:
                seen.add((h["kind"], h["ref"]))
                hits.append(h)
    return hits[:limit]
