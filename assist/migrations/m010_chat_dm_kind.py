"""Teams direct messages arrive as conversation_kind 'oneOnOne' as well as 'dm': store them as 'dm', the one kind every
reader (open items, Actions, linking, meeting prep) treats as a direct message. assist/chatsync.py normalises new ones."""


def up(con):
    con.execute("UPDATE chat_messages SET conversation_kind='dm' WHERE conversation_kind='oneOnOne'")
