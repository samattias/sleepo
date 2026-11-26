"""One view of every agent: what exists, what is running right now, and what ran recently.

Sources of truth, combined here:
- the full refresh (api.STATE: phases, progress) - passed in by the API
- meeting-brief jobs (api.PREP_JOBS) - passed in by the API
- reply-drafting jobs (job files in Application Support/Assist/jobs/replies)
- initiative jobs (initiatives.JOBS)
- the runs table (every agent run records start, finish and outcome)
- live `claude -p` processes on this Mac, classified by the purpose llm.run recorded for them, else by the start of
  their prompt (the prompt itself is never returned)
"""
import json
import re
import subprocess
import time
from datetime import datetime, timezone

# key, name, what it does, how it is triggered, the page it feeds, runs.agent patterns, prompt-start patterns of its claude -p
REGISTRY = [
    ("refresh", "Full refresh", "Pulls every source, then links, checks open items, tags initiatives, ranks actions and writes meeting briefs.",
     "Every morning, and the Refresh button", "/sources", r"^$", r"Morning (full )?refresh|^Refresh"),
    ("mail", "Mail", "Stores new Inbox and Sent mail (full text for 30 days, envelopes for everything).", "Refresh", "/mail",
     r"mail-full|mail-connector|mail-sync|mail-envelopes", r"/mail-full"),
    ("chat", "Teams and Slack", "Pulls Teams and Slack messages, full text for 30 days.", "Refresh", "/messages", r"chat-full|slack|teams", r"Teams|Slack"),
    ("salesforce", "Salesforce pipeline", "Pulls open opportunities (company and deal data only).", "Refresh", "/pipeline", r"salesforce", r"/salesforce"),
    ("linking", "Entity linking", "Links every item to the people, organisations and initiatives it mentions.", "Refresh, after each pull", "/explore",
     r"link|entities", r"^$"),
    ("graph", "Graph memory", "Keeps bets, topics and the next meetings' briefs current during the day: reads what new mail, messages and notes touched each one since it was written, and rewrites only what changed.",
     "After a sync, at most hourly", "/initiatives", r"^graph-", r"^You keep SleePO's records current"),   # before topics, initiatives and prep, whose patterns match graph-brief and graph-status
    ("loops", "Open items check", "Checks whether open items with colleagues are still open, from the evidence.", "Refresh", "/loops",
     r"loops|extract", r"You check whether open items|register of open items"),
    ("topics", "Top of mind", "Names the topics you discussed in the last days, from your calls, mail, chats and questions, filed under your initiatives.",
     "Refresh, and the Initiatives page", "/initiatives", r"topics", r"^You are SleePO, chief of staff to .*Below is everything .* discussed"),   # before initiatives, whose patterns match it too
    ("initiatives", "Initiative updates", "Tags items to initiatives and drafts each initiative's weekly update.", "Refresh, and initiative pages", "/initiatives",
     r"initiatives", r"initiative"),
    ("todo", "Task suggestions", "Suggests tasks and steps, with ready-made actions, for you to accept or dismiss.",
     "Refresh, and Suggest tasks", "/tasks", r"^todo$|assist:todo|assist:tasks-suggest|tasks-suggest", r"chief of staff\. (From the context|\S+ works from a task list)"),
    ("taskplan", "Task planning", "Turns an email or a meeting into a task with steps and first actions, which you edit and save.", "On demand, from the Inbox and meetings",
     "/tasks", r"task-propose|task-preplan", r"wants to turn the (email|meeting)"),
    ("prep", "Meeting briefs", "Writes a pre-read for each upcoming meeting.", "Refresh, and Prepare brief", "/prep", r"/prep|prep", r"/prep|meeting brief|Prep "),
    ("followup", "Meeting follow-ups", "Suggests the actions to take after each recorded meeting, from what was said.", "Refresh, and opening a past meeting",
     "/meetings", r"followup", r"You suggest the follow-up actions"),
    ("reviews", "File reviews", "Reviews a file someone shared in Teams against what SleePO knows, proposes exact edits, makes the updated copy and briefs the reply.",
     "On demand, from Messages", "/messages", r"file-review|review-plan", r"^You (review a file for |plan the checks for a review)"),   # before briefings, whose patterns match "brief"
    ("briefings", "Email briefings", "Briefs you on the situation around an email thread: its history, the people, documents to read, what is open; continues in the chat.",
     "On demand, from the Inbox", "/inbox", r"briefing", r"^You brief "),   # before "brief", whose patterns match it too
    ("people", "Person summaries", "Writes where things stand with one person at the top of their page: what is live, what was last discussed, what to raise next time.",
     "Opening a person's page when the last one is out of date", "/people", r"person-summary", r"^You write where things stand"),
    ("brief", "Daily brief", "Writes a daily brief (the three things that matter, decisions and people waiting) when asked; not part of the refresh.", "On demand (/brief)", "/",
     r"brief", r"brief"),
    ("replies", "Reply drafting", "Drafts an email reply in your voice, with no tools.", "On demand", "/inbox", r"repl", r"You are drafting an email"),
    ("drafts", "New emails", "Writes new emails (not replies) in your voice in the Inbox's Drafts, and recommends the new emails you should send, as task suggestions.",
     "Refresh, and Drafts › Suggest emails or Write", "/inbox", r"new.mail|drafts-suggest|mail-draft", r"You are drafting a new email|recommend the NEW emails"),
    ("deliverables", "Document planning", "Plans a deck, document or workbook that answers an email, for Claude Cowork to build from SleePO's context.",
     "On demand, from the Inbox", "/inbox", r"deliverable", r"You plan a document for "),
    ("docs", "Document reading", "Reads documents and writes their summary cards.", "Refresh and on demand", "/documents", r"doc", r"document"),
]


DOING = {"refresh": "Refreshing every source", "mail": "Storing new mail", "chat": "Pulling Teams and Slack",
         "salesforce": "Pulling the open pipeline", "linking": "Linking items to people and initiatives", "graph": "Bringing records up to date", "loops": "Checking open items",
         "initiatives": "Updating initiatives", "topics": "Finding what is top of mind", "todo": "Suggesting tasks", "taskplan": "Planning a task", "prep": "Writing meeting briefs", "followup": "Suggesting meeting follow-ups",
         "brief": "Writing the daily brief", "replies": "Drafting a reply", "drafts": "Writing a new email", "deliverables": "Planning a document", "briefings": "Writing an email briefing", "reviews": "Reviewing a file","docs": "Reading documents"}


PHASE_AGENT = {"Mail (Claude)": "mail", "Salesforce": "salesforce", "Calendar, Teams, Slack": "chat", "Linking": "linking",
               "Open items": "loops", "Initiatives": "initiatives", "Top of mind": "topics", "Tasks": "todo", "Meeting prep": "prep", "Meeting follow-ups": "followup",
               "Documents": "docs"}


def _durations(recent):
    """Recent run lengths per agent, newest first: timed runs (start to finish), refresh phases, manual runs, refresh totals.
    Runs recorded only when their results were loaded (start == finish) are not timings and are skipped."""
    from . import db
    out = {}
    for r in recent:
        st, fi = _parse(r["started_at"]), _parse(r["finished_at"])
        if st and fi and (fi - st).total_seconds() >= 5:
            out.setdefault(_key_for_run(r["agent"]), []).append((fi.isoformat(), (fi - st).total_seconds()))
    try:
        h = json.loads((db.db_path().parent / "refresh_history.json").read_text())
    except (OSError, ValueError):
        h = {}
    for run in h.get("full", []):
        out.setdefault("refresh", []).append((run.get("finished", ""), float(run.get("total") or 0)))
        for ph, secs in (run.get("phases") or {}).items():
            if ph in PHASE_AGENT and secs is not None:
                out.setdefault(PHASE_AGENT[ph], []).append((run.get("finished", ""), float(secs)))
    try:
        jd = db.db_path().parent / "jobs" / "agents"
        for f in jd.glob("*.json"):
            j = json.loads(f.read_text())
            if j.get("finished") and j.get("ok") and j.get("secs") is not None:
                out.setdefault(j.get("key"), []).append((j["finished"], float(j["secs"])))
    except (OSError, ValueError):
        pass
    return {k: [secs for _, secs in sorted(v, reverse=True)[:10]] for k, v in out.items()}


def _refresh_history():
    from . import db
    try:
        h = json.loads((db.db_path().parent / "refresh_history.json").read_text())
    except (OSError, ValueError):
        return None
    runs = [r for v in h.values() for r in v if r.get("finished")]
    return max(runs, key=lambda r: r["finished"]) if runs else None


def _now():
    return datetime.now(timezone.utc)


def _parse(ts):
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        d = datetime.fromisoformat(s if "T" in s else s.replace(" ", "T"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _key_for_run(agent):
    a = (agent or "").lower()
    for key, _name, _what, _trig, _page, runpat, _procpat in REGISTRY:
        if key != "refresh" and re.search(runpat, a):
            return key
    return "other"


def _processes():
    """Live `claude -p` processes: pid, elapsed seconds and the agent they belong to (by llm.run's purpose record, else by
    prompt start; prompt not returned)."""
    from . import llm
    try:
        out = subprocess.run(["ps", "-axo", "pid=,etime=,args="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    procs = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)$", line)
        if not m or " -p " not in m.group(3) or "claude" not in m.group(3).split(" -p ")[0]:
            continue
        prompt = m.group(3).split(" -p ", 1)[1][:200]
        key = "other"
        purpose = llm.running_purpose(m.group(1))   # llm.run records each call's purpose; the prompt is the fallback
        if purpose:
            key = _key_for_run(purpose)
        else:
            for k, _name, _what, _trig, _page, _runpat, procpat in REGISTRY:
                if procpat != r"^$" and re.search(procpat, prompt, re.I):
                    key = k
                    break
        parts = [int(x) for x in re.split(r"[-:]", m.group(2))]
        secs = 0
        if "-" in m.group(2):
            secs = parts[0] * 86400 + parts[1] * 3600 + parts[2] * 60 + parts[3]
        else:
            for p in parts:
                secs = secs * 60 + p
        procs.append({"pid": int(m.group(1)), "elapsed": secs, "key": key})
    return procs


def _reply_jobs():
    from . import replies
    out = []
    d = getattr(replies, "JOB_DIR", None)
    if not d or not d.exists():
        return out
    cutoff = time.time() - 900
    for f in d.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                continue
            j = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if j.get("running"):
            out.append({"key": "replies", "what": "Drafting a reply", "started": j.get("started")})
    return out


def snapshot(con, state=None, prep_jobs=None, progress=None):
    now = _now()
    running = []
    # 1. the full refresh
    if state and state.get("running"):
        cur = next((p for p in state.get("phases") or [] if p.get("status") == "running"), None)
        frac, left = progress or (None, None)
        running.append({"key": "refresh", "what": f"{'Full refresh' if state.get('mode') == 'full' else 'Sync'}: {cur['name'] if cur else 'starting'}",
                        "started": state.get("started"), "progress": frac, "eta_secs": left,
                        "phases": [{"name": p["name"], "status": p["status"]} for p in state.get("phases") or []]})
    # 2. meeting briefs
    for eid, j in (prep_jobs or {}).items():
        if j.get("running"):
            running.append({"key": "prep", "what": "Writing a meeting brief" + (f" ({j['subject']})" if j.get("subject") else ""), "started": j.get("started")})
    # 3. replies, initiatives, actions jobs
    running += _reply_jobs()
    for modname, key in (("initiatives", "initiatives"),):
        try:
            mod = __import__(f"assist.{modname}", fromlist=["JOBS"])
            for j in getattr(mod, "JOBS", {}).values():
                if j.get("running"):
                    running.append({"key": key, "what": (j.get("kind") or modname).replace("_", " ").capitalize()
                                    + (f" · {j['done']}/{j['total']}" if j.get("total") else ""), "started": j.get("started")})
        except Exception:
            pass
    # 3b. agents started by hand from the Agents page (assist/agent_runner.py)
    try:
        from . import agent_runner
        for k in agent_runner.STEPS:
            s = agent_runner.status(k)
            if s and s.get("running") and not any(x["key"] == k for x in running):
                running.append({"key": k, "what": DOING.get(k, k) + " (started by you)", "started": s.get("started"), "manual": True})
    except Exception:
        pass
    # 4. unfinished runs in the last 45 minutes (detached processes such as Actions)
    for r in con.execute("SELECT id, agent, started_at FROM runs WHERE finished_at IS NULL AND started_at >= ? ORDER BY id DESC",
                         (datetime.fromtimestamp(now.timestamp() - 2700, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),)):
        k = _key_for_run(r["agent"])
        if not any(x["key"] == k for x in running):
            running.append({"key": k, "what": DOING.get(k, r["agent"]), "started": r["started_at"]})
    # 5. live claude processes not already explained
    procs = _processes()
    for p in procs:
        if not any(x["key"] == p["key"] for x in running) and not (state and state.get("running") and p["key"] in ("other", "refresh")):
            running.append({"key": p["key"], "what": DOING.get(p["key"], "Claude is working on something not yet listed here"),
                            "started": datetime.fromtimestamp(now.timestamp() - p["elapsed"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    for x in running:
        st = _parse(x.get("started"))
        x["elapsed"] = round((now - st).total_seconds()) if st else None

    # registry with last run and 24h counts
    recent = [dict(r) for r in con.execute("SELECT id, agent, started_at, finished_at, output_json FROM runs ORDER BY id DESC LIMIT 400")]
    day_ago = now.timestamp() - 86400
    agents = []
    busy = {x["key"] for x in running}
    for key, name, what, trigger, page, _rp, _pp in REGISTRY:
        mine = [r for r in recent if _key_for_run(r["agent"]) == key] if key != "refresh" else []
        last = mine[0] if mine else None
        err = None
        if last and last.get("output_json"):
            try:
                o = json.loads(last["output_json"])
                err = o.get("error") if isinstance(o, dict) else None
            except ValueError:
                pass
        if key == "refresh":
            last_ts, ok = (state or {}).get("finished"), (state or {}).get("ok")
            if not last_ts:   # the server keeps refresh state in memory; after a restart use the refresh history
                h = _refresh_history()
                if h:
                    last_ts, ok = h.get("finished"), h.get("ok")
        else:
            last_ts = last and (last["finished_at"] or last["started_at"])
            stale = last and not last["finished_at"] and (now - (_parse(last["started_at"]) or now)).total_seconds() > 2700
            ok = None if not last or key in busy or (not last["finished_at"] and not stale) else (False if err or stale else True)
            if stale and not err:
                err = "did not finish"
        try:
            from . import agent_runner
            runnable = key in agent_runner.STEPS or key == "refresh"
            not_runnable = agent_runner.NOT_RUNNABLE.get(key) if key != "refresh" else None
            man = agent_runner.status(key) if key in agent_runner.STEPS else None
        except Exception:
            runnable, not_runnable, man = False, None, None
        has_log = key == "refresh" or bool(man)
        agents.append({"key": key, "name": name, "what": what, "trigger": trigger, "page": page, "running": key in busy,
                       "last": last_ts, "ok": ok, "error": err, "runnable": runnable, "not_runnable": not_runnable, "has_log": has_log,
                       "manual": {"started": man.get("started"), "finished": man.get("finished"), "ok": man.get("ok"), "running": man.get("running")} if man else None,
                       "runs_24h": sum(1 for r in mine if (_parse(r["started_at"]) or now).timestamp() >= day_ago)})
    durs = _durations(recent)
    for a in agents:
        d = durs.get(a["key"]) or []
        a["avg_secs"] = round(sum(d) / len(d)) if d else None
        a["avg_n"] = len(d)
    log = []
    for r in recent[:60]:
        st, fi = _parse(r["started_at"]), _parse(r["finished_at"])
        err = None
        try:
            o = json.loads(r["output_json"] or "{}")
            err = o.get("error") if isinstance(o, dict) else None
        except ValueError:
            pass
        log.append({"id": r["id"], "agent": r["agent"], "key": _key_for_run(r["agent"]), "started": r["started_at"], "finished": r["finished_at"],
                    "secs": round((fi - st).total_seconds()) if st and fi else None, "ok": None if not fi else not err, "error": err})
    pages = {a["page"] for a in agents if a["running"]}
    if "/prep" in pages:
        pages.add("/meetings")          # Briefings and Meetings are the same page
    pages = sorted(pages)
    return {"running": running, "agents": agents, "log": log, "busy_pages": pages, "now": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
