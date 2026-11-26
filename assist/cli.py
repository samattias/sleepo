"""assist · command line.

  assist migrate                 create or upgrade the database
  assist import-legacy           load everything the prototype collected (idempotent)
  assist import-kb [vault]       import the Acme emery yates vault (default Documents/acme-kb)
  assist ingest <file.json>...   load an ingest bundle written by an agent (see ingest.py); default: inbox/queue/*.json
  assist calendar-merge <pull.json>   merge a calendar pull {"window", "events"} into inbox/calendar/events.json (replace by id)
  assist todo                    regenerate the prioritised Actions list (headless Claude, no tools)
  assist doc-file [N]             give every unfiled document a folder (initiative, type) for the Documents page
  assist company-logos [N] [--redo]  fetch the logo of every listed company that has none yet (assist/logos.py)
  assist serve [port]            run the API + page at http://localhost:8765
  assist stats                   row counts
  assist doctor                  is this install ready? checks the data folder, profile, org pack, Claude, permissions and sign-ins
  assist profile [set|unset <field> [value]]   the user's profile (name, addresses, role, time zone, voice): assist/profile.py
  assist org [set|unset <field> [value]]       the organisation (its name; the rest of the org pack in phase 3): assist/org.py
  assist search-index            rebuild the unified search index (also runs after every load)
  assist predraft [--limit N] [--redo]   write a recommended response (reply, reply all or forward) for each email waiting on Sam that has none (tool-free; the Inbox opens with it)
  assist mail-login              sign in to Microsoft Graph once (device code, Mail.Read)
  assist chat-titles             name chat conversations with a short summary (tool-free, small model); the app does it after each answer
  assist onboard-scan [--chat]   the onboarding agent: import, read, then one tool-free run that infers the profile and bets (the Welcome page starts it)
  assist chat-pull [--from YYYY-MM-DD --to YYYY-MM-DD]   pull Teams and Slack now and ingest (the Messages page's Refresh starts it in the background); --from/--to re-reads that window (backfill)
  assist task-links [--match [--days N]]   link mail, chat and meeting notes to Sam's tasks: same thread as a task's sources; --match adds a tool-free match of recent items
  assist outlook-login           sign in once so the Inbox can save reply drafts into your Outlook threads (Mail.ReadWrite; never sends)
  assist granola-login           sign in to Granola's MCP once (device code; SleePO's own client) for meeting screenshots
  assist granola-shots [--days N]   screenshots of the shared screen from recent meetings (default 3 days, at most 30); exit 2 = not signed in
  assist mail-sync [--since D]   full Inbox + Sent sync: bodies, recipients, attachments (incremental after the first run)
  assist mail-window             where the next connector pull (/mail-full) should start, per folder
  assist calendar-local [--dry-run]       calendar from Calendar.app's local store (live; your replies; needs Full Disk Access)
  assist mail-local [--since D] [--force]   Inbox + Sent from Apple Mail's local store (fast; needs Full Disk Access)
  assist mail-saved <inbox|sent> <file>...   oversized messages saved by read_resource -> a mail-full bundle (/mail-full)
  assist sf-bundle <file.json>...  Salesforce: saved connector results -> inbox/queue/salesforce-<date>.json (/salesforce skill)
  assist sf-closed <file.json>...  Salesforce: saved Closed Won/Lost results -> inbox/queue/salesforce-closed-<date>.json
  assist sf-accounts <file.json>... Salesforce: saved account lists -> inbox/queue/salesforce-accounts-<date>.json (type, website, mail domain)
  assist ask-sql "SELECT …"      one read-only query (the in-app chat's database access; see assist/chat.py)
  assist ask-search "words"      the app's search, as text (in-app chat)
  assist ask-today               today's date and time in London (in-app chat)
  assist ask-read REF            one mail, message, meeting (m-45), document (sp-12), open item (l-7) or decision (d-9) in full (in-app chat)
  assist ask-file PATH           the text of a Word, Excel, PowerPoint, PDF or text file on this Mac (in-app chat)
  assist ask-copy PATH           copy a file into the chat conversation's workspace folder (in-app chat)
  assist ask-do PLAN             ask to do steps on this Mac (folders, copy, move, download, open); waits for the user's answer in the app (in-app chat)
  assist ask-sharepoint "WORDS"  one read-only SharePoint and OneDrive search: files with their links (in-app chat)
  assist ask-make FORMAT FILE    make a docx/rtf/odt from .md or .html, or an xlsx from .csv, in that workspace (in-app chat)
  assist ask-code repos|search|files|ls|read …   the company's source code from the git clones on this Mac (in-app chat; assist/codebase.py)
  assist code-fetch [--repo NAME] [--due]   update each clone's default branch from GitLab (Code base page; weekly in the full refresh)
  assist ini-setup               canonical initiatives (assist/initiatives.py), fold the old ones, rebuild keyword links
  assist ini-tag [--days N]      Claude files new mail, chat, meetings, commitments, decisions against initiatives
  assist ini-updates             SleePO rewrites every initiative's status (current at once) and suggests actions as tasks
  assist strategy                the weekly strategy memo (tool-free): macro-level thoughts across everything, for the Strategy page
  assist roadmap-import [--modified ISO] [--force]   load inbox/roadmap/initiatives.tsv (Rowan's Roadmap Workbook, Initiatives sheet) when it differs from the snapshot
  assist roadmap-pull   read Rowan's workbook now and load it if it changed (the Roadmap page's Refresh starts it in the background)
  assist link [--full]           entity linking: tie items to people, organisations (Salesforce accounts, mail domains), initiatives
  assist loops [sync|review|extract|dedupe|all]   the open-items register: sync from sources, evidence review, new commitments/decisions, reworded duplicates
  assist brief                   write today's brief from the database (tool-free run) and ingest it
  assist sp-index [--since ISO]   index SharePoint/OneDrive files changed since the last index, by topic (assist/sp_index.py)
  assist kb-sync [--repo NAME]    read the emery yates and product docs repositories in full through the connector (assist/kb_sync.py)
  assist sp-read-list [--limit N] recent SharePoint/OneDrive files to read in full (for /docs-read)
  assist sp-text <file.json>     store text read through the connector: [{"item_id", "text"}]
  assist doc-cards [--force]     Claude writes a card (summary, facts, initiatives, version, sensitivity) for each document worth reading
  assist scan-local              index documents in ~/Downloads, ~/Desktop and ~/Documents (source "Local files")
  assist prep-upcoming [--days N] [--missing|--stale]   upcoming meetings worth a brief (JSON); --stale adds briefs with new material since
  assist prep-write <event_id> [--notes "..."] | --upcoming [--days N]   write meeting briefs with a tool-free run (assist/prepgen.py)
  assist remember-learn [--days N] | remember-list   what SleePO remembers from what Sam told it (assist/remember.py)
  assist topics [--days N] [--dry]                   top of mind: the topics Sam discussed in the last days (assist/topics.py)
  assist embed-sync                                 search by meaning: embed the search index locally (assist/embed.py)
  assist prep-context <event_id>                context pack for one meeting, for the /prep skill
  assist followup-write <meeting_id> [--notes "..."] | --recent [--hours N]   actions from what was said in a recorded meeting (assist/followup.py)
  assist followup-context <meeting_id>          the context pack a follow-up is written from
  assist eval-seed-extract [N]   add N unreviewed cases to evals/golden/extract.json, pre-filled from the register, for Sam to correct
  assist eval-extract [--include-unreviewed]   precision / recall / direction of open-item extraction on the golden set
  assist tickets-todo / tickets-import [file]   Jira issues mentioned in content: keys to read, then store title/type/status
  assist eval-links              link quality: precision / recall on Sam's ticks and crosses, coverage per kind of item
  assist eval-needs-reply [days] does "needs a reply" match the mail Sam actually answered? precision / recall per reason
  assist demo [start|stop|reset|status] [--open]   a separate demo copy on :8766 to try first-run setup as a new user
  assist eval-online [days]      scorecard from Sam's own actions: drops, dismissals, thumbs, edits, draft vs sent, prep grounding
  assist eval-replies [N] [--no-judge]   backtest reply drafts against what Sam actually sent
"""
import glob
import os
import json
import sys
from pathlib import Path

from . import db
from .promptkit import USER   # the user in prompt text (assist/profile.py)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    cmd = argv[0] if argv else "help"
    con = db.connect()
    db.migrate(con)
    if cmd == "migrate":
        print(f"database ready at {db.db_path()}")
    elif cmd == "import-legacy":
        from . import importer
        importer.run_all(con)
        print("legacy import complete")
    elif cmd == "ingest":
        from . import ingest
        files = argv[1:] or sorted(glob.glob(str(db.ASSIST / "inbox" / "queue" / "*.json")))
        if not files:
            print("nothing to ingest (inbox/queue is empty)")
        import sqlite3 as _sq
        import time as _t

        def locked_retry(fn):   # parallel pulls can hold the write lock: wait and retry rather than fail
            for attempt in range(8):
                try:
                    return fn()
                except _sq.OperationalError as e:
                    if "locked" not in str(e) or attempt == 7:
                        raise
                    con.rollback()
                    _t.sleep(5 * (attempt + 1))

        def load(f):
            if not Path(f).exists():   # another run already ingested it (a committed bundle leaves the queue at once)
                return False
            print(ingest.ingest_file(con, Path(f), index=False))
            return True

        loaded = False
        try:
            for f in files:
                loaded = locked_retry(lambda f=f: load(f)) or loaded
        except Exception:
            if loaded:   # the bundles committed before the failure still reach the search index
                try:
                    locked_retry(lambda: ingest.reindex(con))
                except Exception as e:
                    print(f"search rebuild skipped: {e}")
            raise
        if loaded:   # one search rebuild and linking pass for the whole queue, not one per bundle
            locked_retry(lambda: ingest.reindex(con))
    elif cmd == "calendar-merge":
        from . import importer
        if len(argv) < 2:
            sys.exit("usage: assist calendar-merge <pull.json>")
        r = importer.merge_calendar(json.loads(Path(argv[1]).read_text()))
        print(f"calendar: {r['added']} events added, {r['replaced']} replaced ({r['moved']} moved), {r['removed']} no longer on the "
              f"calendar in inbox/calendar/events.json")
    elif cmd == "calendar-import":   # load events.json into the database and re-match recordings (the Calendar page's refresh)
        from . import importer
        importer.import_calendar(con)
    elif cmd == "sync-granola":
        from . import importer
        importer.import_granola(con)
        importer.import_calendar(con)
        con.commit()
        print("granola + calendar synced into the database")
    elif cmd == "import-kb":
        from . import kb
        total, new = kb.import_kb(con, argv[1] if len(argv) > 1 else None)
        print(f"emery yates: {total} notes ({new} new)")
    elif cmd == "import-orgchart":
        from . import orgchart
        n, links = orgchart.import_orgchart(con, argv[1] if len(argv) > 1 else str(Path.home() / "Downloads" / "org_chart.pdf"))
        print(f"org chart: {n} people, {links} reporting lines")
    elif cmd == "import-avatars":
        from . import avatars
        m, k = avatars.import_avatars(con, argv[1] if len(argv) > 1 else str(Path.home() / "Downloads" / "org_chart.pdf"))
        print(f"avatars: {m} photos matched, {k} placeholders skipped")
    elif cmd == "classify-people":
        from . import affiliations
        print(f"classified {affiliations.classify(con)} people")
    elif cmd == "import-docs":
        from . import importer
        importer.import_documents(con); con.commit()
        con.execute("INSERT INTO docs_fts(docs_fts) VALUES ('rebuild')"); con.commit()
        print("documents re-imported")
    elif cmd == "todo":
        from . import todo
        todo.generate(con)
    elif cmd == "tasks":   # Tasks (assist/tasks.py): cutover | sync | suggest | all (sync, then suggest)
        from . import tasks
        what = argv[1] if len(argv) > 1 else "sync"
        if what == "cutover":
            tasks.cutover(con)
        if what in ("sync", "all"):
            tasks.sync(con)
        if what in ("suggest", "all"):
            from . import jobs
            with jobs.exclusive("tasks-suggest") as got:   # the refresh's run and Generate suggestions never overlap
                if got:
                    tasks.suggest(con)
                else:
                    print("tasks suggest: another run is going")
    elif cmd == "task-preplan":   # tasks proposed in the background for mail waiting on Sam (assist/tasks.py preplan)
        from . import tasks
        limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 6
        from . import jobs
        with jobs.exclusive("task-preplan") as got:   # one run at a time, whoever starts it
            if got:
                tasks.preplan(con, limit=limit, log=lambda x: print(x, flush=True))
            else:
                print("task-preplan: another run is going")
    elif cmd == "calendar-refresh":   # Meetings › Refresh, started by the server in the background (assist/calrefresh.py)
        from . import calrefresh
        calrefresh.main(granola="--no-granola" not in argv)
    elif cmd == "remember-learn":   # what Sam told SleePO since the last run, kept as memories (assist/remember.py)
        from . import remember
        res = remember.learn(con, days=int(argv[argv.index("--days") + 1]) if "--days" in argv else 14)
        print(json.dumps(res))
    elif cmd == "topics":   # top of mind: the topics of the last days, filed under the initiatives (assist/topics.py)
        from . import jobs, topics
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else topics.DAYS
        if "--dry" in argv:
            print(json.dumps(topics.run(con, days=days, dry=True)))
            return
        with jobs.exclusive("topics") as got:   # one run at a time, whoever starts it
            if not got:
                print("topics: another run is going")
                return
            print(json.dumps(topics.run(con, days=days, log=lambda x: print(x, flush=True))))
    elif cmd == "remember-list":
        from . import remember
        for m in remember.listing(con)["memories"]:
            print(f"M{m['id']} · {m['kind']} · {','.join(m['scope'])} · {', '.join(m['people']) or USER.first} · {m['text']}")
    elif cmd == "embed-sync":   # search by meaning: embed new and changed rows of the search index (assist/embed.py)
        from . import embed
        print(json.dumps(embed.sync(con)))
    elif cmd == "task-history":   # Sam's past tasks rebuilt from his actions (assist/task_history.py): new weeks; --redo all; --eval
        from . import jobs, task_history
        if "--eval" in argv:
            print(json.dumps(task_history.evaluate(con), indent=1))
            return
        from datetime import date as _date
        since = _date.fromisoformat(argv[argv.index("--since") + 1]) if "--since" in argv else None
        with jobs.exclusive("task-history") as got:   # one run at a time, whoever starts it
            if not got:
                print("task-history: another run is going")
                return
            ok, note = True, ""
            try:
                n = task_history.build(con, since=since, redo="--redo" in argv, log=lambda x: print(x, flush=True))
                note = f"{n} tasks"
            except Exception as e:
                ok, note = False, str(e)[-200:]
                raise
            finally:
                task_history.STATE.parent.mkdir(parents=True, exist_ok=True)
                task_history.STATE.write_text(json.dumps({"running": False, "finished": db.now(), "ok": ok, "note": note}))
    elif cmd == "task-job":
        from . import tasks
        tasks.run_job(argv[1])
    elif cmd == "mail-draft-job":   # Inbox › Drafts: write or revise a new email (assist/new_mail.py)
        from . import new_mail
        new_mail.run_job(argv[1], db.ASSIST)
    elif cmd == "drafts-suggest":   # Inbox › Drafts: new emails SleePO recommends, stored as task suggestions (assist/new_mail.py)
        from . import jobs, new_mail
        with jobs.exclusive("drafts-suggest") as got:   # one run at a time: the refresh's and Suggest emails
            if got:
                new_mail.recommend(con, log=lambda x: print(x, flush=True))
            else:
                print("drafts-suggest: another run is going")
    elif cmd == "strategy":
        from . import strategy
        strategy.generate(con)
    elif cmd == "roadmap-status":
        from . import roadmap
        m = con.execute("SELECT value FROM settings WHERE key='roadmap:meta'").fetchone()
        print(m["value"] if m else "{}")
    elif cmd == "roadmap-import":   # loads only a sheet that differs from the snapshot; --force keeps a much shorter one
        from . import roadmap
        modified = argv[argv.index("--modified") + 1] if "--modified" in argv else None
        r = roadmap.import_tsv(con, roadmap.TSV, modified, force="--force" in argv)
        print(roadmap.note(r))
    elif cmd == "kb-sync":   # the emery yates and product docs, every note read through the connector (assist/kb_sync.py; weekly)
        from . import kb_sync, llm
        ok, _ = kb_sync.run(only=argv[argv.index("--repo") + 1] if "--repo" in argv else None,
                            on_result=lambda ev: llm.record_stream_result(ev, "kb-sync"))
        sys.exit(0 if ok else 1)
    elif cmd == "sp-index":   # the SharePoint & OneDrive index since the last one (assist/sp_index.py; every full refresh)
        from . import llm, sp_index
        ok, _ = sp_index.run(after=argv[argv.index("--since") + 1] if "--since" in argv else None,
                             on_result=lambda ev: llm.record_stream_result(ev, "sp-index"))
        sys.exit(0 if ok else 1)
    elif cmd == "roadmap-pull":   # Roadmap › Refresh (assist/roadmap.py), started by the server in the background
        from .api import chat_files_cmd
        from . import roadmap
        roadmap.main(chat_files_cmd)
    elif cmd == "agent-run":
        from . import agent_runner
        sys.exit(0 if agent_runner.run(argv[1], argv[2], db.ASSIST) else 1)
    elif cmd == "reply-job":
        from . import replies
        replies.run_job(argv[1], db.ASSIST)
    elif cmd == "predraft":
        from . import replies
        limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 6
        from . import jobs
        with jobs.exclusive("predraft") as got:   # one run at a time, whoever starts it
            if not got:
                print("predraft: another run is going")
            else:
                if "--redo" in argv:   # write them again (after a prompt change): clears the stored pre-drafts first
                    con.execute("DELETE FROM reply_predrafts")
                    con.commit()
                replies.predraft(con, db.ASSIST, limit=limit, log=lambda x: print(x, flush=True))
    elif cmd == "deliverable-job":
        from . import deliverables
        deliverables.run_job(argv[1])
    elif cmd == "review-job":   # review a file shared in Teams (assist/file_review.py), started by the Messages page
        from . import file_review
        file_review.run_job(argv[1])
    elif cmd == "briefing-job":
        from . import briefing
        briefing.run_job(argv[1])
    elif cmd == "person-summary-job":   # where things stand with one person (assist/person_summary.py), from their page
        from . import person_summary
        person_summary.run_job(argv[1])
    elif cmd == "link":
        from . import entities
        entities.link(con, full="--full" in argv)
    elif cmd == "graph-stale":   # graph memory (DESIGN-GRAPH-MEMORY.md): mark what new items touch; --report: the churn and stale records
        from . import graph_memory
        if "--report" in argv:
            print(graph_memory.report_text(con, days=int(argv[argv.index("--days") + 1]) if "--days" in argv else 7))
        else:
            print(graph_memory.propagate(con))
    elif cmd == "graph-refresh":   # graph memory, phase 2 (assist/graph_refresh.py): bring the records with new material up to date; --dry prints the prompts
        from . import graph_refresh
        graph_refresh.run(con, dry="--dry" in argv)
    elif cmd == "speakers":   # who said what: statistics from the transcripts, then main points and open items placed (model, tool-free)
        from . import speakers, entities
        speakers.sync(con)
        if "--no-model" not in argv:
            speakers.points(con, limit=int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 40, force="--force" in argv)
        entities.link(con, log=lambda *_: None)
    elif cmd == "loops":
        from . import loops
        what = argv[1] if len(argv) > 1 else "all"
        failed = False
        for step, fn in (("extract", loops.extract), ("sync", loops.sync), ("review", loops.review), ("dedupe", loops.dedupe)):
            if what in (step, "all"):
                try:   # each step stands alone: a failed extract must not stop the sync or the review
                    res = fn(con)
                    if isinstance(res, dict) and res.get("error"):   # extract and review report a failed model run instead of raising
                        print(f"loops {step} failed: {res['error']}")
                        failed = True
                except Exception as e:
                    con.rollback()
                    print(f"loops {step} failed: {e}")
                    failed = True
        if failed:
            sys.exit(1)
    elif cmd == "company-logos":   # each listed company's logo, cached by web domain (assist/logos.py); network only, no model
        from . import logos
        n = next((int(a) for a in argv[1:] if a.isdigit()), None)
        logos.run(con, redo="--redo" in argv, limit=n, only=[a for a in argv[1:] if "." in a] or None)   # domains given: just those
    elif cmd == "doc-file":
        from . import documents
        n = next((int(a) for a in argv[1:] if a.isdigit()), None)
        res = documents.file_documents(con, limit=n)
        if res.get("documents") and not res.get("filed"):
            sys.exit(1)
    elif cmd == "brief":
        from . import briefgen
        briefgen.generate(con)
    elif cmd == "eval-seed-extract":
        from . import evals
        evals.seed_extract(con, n=int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 30)
    elif cmd == "eval-extract":
        from . import evals
        evals.eval_extract(con, include_unreviewed="--include-unreviewed" in argv)
    elif cmd == "tickets-todo":   # Jira issue keys the pull should read (one per line)
        from . import refs
        print("\n".join(refs.tickets_todo(con)))
    elif cmd == "tickets-import":
        from . import refs
        path = argv[1] if len(argv) > 1 else str(db.ASSIST / "inbox" / "jira" / "issues.json")
        print(f"jira: {refs.import_issues(con, path, db.now())} issues stored")
    elif cmd == "eval-links":
        from . import evals
        evals.eval_links(con)
    elif cmd == "eval-needs-reply":
        from . import evals
        evals.eval_needs_reply(con, days=int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 40)
    elif cmd == "eval-online":
        from . import evals
        evals.online(con, days=int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 30)
    elif cmd == "eval-replies":
        from . import evals
        n = int(next((a for a in argv[1:] if a.isdigit()), "5"))
        evals.eval_replies(con, n=n, judge="--no-judge" not in argv)
    elif cmd == "retention":
        from . import retention
        import json as _j
        print(_j.dumps(retention.apply(con) if "--apply" in argv else retention.report(con), indent=1))
    elif cmd == "export":
        # The app is the React page served at localhost:8765. The old static Assist.html embedded a copy of the data
        # (HR and legal threads included) into the OneDrive folder, so it is written only when asked for.
        print("export: nothing to do (the app reads the database live; the static Assist.html was retired)")
    elif cmd == "serve":
        import uvicorn
        port = int(argv[1]) if len(argv) > 1 else 8765
        __import__("os").environ["ASSIST_PORT"] = str(port)   # the server's own origin (api.TRUSTED_ORIGINS); the reloaded worker inherits it
        # Restart on demand (Sam, 23 Oct 2026): the server no longer restarts on every saved .py (16 restarts an hour with
        # several sessions coding made the whole app slow and cut refreshes off). It restarts when assist/reload.trigger
        # changes: `assist.cli restart`, run once a change is done and its tests pass.
        uvicorn.run("assist.api:app", host="127.0.0.1", port=port, log_level="warning",
                    reload=True, reload_dirs=[str(db.PKG)], reload_includes=[db.reload_trigger().name], reload_excludes=["*.py"],
                    timeout_graceful_shutdown=1)
    elif cmd == "demo":   # a separate demo copy for trying first-run setup as a new user (assist/demo.py); never touches this install
        from . import demo
        sys.exit(demo.main(argv[1:]))
    elif cmd == "doctor":   # is this install ready? read-only checks with how to fix each gap (assist/doctor.py)
        from . import doctor
        sys.exit(doctor.main())
    elif cmd in ("profile", "org"):   # show or set the user's profile / the org (assist/profile.py, assist/org.py)
        mod = __import__("assist." + cmd, fromlist=["save"])
        con = db.connect()
        db.migrate(con)
        if len(argv) >= 4 and argv[1] == "set":
            v = argv[3]
            if v.startswith("[") or v.startswith("{"):
                v = json.loads(v)
            mod.save(con, **{argv[2]: v})
        elif len(argv) >= 3 and argv[1] == "unset":
            mod.save(con, **{argv[2]: None})
        print(json.dumps(mod.get(con) if cmd == "org" else mod.complete(mod.from_db(con)), indent=2, ensure_ascii=False))
    elif cmd == "restart":   # restart the server to load code changes; waits for a running refresh and Ask SleePO answers unless --now
        import json as _j
        import time as _t
        import urllib.request
        for _ in range(0 if "--now" in argv else 360):
            try:
                running = _j.loads(urllib.request.urlopen(f"http://127.0.0.1:{db.PORT}/status", timeout=3).read()).get("running")
            except Exception:
                running = False
            if not running:
                break
            print("a refresh is running; restarting when it ends…", flush=True)
            _t.sleep(10)
        for _ in range(0 if "--now" in argv else 60):   # Ask SleePO answers run in the server: wait up to 10 minutes for them
            try:
                n = len(_j.loads(urllib.request.urlopen(f"http://127.0.0.1:{db.PORT}/api/chat/live", timeout=3).read()).get("jobs") or [])
            except Exception:
                n = 0
            if not n:
                break
            print(f"{n} Ask SleePO answer{'s are' if n > 1 else ' is'} still running; restarting when done…", flush=True)
            _t.sleep(10)
        db.reload_trigger().write_text(__import__("datetime").datetime.now().isoformat())
        print("server restarting: back in a few seconds")
    elif cmd == "mail-login":
        from . import mailsync
        mailsync.login()
    elif cmd == "chat-titles":   # summary titles for chat conversations that have none (assist/chat.py summarize)
        from . import chat
        chat.summarize_missing(log=lambda x: print(x, flush=True))
    elif cmd == "chat-files":   # read the files shared in Teams chats that SleePO does not hold yet (assist/chat_files.py)
        from .api import chat_files_cmd
        from . import chat_files
        chat_files.run(log=lambda x: print(x, flush=True), claude_cmd=chat_files_cmd)
    elif cmd == "chat-files-store":   # run by the chat-files Claude run: store the text it read, then delete its file
        from . import chat_files
        print(f"{chat_files.store_file(argv[1])} shared file(s) stored")
    elif cmd == "onboard-scan":   # the Welcome page's onboarding agent (assist/onboard_agent.py), started by the server
        from . import onboard_agent
        onboard_agent.run(chat="--chat" in argv, log=lambda x: print(x, flush=True))
    elif cmd == "chat-pull":   # the Messages page's Refresh (assist/api.py chat_pull_run), started by the server
        from .api import chat_pull_run, _chat_write
        if "--from" in argv:   # a backfill from the terminal; the Messages page shows it as Pulling…
            import os
            _chat_write({"running": True, "started": db.now(), "pid": os.getpid()})
            chat_pull_run((argv[argv.index("--from") + 1], argv[argv.index("--to") + 1]))
        else:
            chat_pull_run()
    elif cmd == "task-links":
        from . import task_links
        task_links.sync_threads(con, log=lambda x: print(x, flush=True))
        if "--match" in argv:
            from . import jobs
            days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 5
            with jobs.exclusive("task-links-match") as got:   # one match at a time, whoever starts it
                if got:
                    task_links.match(con, db.ASSIST, days=days, log=lambda x: print(x, flush=True))
                else:
                    print("task links: another match is running")
    elif cmd == "outlook-login":
        from . import outlook_drafts
        outlook_drafts.login()
    elif cmd == "granola-login":
        from . import granola_shots
        granola_shots.login()
    elif cmd == "granola-shots":
        from . import granola_shots
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 3
        try:
            res = granola_shots.sync(con, days=days, log=lambda s: print(s, flush=True))
        except granola_shots.NotSignedIn as e:
            print(f"not signed in to Granola's MCP{(' (' + str(e) + ')') if str(e) else ''}: run  ~/.assist/venv/bin/python -m assist.cli granola-login")
            sys.exit(2)
        if res["new"]:
            from . import search
            n, t = search.build(con)
            print(f"search index: {n} entries ({t}s)")
    elif cmd == "mail-sync":
        from . import mailsync
        since = argv[argv.index("--since") + 1] if "--since" in argv else None
        mailsync.sync(con, since=since, log=lambda s: print(s, flush=True))
    elif cmd == "mail-window":
        from . import mailsync
        for k, v in mailsync.window(con).items():
            print(f"{k}: {v}")
    elif cmd == "mail-local":
        from . import applemail
        try:
            applemail.sync(con, since=argv[argv.index("--since") + 1] if "--since" in argv else None, force="--force" in argv,
                           log=lambda s: print(s, flush=True), quiet="--quiet" in argv)   # --quiet: no write when nothing changed
        except applemail.NoAccess as e:
            print(f"!! {e}"); sys.exit(2)
    elif cmd == "calendar-local":
        from . import applecal
        try:
            applecal.sync(con, log=lambda s: print(s, flush=True), dry_run="--dry-run" in argv)
        except applecal.NoAccess as e:
            print(f"!! {e}"); sys.exit(2)
        except applecal.Stale as e:
            print(f"!! {e}"); sys.exit(3)
    elif cmd == "mail-saved":
        from . import mailsaved
        out, n, bad = mailsaved.build(argv[1], argv[2:])
        print(f"{out}: {n} messages" if out else "nothing converted")
        for b in bad:
            print(f"  unreadable: {b}")
    elif cmd == "sf-bundle":
        from . import sfsync
        out, n, closed, capped = sfsync.build(con, argv[1:])
        print(f"{out}: {n} open opportunities, {closed} marked no longer open")
        for f in capped:
            print(f"INCOMPLETE: {f} hit the {sfsync.CAP}-row cap; split that window and rerun")
    elif cmd == "ini-setup":
        from . import initiatives, ingest
        print(ingest.ingest_bundle(con, initiatives.setup_bundle()))
        initiatives.retag_regex(con)
        print("keyword links rebuilt for commitments and decisions")
    elif cmd == "ini-tag":
        from . import initiatives
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 45
        print(initiatives.tag(con, days=days))
    elif cmd == "ini-updates":
        from . import initiatives
        for r in initiatives.active(con):
            try:
                initiatives.draft_update(con, r["slug"]); print(f"drafted: {r['name']}")
            except Exception as e:
                print(f"failed: {r['name']}: {e}")
    elif cmd in ("ask-sql", "ask-search", "ask-today"):
        from . import chat
        arg = " ".join(argv[1:])
        print(chat.ask_sql(arg) if cmd == "ask-sql" else chat.ask_search(arg) if cmd == "ask-search" else chat.ask_today())
    elif cmd == "ask-code":   # the company's source code, read from the clones on this Mac (assist/codebase.py)
        from . import codebase
        print(codebase.ask(argv[1:]))
    elif cmd == "code-fetch":   # Code base › Update, and weekly from the full refresh with --due (assist/codebase.py)
        from . import codebase
        repo = argv[argv.index("--repo") + 1] if "--repo" in argv[1:-1] else None
        if "--due" in argv and not codebase.due():
            print("code-fetch: updated within the last week, skipped")
        elif not codebase.fetch(repo):
            sys.exit(1)
    elif cmd == "ask-do":   # the chat asks to do steps on the Mac; waits for the user's answer in the app (assist/desktop.py)
        from . import desktop
        con.close()   # it may wait 25 minutes: hold no database connection meanwhile
        out, code = desktop.ask(" ".join(argv[1:]))
        print(out)
        sys.exit(code)   # before main's closing commit: the connection is closed (23 Nov 2026: an expired request then crashed)
    elif cmd == "ask-sharepoint":   # one read-only SharePoint and OneDrive search for the chat (assist/sp_index.py lookup)
        from . import sp_index
        q, flt = sp_index.parse_args(argv[1:])
        print(sp_index.folder_lookup(flt["folder"]) if flt.get("folder") else sp_index.lookup(q, **flt))
    elif cmd == "ask-review":   # the chat's view of a shared file's review (assist/file_review.py as_text)
        from . import file_review
        arg = " ".join(argv[1:]).strip().removeprefix("ca-")
        print(file_review.as_text(con, int(arg)) if arg.isdigit() else "Usage: ask-review <attachment id>")
    elif cmd in ("ask-read", "ask-file", "ask-copy", "ask-make"):
        from . import chat_tools
        if cmd == "ask-make":
            print(chat_tools.ask_make(" ".join(argv[2:]), argv[1]) if len(argv) > 2 else "Usage: ask-make docx|rtf|odt|xlsx FILE")
        else:
            print(getattr(chat_tools, cmd.replace("-", "_"))(" ".join(argv[1:])))
    elif cmd == "sf-closed":
        from . import sfsync
        out, won, lost, capped = sfsync.build_closed(con, argv[1:])
        print(f"{out}: {won} closed won, {lost} closed lost")
        for f in capped:
            print(f"INCOMPLETE: {f} hit the {sfsync.CLOSED_CAP}-row cap; split that window and rerun")
    elif cmd == "sf-accounts":
        from . import sfsync
        out, n, capped = sfsync.build_accounts(argv[1:])
        print(f"{out}: {n} accounts (name, type, website, mail domain only)")
        for f in capped:
            print(f"CAPPED: {f} hit the 500-row cap")
    elif cmd == "sp-read-list":
        import json as _json
        from . import doccards
        n = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 25
        print(_json.dumps(doccards.sp_candidates(con, n), indent=1))
    elif cmd == "sp-text":
        import json as _json
        from . import doccards, ingest
        b = doccards.sp_bundle(con, _json.loads(Path(argv[1]).read_text()))
        print(ingest.ingest_bundle(con, b), f"{len(b['items'])} SharePoint files now have full text")
    elif cmd == "doc-cards":
        from . import doccards
        print(doccards.generate(con, force="--force" in argv))
    elif cmd == "scan-local":
        from . import localfiles
        localfiles.scan(con)
    elif cmd == "prep-upcoming":
        import json as _json
        from . import prep
        days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 2
        print(_json.dumps([{k: v for k, v in e.items() if k != "attendee_addresses"} for e in prep.upcoming(con, days, "stale" if "--stale" in argv else "--missing" in argv)], indent=1, ensure_ascii=False))
    elif cmd == "prep-write":
        from . import prepgen
        if "--upcoming" in argv:
            sys.exit(0 if prepgen.write_upcoming(con, int(argv[argv.index("--days") + 1]) if "--days" in argv else 1) else 1)
        notes = argv[argv.index("--notes") + 1] if "--notes" in argv else ""
        if not prepgen.write(con, argv[1], notes):
            sys.exit(1)
    elif cmd == "prep-context":
        from . import prep
        print(prep.context(con, argv[1]))
    elif cmd == "followup-write":
        from . import followup
        if "--recent" in argv:
            sys.exit(0 if followup.write_recent(con, int(argv[argv.index("--hours") + 1]) if "--hours" in argv else followup.AUTO_HOURS) else 1)
        notes = argv[argv.index("--notes") + 1] if "--notes" in argv else ""
        if not followup.write(con, argv[1], notes):
            sys.exit(1)
    elif cmd == "followup-context":
        from . import followup
        print(followup.context(con, int(argv[1].replace("m-", "")))[0])
    elif cmd == "search-index":
        pass   # built below
    elif cmd == "stats":
        for t in ["sources", "pulls", "items", "people", "initiatives", "commitments", "decisions", "meetings", "runs", "approvals", "documents", "mentions"]:
            print(f"{t:12s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    else:
        print(__doc__)
    if cmd in ("sync-granola", "calendar-import", "scan-local", "mail-sync", "import-docs", "import-kb", "classify-people", "import-orgchart"):
        from . import search
        n, t = search.build(con)
        print(f"search index: {n} entries ({t}s)")
    elif cmd == "search-index":
        from . import search
        n, t = search.build(con)
        print(f"search index: {n} entries ({t}s)")
    con.commit()


if __name__ == "__main__":
    main()
