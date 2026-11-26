"""Revising a draft email with Sam's request (Sam, 28 Oct 2026: "when I enter the change the email doesn't look natural, and
sometimes I click Revise this draft and it doesn't really change anything").

Shared by the Inbox reply writer (replies.prompt) and new emails in Drafts (new_mail.prompt). What changed from the first
version (replies.REVISE, 22 Oct 2026):
  - The request is carried out fully and visibly: a tone request rewrites the wording throughout instead of adding a line,
    and "shorter" means clearly shorter. "Keep everything else word for word" made revisions bolt sentences on (a thank-you
    line and "Appreciate everyone moving quickly" for "Warmer") or change a word or two.
  - The email must read as written in one go: the sentences around a change are reworked so it flows.
  - What Sam typed himself is kept (his own wording, found by comparing the draft with the last text SleePO wrote), and so are
    the facts, asks, owners, dates, greeting, sign-off and [FILL] blanks he did not ask about.
  - The earlier requests in the same session go with it, so "more" and "not that" make sense.
  - The block comes last in the prompt, after the context, so the request is what the model reads before it writes.
  - A revision that comes back almost unchanged is run once more, told so (unchanged, NUDGE); an empty request is refused by
    the app (the Revise button needs words or a quick ask).
"""
import difflib
import re
from .promptkit import USER   # the user in prompt text (assist/profile.py)

VERSION = "revise-2026-10-28"

BLOCK = f"""# Revise the current draft
This is the email {USER.first} has in front of {USER.him}, between <draft> tags. It is the text to revise, not a new email to write.
<draft>
{{draft}}
</draft>
{{mine}}{{history}}
# {USER.first}'s request now
{{ask}}

How to revise:
- Carry out the request fully, so that someone comparing before and after sees at once that it was done. A request about tone
  ("warmer", "more direct", "more formal", "friendlier") changes the wording throughout the email, not one added line.
  "Shorter" means at least a third shorter, keeping every ask; "longer" adds substance the context supports, not padding.
- The result must read as one email {USER.first} wrote in one go, in {USER.his} voice. Rework the sentences around a change so it flows;
  never bolt a sentence on at the start or the end. No stock phrases ("I hope this helps", "Appreciate everyone…",
  "Just wanted to…", "Please don't hesitate"), no repeated thanks.
- Keep what the request is not about: the facts, names, numbers, dates, the asks and who owns them, the greeting, the sign-off,
  and any [FILL: …] blank the request does not fill. {USER.first}'s own wording (listed above, when there is any) stays unless the
  request is about it. Add no new facts, asks, dates or commitments unless the request or the context gives them.
- If the draft already does what {USER.he} asks, still make the clearest improvement in that direction, and say so in notes.
In notes: one short line on what you changed, starting with a verb ("Cut the second paragraph and…")."""

NUDGE = (f"\n\nYour previous attempt returned the draft almost unchanged. {USER.first} asked for a change: make it now, clearly, "
         "following the rules above.")


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if len(s.strip()) > 12]


def own_wording(current, base):
    """Sentences in the draft on screen that are not in the last text SleePO wrote: what Sam typed or changed himself."""
    if not (base or "").strip() or (current or "").strip() == (base or "").strip():
        return []
    norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
    theirs = {norm(s) for s in _sentences(base)}
    return [s for s in _sentences(current) if norm(s) not in theirs][:12]


def block(current, ask, base=None, history=()):
    """The revise section of a writer's prompt: the draft, Sam's own wording, earlier requests, the request and the rules."""
    mine = own_wording(current, base)
    hist = [str(h).strip() for h in (history or []) if str(h).strip()][-5:]
    return (BLOCK.replace("{draft}", (current or "").strip()[:12000])
            .replace("{mine}", (f"\n# {USER.first}'s own wording in it ({USER.he} typed these {USER.himself}: keep them)\n" + "\n".join(f"- {s}" for s in mine) + "\n") if mine else "")
            .replace("{history}", ("\n# What he asked for earlier in this session, oldest first (already done in the draft)\n" + "\n".join(f"- {h}" for h in hist) + "\n") if hist else "")
            .replace("{ask}", (ask or "").strip()))


STYLE = re.compile(r"warm|friendl|direct|short|concise|brief|tight|formal|casual|polite|firm|softer|clear|punch|tone|natural|confident", re.I)


def unchanged(before, after, ask=""):
    """True when a revision did not do what was asked: the same words came back, or a request about style or length left
    the text almost as it was. A small factual change ("Friday, not Thursday") is a real revision."""
    norm = lambda t: re.sub(r"\W+", " ", (t or "").lower()).strip()
    if not norm(after):
        return False
    if norm(before) == norm(after):
        return True
    return bool(STYLE.search(ask or "")) and difflib.SequenceMatcher(None, before.strip(), after.strip()).ratio() > 0.95
