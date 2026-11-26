"""What SleePO remembers from what Sam tells it (assist/remember.py; Sam, 28 Oct 2026, option A of the mem0 review): one
row per memory, a preference, a fact he stated or a correction, with his words, who it is about, what it applies to and
when it expires. Idempotent."""


def up(con):
    from .. import remember
    remember.ensure_schema(con)
