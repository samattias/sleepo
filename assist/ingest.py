"""Ingest bundles: how an agent (today: Claude Code) writes into the database.

An agent never touches the database directly. It writes one JSON file to inbox/queue/ and runs
`assist ingest`. Every bundle is idempotent; re-ingesting the same file changes nothing.

Bundle format (all sections optional):
{
  "agent": "claude-code:/brief",            # who produced it
  "prompt_version": "brief-2026-10",
  "model": "claude-fable-5-1",
  "pulls": [ {"source_id": "outlook.inbox", "window_from": "2026-10-06T10:45:00Z", "window_to": "...", "available": 30,
              "pulled": 30, "noise": 12, "complete": true, "note": "paginated to the end"} ],
  "items": [ {"source_id": "outlook.inbox", "external_id": "mail:AAMk...", "kind": "mail", "ts": "2026-10-06T08:12:00Z",
              "from_name": "Gray Selby", "subject": "...", "text": "one-line gist", "thread": null, "url": "https://...",
              "noise": false, "retention": "general", "pull": 0} ],       # pull = index into "pulls"
              # no Teams or Slack items: those are dropped; each message goes in "chat_messages", verbatim (assist/chatsync.py)
  "chat_messages": [ {"source_id": "teams|slack", "external_id": "...", "body_text": "the message, verbatim", ...} ],   # chatsync.store_record
  "commitments": [ {"kind": "owed_by_me|owed_to_me|someday", "title": "...", "context": "...", "counterparty": "Gray Selby",
                    "due": "2026-10-08", "status": "open|done|dropped", "origin": "Current",
                    "links": [{"url": "...", "label": "mail"}, {"external_id": "mail:AAMk...", "source_id": "outlook.inbox"}]} ],
  # no "decisions": retired (Sam, 26 Oct 2026); a decision to take is a commitment owed_by_me ("Decide …"). Dropped, counted.
  "meetings": [ {"external_id": "not_...", "status": "digested|analysed", "digest_md": "...",
                 "attendees": ["Sam Doe", "Noel Osborne"], "event_external_id": "<calendar event id>"} ],   # attendees/event: corrections
  "documents": [ {"id": "briefs/2026-10-06.md", "section": "Briefs", "title": "Brief · ...", "body_md": "...", "path": "briefs/2026-10-06.md"} ],
  "source_health": [ {"source_id": "slack", "health": "stale", "note": "not reachable headless"} ],
  "gaps": ["..."],
  "roadmap": {"items": [...], "url": "...", "modified": "..."},   # product roadmap snapshot (assist/roadmap.py; replaces the previous one)
  "remove_sources": ["jira"],               # retire a source that never delivered items (its pulls go too)
  "output_md": "the brief text (stored on the run)",
  # Salesforce items: source_id "salesforce", kind "opportunity", external_id "sf:<Id>", payload limited to SF_FIELDS (see .claude/skills/salesforce)
  "accounts": [ {"name": "Tailspin Ltd", "type": "Customer", "website": "https://company480.co.uk/", "email_domain": "company480.co.uk"} ],
                    # Salesforce account facts, company fields only (companies.ACCOUNT_FIELDS): Type, website, mail domain (companies.store_accounts)
  "mail_messages": [ {"graph_id": "AAMk…", "folder": "inbox|sent", "subject": "...", "from": {"name", "address"}, "to": [...], "cc": [...],
                      "bcc": [...], "received_at": "...", "sent_at": "...", "conversation_id": "...", "internet_message_id": "...",
                      "web_link": "...", "importance": "normal", "is_read": true, "body_text": "plain text, verbatim",
                      "attachments": [{"id", "name", "content_type", "size", "is_inline": false, "text": "extracted text or null"}]} ]
                    # full emails via the Microsoft 365 connector (see .claude/skills/mail-full); masked and stored by mailsync.store_record
}
"""
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .retention import RETENTION_DAYS

# Salesforce: company and deal data only (org policy). Anything not listed here is dropped before it is stored:
# owner names, MEDDICC person fields (Champion, Economic Buyer) and free text (Description, Next Steps, comments).
SF_FIELDS = {"id", "name", "account", "account_region", "target_region", "stage", "forecast_category", "probability", "sale_type",
             "record_type", "use_case", "arr_type", "currency", "acv", "tcv", "net_forecast", "net_forecast_usd", "close_date",
             "created", "contract_start", "contract_end", "age_days", "sales_channel", "lead_source", "loss_reason", "win_reason",
             "churn_reason", "auto_renewal", "is_open", "seen"}


def _sf_clean(it):
    it = dict(it, from_name=None)
    if it.get("payload") is not None:  # no payload = a field update (e.g. noise); keep what is stored
        it["payload"] = {k: v for k, v in it["payload"].items() if k in SF_FIELDS}
    return it


def _link(con, l):
    if l.get("external_id") and l.get("source_id"):
        row = con.execute("SELECT id FROM items WHERE source_id=? AND external_id=?", (l["source_id"], l["external_id"])).fetchone()
        return {"item_id": row["id"] if row else None, "url": l.get("url"), "label": l.get("label")}
    return {"item_id": None, "url": l.get("url"), "label": l.get("label")}


def ingest_bundle(con, b, origin_file=None):
    run = db.start_run(con, b.get("agent", "unknown"), b.get("prompt_version"), b.get("model"),
                       {"file": str(origin_file) if origin_file else None, "pulls": len(b.get("pulls", [])), "items": len(b.get("items", []))})
    pull_ids = []
    for p in b.get("pulls", []):
        pid = db.start_pull(con, p["source_id"], b.get("agent", "unknown"), p.get("window_from"), p.get("window_to"), p.get("note"))
        # complete only when the bundle says so: a pull that does not say it paginated to the end is retried and shown as stale
        db.finish_pull(con, pid, p.get("available"), p.get("pulled"), p.get("noise"), 1 if p.get("complete") in (True, 1) else 0)
        pull_ids.append(pid)
    counts = {"items_new": 0, "items_seen": 0, "commitments_new": 0, "meetings": 0, "documents": 0}
    for it in b.get("items", []):
        # Teams and Slack are kept as the raw messages only (Sam, 22 Oct 2026): a pull's one-line gists made a second,
        # summary-only copy of each message. chat_messages below creates the item row from the message itself.
        if it["source_id"] in ("teams", "slack"):
            counts["chat_gists_dropped"] = counts.get("chat_gists_dropped", 0) + 1
            continue
        if it["source_id"] == "salesforce":
            it = _sf_clean(it)
        pid = pull_ids[it["pull"]] if isinstance(it.get("pull"), int) and it["pull"] < len(pull_ids) else None
        _, created = db.upsert_item(con, it["source_id"], it["external_id"], it.get("kind", "mail"), it["ts"], pull_id=pid,
                                    from_name=it.get("from_name"), subject=it.get("subject"), text=it.get("text"), thread=it.get("thread"),
                                    url=it.get("url"), payload=it.get("payload"), noise=it.get("noise"), retention=it.get("retention"),
                                    from_person_id=db.resolve_person(con, it.get("from_name")))
        counts["items_new" if created else "items_seen"] += 1
    for c in b.get("commitments", []):
        cid, created = db.upsert_commitment(con, c.get("kind", "owed_by_me"), c["title"], run_id=run, context=c.get("context"),
                                            counterparty=c.get("counterparty"), due=c.get("due"), status=c.get("status"), origin=c.get("origin"),
                                            links=[_link(con, l) for l in c.get("links", [])])
        if c.get("status") in ("done", "dropped"):
            con.execute("UPDATE commitments SET closed_at=COALESCE(closed_at, ?) WHERE id=?", (db.now(), cid))
        db.tag_mentions(con, "commitment", cid, c["title"] + " " + (c.get("context") or ""))
        counts["commitments_new"] += created
    if b.get("decisions"):   # retired (Sam, 26 Oct 2026): migration m026
        counts["decisions_dropped"] = len(b["decisions"])
    for m in b.get("meetings", []):
        row = con.execute("SELECT id FROM items WHERE source_id='granola' AND external_id=?", (m["external_id"],)).fetchone()
        if row:
            con.execute("UPDATE meetings SET status=COALESCE(?, status), digest_md=COALESCE(?, digest_md) WHERE note_item_id=?",
                        (m.get("status"), m.get("digest_md"), row["id"]))
            if m.get("attendees"):   # a correction from Sam: full names or emails, recorded as confirmed (assist/meeting_people.py)
                from . import meeting_people
                mid = con.execute("SELECT id FROM meetings WHERE note_item_id=?", (row["id"],)).fetchone()
                for who in m["attendees"]:
                    if mid and not db.ME_STRICT.search(who or ""):
                        try:
                            meeting_people.decide(con, mid["id"], who=who)
                        except ValueError:
                            pass
            if m.get("event_external_id"):
                ev = con.execute("SELECT id FROM items WHERE source_id='calendar' AND external_id=?", (m["event_external_id"],)).fetchone()
                if ev:
                    con.execute("UPDATE meetings SET event_item_id=?, match_quality='sam' WHERE note_item_id=?", (ev["id"], row["id"]))
            if m.get("attendees") or m.get("event_external_id"):   # re-link this meeting's people on the next entity pass
                con.execute("UPDATE items SET pulled_at=? WHERE id=?", (db.now(), row["id"]))
            counts["meetings"] += 1
    for d in b.get("documents", []):
        db.upsert_document(con, d["id"], d.get("section", "Library"), d["title"], d["body_md"], d.get("path"), d.get("meta"))
        counts["documents"] += 1
    if b.get("mail_messages"):
        from . import mailsync
        for r in b["mail_messages"]:
            mailsync.store_record(con, r)
        counts["mail_full"] = len(b["mail_messages"])
        mailsync.purge(con, RETENTION_DAYS)
    if b.get("chat_messages"):
        from . import chatsync
        for r in b["chat_messages"]:
            chatsync.store_record(con, r)
        counts["chat_full"] = len(b["chat_messages"])
        chatsync.purge(con, RETENTION_DAYS)
    if any(k in b for k in ("initiatives", "merge_initiatives", "initiative_links", "tagged", "initiative_updates")):
        from . import initiatives
        initiatives.apply_bundle(con, b, counts)   # canonical list, folds, links with reasons, tagged records, weekly updates
    if b.get("doc_cards"):
        from . import doccards
        doccards.apply_bundle(con, b, counts)
    if b.get("roadmap"):   # the product roadmap snapshot (assist/roadmap.py): replaces the previous one
        from . import roadmap
        counts["roadmap"] = roadmap.apply(con, b["roadmap"])
    if b.get("accounts"):   # Salesforce account facts (company fields only): Type, website, mail domain
        from . import companies, entities
        entities.sync_orgs(con)   # the account records the bundle's own opportunities bring
        keep = [{k: a.get(k) for k in companies.ACCOUNT_FIELDS} for a in b["accounts"] if isinstance(a, dict)]
        counts["accounts"] = companies.store_accounts(con, keep)
    for s in b.get("source_health", []):   # a source's last pull never moves back in time (16 Nov 2026: a replayed 6 Oct bundle did)
        con.execute("UPDATE sources SET health=COALESCE(?, health), note=COALESCE(?, note), "
                    "last_pull_at=CASE WHEN ? IS NULL OR (last_pull_at IS NOT NULL AND last_pull_at > ?) THEN last_pull_at ELSE ? END WHERE id=?",
                    (s.get("health"), s.get("note"), s.get("last_pull_at"), s.get("last_pull_at"), s.get("last_pull_at"), s["source_id"]))
    for sid in b.get("remove_sources", []):  # retire a source: only allowed when nothing was ever pulled from it
        if con.execute("SELECT COUNT(*) FROM items WHERE source_id=?", (sid,)).fetchone()[0]:
            raise ValueError(f"remove_sources: {sid} still has items; mark them noise or purge them first")
        con.execute("DELETE FROM pulls WHERE source_id=?", (sid,))
        con.execute("DELETE FROM sources WHERE id=?", (sid,))
        counts["sources_removed"] = counts.get("sources_removed", 0) + 1
    from . import gaps   # each gap is stamped with when it was last reported (the Sources page shows the current ones)
    for g in b.get("gaps", []):
        gaps.note(con, g)
    for g in b.get("clear_gaps", []):
        gaps.clear(con, g)
    db.finish_run(con, run, output_md=b.get("output_md"), output_json=counts)
    con.execute("INSERT INTO docs_fts(docs_fts) VALUES ('rebuild')")
    con.commit()
    return run, counts


def loaded_before(con, path):
    """When a bundle file of this name was already loaded and has not changed since: the start of that run, else None.
    16 Nov 2026: bundles from October came back into inbox/queue (pull-retry-2026-10-12.json was loaded six times, the last
    two today) and a plain `ingest` loaded them again; their old source_health set Slack to "partial" (Capped on Sources)
    and SharePoint's last pull back to 6 Oct."""
    name = Path(path).name
    try:
        changed = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None
    for r in con.execute("SELECT started_at, json_extract(input_summary, '$.file') AS f FROM runs "
                         "WHERE input_summary LIKE ? ORDER BY id DESC", (f"%{name}%",)):
        if r["f"] and Path(r["f"]).name == name and (r["started_at"] or "") > changed:
            return r["started_at"]
    return None


def ingest_file(con, path, index=True):
    """Load one bundle file. It leaves the queue as soon as it is committed, before anything else can fail, so a retry
    (the CLI retries on a locked database) never loads it twice. index=False leaves reindex() to the caller, which runs
    it once after a batch of bundles instead of once per bundle (a full search rebuild takes seconds). A file already
    loaded and unchanged since is not loaded again (loaded_before); it leaves the queue the same way."""
    b = json.loads(Path(path).read_text())
    before = loaded_before(con, path)
    if before:
        run, counts = None, {"skipped": f"already loaded {before[:16].replace('T', ' ')}, unchanged since"}
    else:
        run, counts = ingest_bundle(con, b, origin_file=path)
    if b.get("mail_messages") or b.get("chat_messages"):  # full mail and chat stay only in the database (outside OneDrive); no copy of the bundle is kept
        Path(path).unlink(missing_ok=True)
        msg = f"{Path(path).name}: run {run} · {counts} · bundle deleted"
    else:
        done = db.ASSIST / "inbox" / "queue" / "done"
        done.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(path), str(done / Path(path).name))
        except Exception:
            pass
        msg = f"{Path(path).name}: run {run} · {counts}"
    if index and run is not None:
        reindex(con)
    return msg


def reindex(con):
    """After loading: rebuild the search index (it copies text, so purged mail and chat leave it too), then tie what
    arrived to people, organisations and initiatives (incremental)."""
    from . import search
    search.build(con)
    try:
        from . import entities
        entities.link(con, log=lambda *_: None)
    except Exception as e:  # linking must never block an ingest
        print(f"entity linking skipped: {e}")
