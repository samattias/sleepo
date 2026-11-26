"""The soul pages, and which agent reads which part of them.

Three pages in memory/context/, all Sam's to edit:
- company (soul.md): how to read what people say. Statements are claims; weigh the source; say how confident.
- cpo (cpo-soul.md): what good product leadership looks like. The lens for what matters, what to delegate, when to push back.
- sleepo (assistant-soul.md): how the assistant behaves. Every claude -p run already carries its summary through CLAUDE.md
  (loaded from the working folder), and the code enforces its lines (no tools over untrusted text, never send).

Tool-free runs cannot open files, so each prompt carries the text it needs. Prompts used to take the first 1,200-1,500
characters of soul.md: its frontmatter and beliefs. Every rule starts after that, so the brief, Actions and initiative
updates never saw one. Here a prompt asks for headed sections instead, with frontmatter and Sam's notes to himself stripped,
so what an agent gets does not shift as the pages grow. A section that has been renamed falls back to the whole page,
never to nothing, and the Soul page says so (GET /api/souls).

USES is the one map of who reads what; the Soul page shows it.
"""
import re

from . import db

FILES = {"company": "memory/context/soul.md", "cpo": "memory/context/role-soul.md", "sleepo": "memory/context/assistant-soul.md"}
TITLES = {"company": "How to weigh what people say (the company soul)",
          "cpo": "What good looks like in the role (the role soul)",
          "sleepo": "How SleePO behaves (SleePO's soul)"}
# "cpo" is the role soul: the standard for the user's own role. Its file and heading come from the profile
# (role_soul_file, role_soul_title; Sam's: cpo-soul.md, "What good product leadership looks like (the CPO soul)").


def files():
    from . import profile
    p = profile.get()
    return {**FILES, "cpo": p["role_soul_file"] or FILES["cpo"]}


def titles():
    from . import profile
    p = profile.get()
    return {**TITLES, "cpo": p["role_soul_title"] or f"What good looks like in the role (the {p['role_short'] or 'role'} soul)"}
SKIP = ("Still to add", "Sources", "How to change it")   # notes to Sam, not instructions to an agent

COMPANY_RULES = "How the assistant must apply this"
CPO_RULES = "How SleePO applies this"
CPO_DRAFTS = "In what goes out under my name"

# (agent key as in agents.REGISTRY, label, soul, sections, how). sections None = the whole page.
# how: "carried" = the text goes into a tool-free prompt; "reads" = a session with file access is told to read the page;
# "inline" = the agent's own prompt restates the rules it needs (note says which); "summary" = through CLAUDE.md only.
USES = [
    ("todo", "Task suggestions", "company", [COMPANY_RULES], "carried"),
    ("todo", "Task suggestions", "cpo", [CPO_RULES], "carried"),
    ("brief", "Daily brief", "company", [COMPANY_RULES], "carried"),
    ("brief", "Daily brief", "cpo", [CPO_RULES], "carried"),
    ("prep", "Meeting briefs", "company", None, "carried"),
    ("prep", "Meeting briefs", "cpo", None, "carried"),
    ("followup", "Meeting follow-ups", "company", None, "carried"),
    ("followup", "Meeting follow-ups", "cpo", None, "carried"),
    ("strategy", "Strategy", "company", [COMPANY_RULES], "carried"),
    ("strategy", "Strategy", "cpo", None, "carried"),
    ("topics", "Top of mind", "company", [COMPANY_RULES], "carried"),
    ("topics", "Top of mind", "cpo", [CPO_RULES], "carried"),
    ("graph", "Graph memory refresh", "company", [COMPANY_RULES], "carried"),
    ("initiatives", "Initiative updates", "company", [COMPANY_RULES], "carried"),
    ("initiatives", "Initiative updates", "cpo", [CPO_RULES], "carried"),
    ("replies", "Reply drafting", "company", None, "carried"),
    ("replies", "Reply drafting", "cpo", [CPO_DRAFTS], "carried"),
    ("cowork", "Create in Claude (Actions and Inbox)", "cpo", [CPO_DRAFTS], "carried"),
    ("briefing", "Email briefings (Inbox)", "company", [COMPANY_RULES], "carried"),
    ("briefing", "Email briefings (Inbox)", "cpo", [CPO_RULES], "carried"),
    ("people", "Where things stand (person pages)", "company", [COMPANY_RULES], "carried"),
    ("review", "File reviews (Messages)", "company", [COMPANY_RULES], "carried"),
    ("review", "File reviews (Messages)", "cpo", [CPO_RULES, CPO_DRAFTS], "carried"),
    ("loops", "Open items check", "company", None, "inline"),
    ("speakers", "Who said what", "company", None, "inline"),
    ("chat", "Ask SleePO", "company", None, "reads"),
    ("chat", "Ask SleePO", "cpo", None, "reads"),
    ("chat", "Ask SleePO", "sleepo", None, "reads"),
    ("skills", "/week, /decide", "company", None, "reads"),
    ("skills", "/week, /decide", "cpo", None, "reads"),
    ("skills", "/triage, /draft", "company", None, "reads"),
    ("skills", "/draft", "cpo", [CPO_DRAFTS], "reads"),
    ("all", "Every Claude run", "sleepo", None, "summary"),
]
NOTES = {
    "loops": "Extraction keeps who said it and one source per item; the review closes items only on evidence (assist/loops.py).",
    "speakers": "Every point sits on a real turn of that speaker; Granola's spellings are kept, not corrected (assist/speakers.py).",
    "all": "CLAUDE.md is loaded into every claude -p run from this folder and carries the soul's lines; the code enforces them.",
}


def _raw(name):
    p = db.ASSIST / files()[name]
    return p.read_text() if p.exists() else ""


def sections(text):
    """[(heading, body)] for each '## ' section, frontmatter and the '# ' title line dropped. The text before the first
    '## ' heading is returned under the heading ''."""
    t = re.sub(r"\A---\n.*?\n---\n", "", text or "", flags=re.S)
    t = re.sub(r"\A\s*# [^\n]*\n", "", t)
    out, head, buf = [], "", []
    for line in t.splitlines():
        if line.startswith("## "):
            out.append((head, "\n".join(buf).strip()))
            head, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if b or h]


def page(name):
    """The whole page as an agent should read it: no frontmatter, no notes to Sam (SKIP)."""
    parts = []
    for h, b in sections(_raw(name)):
        if h.startswith(SKIP):
            continue
        parts.append((f"### {h}\n" if h else "") + b)
    return "\n\n".join(p for p in parts if p.strip())


def section(name, heading):
    """The body of the section whose heading starts with `heading`, or None when the page has no such section."""
    for h, b in sections(_raw(name)):
        if h.startswith(heading):
            return b
    return None


def text(name, wanted=None):
    """(text, missing): the named sections joined, or the whole page; sections not found are listed in `missing` and the
    whole page is carried instead, so a renamed heading never leaves an agent without its rules."""
    if not wanted:
        return page(name), []
    got, missing = [], []
    for w in wanted:
        b = section(name, w)
        (got if b else missing).append(b or w)
    return (page(name) if missing else "\n\n".join(got)), missing


def block(agent, level=2):
    """The soul text a tool-free agent carries, each page under its own heading. Empty when the agent carries none."""
    hashes = "#" * level
    parts = []
    for key, _, name, wanted, how in USES:
        if key != agent or how != "carried":
            continue
        t, _ = text(name, wanted)
        if t:
            t = re.sub(r"^### ", "#" * (level + 1) + " ", t, flags=re.M)
            parts.append(f"{hashes} {titles()[name]}\n{t}")
    return "\n\n".join(parts)


def uses():
    """For the Soul page: per page, its file, when it was updated and who reads it (how, which sections, how many characters,
    and any section that was not found)."""
    out = {}
    for name, rel in files().items():
        raw = _raw(name)
        m = re.search(r"^updated:\s*(\S+)", raw, re.M)
        out[name] = {"file": rel, "exists": bool(raw), "updated": m.group(1) if m else None, "chars": len(page(name)), "used_by": []}
    for key, label, name, wanted, how in USES:
        t, missing = text(name, wanted) if how == "carried" else ("", [])
        out[name]["used_by"].append({"agent": key, "label": label, "how": how, "sections": wanted or ["whole page"],
                                     "chars": len(t) if how == "carried" else None, "missing": missing, "note": NOTES.get(key)})
    return out
