"""Mail Sam put on Needs reply himself (Inbox: Add to Needs reply, or reopening its item): added_by_sam is when he did,
so the register keeps the item whatever replies.asked says, until he replies in the thread or removes it."""


def up(con):
    have = {r[1] for r in con.execute("PRAGMA table_info(loops)")}
    if "added_by_sam" not in have:
        con.execute("ALTER TABLE loops ADD COLUMN added_by_sam TEXT")
