"""Top of mind (assist/topics.py; Sam, 28 Oct 2026): the topics Sam discussed in the last days, one row per topic of the
latest run, plus the ones he set aside. Idempotent."""


def up(con):
    from .. import topics
    topics.ensure_schema(con)
