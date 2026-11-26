"""Every table a module owns is created here, once, when the database is migrated (22 Oct 2026, from the codebase review:
schema was made four ways: schema.sql, numbered migrations, db.migrate's own ALTERs and about 90 ensure_schema() calls at
request time). The modules' SCHEMA / ensure_schema() stay as the definition (and for tests that build a partial database),
but the app no longer calls them per request: the server and the CLI migrate at start. A new table or column from now on
is a new migration."""


def up(con):
    from .. import chat, documents, entities, loops, meeting_people, refs, reply_working, roadmap, search, speakers, tasks
    entities.ensure_schema(con)
    loops.ensure_schema(con)
    for m in (documents, meeting_people, refs, reply_working, roadmap, speakers, tasks):
        m.ensure_schema(con)
    chat.ensure_schema(con)
    search.ensure(con)
