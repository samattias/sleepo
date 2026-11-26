"""Link roles and evidence (mentions.role/reason: from, to, speaker, mentioned...) and who said what in meetings
(meeting_speakers, loops.said_json; assist/speakers.py)."""


def up(con):
    from ..entities import ensure_schema
    from ..speakers import ensure_schema as speakers_schema
    ensure_schema(con)
    speakers_schema(con)
