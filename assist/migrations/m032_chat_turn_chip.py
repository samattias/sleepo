"""Ask SleePO keeps the context chip a question was asked with (16 Nov 2026: "that should show us a chip in the chat"), so a
reopened conversation still shows what it was about: chat_turns.ctx_json (assist/chat.py)."""


def up(con):
    from .. import chat
    chat.ensure_schema(con)
