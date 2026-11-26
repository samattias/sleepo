"""Small pieces every tool-free prompt is built from (22 Oct 2026, from the codebase review).

untrusted() wraps text other people wrote (mail, messages, transcripts, documents) in a tag. The prompts tell the model
that whatever sits inside the tag is data, not instructions; that only holds while the text cannot close the tag itself, so
a closing tag inside the text (an email that contains "</context>" followed by "New instructions: ...") is defused.
read() is a memory or context file, cut to a length.
USER is the user in prompt text: f"... {USER.first}'s voice ..." (16 Nov 2026: prompts named one user; DESIGN-PERSONALISATION.md).
Module-level prompts read it when the module is imported, so a changed profile takes effect after a restart."""
import re

from . import db


def untrusted(tag, body, attrs=""):
    """<tag attrs>\\nbody\\n</tag>, with any </tag> inside body broken so it cannot end the block early."""
    safe = re.sub(rf"<(\s*/\s*{re.escape(tag)})(?=[\s>])", r"<\\\1", body or "", flags=re.I)
    return f"<{tag}{' ' + attrs if attrs else ''}>\n{safe}\n</{tag}>"


def read(rel, n):
    """A file under the Assist folder, cut to n characters ("" when missing)."""
    p = db.ASSIST / rel
    t = p.read_text() if p.exists() else ""
    return t if len(t) <= n else t[:n] + "\n…"


PRONOUNS = {"he": ("he", "his", "him", "himself"), "she": ("she", "her", "her", "herself")}


class _User:
    """The user's name, role, company, time zone and voice for prompt text, read from the profile (assist/profile.py) and
    the org (assist/org.py) each time an attribute is used. Unknown values read as neutral words, never as another person."""

    def _p(self):
        from . import profile
        return profile.get()

    @property
    def name(self):
        return self._p()["full_name"] or "the user"

    @property
    def first(self):
        return self._p()["first_name"] or "the user"

    @property
    def FIRST(self):
        return self.first.upper()

    @property
    def role(self):
        return self._p()["role"] or "a leader"

    @property
    def role_short(self):
        return self._p()["role_short"] or self.role

    @property
    def company(self):
        from . import org
        return org.name() or "their company"

    @property
    def tz(self):
        return self._p()["timezone"]

    @property
    def city(self):
        return self.tz.split("/")[-1].replace("_", " ")

    @property
    def signoff(self):
        return self._p()["signoff"] or "-" + self.first

    @property
    def spelling(self):
        return self._p()["spelling"]

    def _pro(self, i, who="user"):
        p = self._p()
        key = (p["pronouns"] if who == "user" else p["manager_pronouns"] or "").split("/")[0].strip().lower()
        forms = PRONOUNS.get(key)
        if forms:
            return forms[i]
        n = self.first if who == "user" else self.manager_first
        return [n, n + "'s", n, "themselves"][i]   # they/them or not set: the name keeps the grammar of he/she

    @property
    def not_free(self):
        """When the user takes no meetings, in words: "mornings or Fridays"."""
        from . import profile
        days, (h0, _), (h1, _), _ = profile.meeting_window()
        parts = (["mornings"] if h0 >= 12 else []) + (["afternoons"] if h1 <= 13 else [])
        parts += [n + "s" for i, n in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")) if i not in days]
        return " or ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 2 else parts) or "outside the free slots"

    @property
    def meeting_habit(self):
        """How the user meets, in words: "in the afternoon, 30 minutes, never Fridays"."""
        from . import profile
        days, (h0, _), (h1, _), mins = profile.meeting_window()
        when = "in the afternoon" if h0 >= 12 else "in the morning" if h1 <= 13 else "in working hours"
        off = [n + "s" for i, n in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")) if i not in days]
        return f"{when}, {mins} minutes" + (", never " + " or ".join(off) if off else "")

    @property
    def role_soul(self):
        """The file name of the user's role soul ("cpo-soul.md")."""
        from . import soul
        return soul.files()["cpo"].rsplit("/", 1)[-1]

    @property
    def role_soul_about(self):
        """What the role soul is about, from its title: "what good product leadership looks like"."""
        import re
        from . import soul
        t = re.sub(r"\s*\([^)]*\)\s*$", "", soul.titles()["cpo"]).strip()
        return t[:1].lower() + t[1:]

    @property
    def about_what(self):
        """" (business process management software)": what the company makes, in brackets, or "" (the org pack's about)."""
        from . import org
        return org.about("what")

    @property
    def about_what_comma(self):
        """", business process management software" (inside brackets that are already open), or ""."""
        from . import org
        t = (org.get()["about"] or {}).get("what") or ""
        return f", {t}" if t else ""

    @property
    def about_strategy(self):
        from . import org
        return org.about("strategy")

    @property
    def about_review(self):
        from . import org
        return org.about("review")

    @property
    def manager(self):
        return self._p()["manager"] or "their manager"

    @property
    def manager_first(self):
        m = self._p()["manager"]
        return m.split()[0] if m else "their manager"

    @property
    def manager_role(self):
        return self._p()["manager_title"] or "manager"

    @property
    def reports_to(self):
        """" · reports to Milo Marsh (CEO)", or "" when the manager is not known."""
        p = self._p()
        return f" · reports to {p['manager']}" + (f" ({p['manager_title']})" if p["manager_title"] else "") if p["manager"] else ""

    @property
    def org_chart_label(self):
        from . import org
        return org.section("org_chart", {}).get("label") or "org chart"

    @property
    def org_chart_as_of(self):
        """"BambooHR org chart, Oct 2026": the org chart and its date."""
        from . import org
        c = org.section("org_chart", {})
        return (c.get("label") or "org chart") + (f", {c['as_of']}" if c.get("as_of") else "")

    @property
    def skip_personal(self):
        """'the personal "Sam <> Robin/Terry sync"', or "personal meetings"."""
        t = self._p()["personal_meetings_title"]
        return f'the personal "{t}"' if t else "personal meetings"

    @property
    def ignore_personal(self):
        """'the "Sam <> Robin/Terry sync" (personal)', or "personal meetings"."""
        t = self._p()["personal_meetings_title"]
        return f'the "{t}" (personal)' if t else "personal meetings"

    @property
    def plan_file(self):
        return self._p()["plan_file"] or "memory/context/plan.md"

    @property
    def plan_title(self):
        return self._p()["plan_title"] or "Plan"

    he = property(lambda self: self._pro(0))
    his = property(lambda self: self._pro(1))
    him = property(lambda self: self._pro(2))
    himself = property(lambda self: self._pro(3))
    He = property(lambda self: self._pro(0)[:1].upper() + self._pro(0)[1:])
    His = property(lambda self: self._pro(1)[:1].upper() + self._pro(1)[1:])
    mgr_he = property(lambda self: self._pro(0, "manager"))     # the user's manager
    mgr_his = property(lambda self: self._pro(1, "manager"))
    mgr_him = property(lambda self: self._pro(2, "manager"))
    mgr_His = property(lambda self: self._pro(1, "manager")[:1].upper() + self._pro(1, "manager")[1:])


USER = _User()
