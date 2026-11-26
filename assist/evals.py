"""Offline evaluation: does SleePO draft what Sam actually sends?

eval_replies(): for emails Sam already answered, draft a reply with the normal reply pipeline using only what existed
before that email (replies.CUTOFF, his real reply excluded), then compare with his real reply:
- word_overlap: share of words in common (0-1), length_ratio: draft words / real words
- with judge=True, a second tool-free model call scores 1-5: same stance/decision, covers the asks, tone like Sam
Results go to the evals table so prompt changes can be compared run against run. Costs model calls: keep n small.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

from . import db, llm, replies
from . import profile
from . import org
from .promptkit import USER   # the user in prompt text (assist/profile.py)

AUTOMATED = re.compile(r"no-?reply|notification|calendar|microsoft|teams@|sharepoint" + org.alt("noise_senders"), re.I)
SENSITIVE = re.compile(r"departure|termination|rupture|resign|dismiss|disciplin|investigation|grievance|salary|compensation|"
                       r"\bHR\b|legal|lawyer|contract of employment|performance review|sick|medical|final day|last day|leaving|notice period", re.I)
JUDGE = f"""Compare a DRAFT email reply with the REAL reply {USER.name} sent to the same email. Judge only these, 1 (poor) to 5 (same):
- stance: does the draft take the same position / decision / answer as the real reply?
- asks: does the draft respond to what the email asked, as the real reply does?
- tone: does it sound like {USER.first} (short, direct, purpose first)?
Return ONLY JSON: {{"stance": n, "asks": n, "tone": n, "note": "one short line on the biggest difference"}}"""


def _words(t):
    return re.findall(r"\w+", (t or "").lower())


def overlap(a, b):
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    bag = {}
    for w in wa:
        bag[w] = bag.get(w, 0) + 1
    common = 0
    for w in wb:
        if bag.get(w, 0) > 0:
            common += 1
            bag[w] -= 1
    return round(2 * common / (len(wa) + len(wb)), 3)


def cases(con, n):
    """Recent inbox emails from a person (not automated) that Sam answered in the same thread, with his first reply."""
    out, seen = [], set()
    for m in con.execute("SELECT m.*, i.retention FROM mail_messages m JOIN items i ON i.id=m.item_id WHERE m.folder='inbox' "
                         "AND m.conversation_id IS NOT NULL ORDER BY m.received_at DESC LIMIT 600"):
        if AUTOMATED.search((m["from_address"] or "") + " " + (m["from_name"] or "")) or db.ME_ADDRESS.search(m["from_address"] or ""):
            continue
        # one case per thread, and never HR, legal or personnel threads as test material
        if m["conversation_id"] in seen or m["retention"] == "hr_legal" or SENSITIVE.search(m["subject"] or ""):
            continue
        if re.match(r"(?i)^(accepted|declined|tentative|canceled|cancelled)\b", m["subject"] or ""):
            continue
        seen.add(m["conversation_id"])
        r = con.execute("SELECT * FROM mail_messages WHERE folder='sentitems' AND conversation_id=? AND sent_at > ? ORDER BY sent_at LIMIT 1",
                        (m["conversation_id"], m["received_at"])).fetchone()
        if not r:
            continue
        real = replies._own_text(r["body_text"])
        if len(_words(real)) < 8:
            continue
        out.append((m, r, real))
        if len(out) >= n:
            break
    return out


def eval_replies(con, n=5, judge=True, log=print):
    run = "replies-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    results = []
    for m, r, real in cases(con, n):
        replies.CUTOFF, replies.EXCLUDE_ITEMS = m["received_at"], {r["item_id"]}
        try:
            pr, _ = replies.prompt(con, m["item_id"], "", "reply")
            ok, out, err = replies._run(pr, db.ASSIST)
            draft = ""
            if ok:
                try:
                    draft = (llm.parse_json(out, "object") or {}).get("body", "")
                except ValueError:
                    draft = out
        finally:
            replies.CUTOFF, replies.EXCLUDE_ITEMS = None, set()
        met = {"subject": (m["subject"] or "")[:80], "from": m["from_name"], "ok": bool(ok and draft), "error": None if ok else err[-200:],
               "word_overlap": overlap(draft, real), "length_ratio": round(len(_words(draft)) / max(1, len(_words(real))), 2),
               "fills": draft.count("[FILL"), "prompt_version": replies.PROMPT_VERSION, "model": llm.model_for(con, "replies")}
        if judge and draft:
            try:
                j = llm.parse_json(llm.run(JUDGE + "\n\nREAL:\n" + real[:3000] + "\n\nDRAFT:\n" + draft[:3000], db.ASSIST, timeout=180, purpose="eval-judge"), "object")
                met.update({k: j.get(k) for k in ("stance", "asks", "tone", "note")})
            except Exception as e:
                met["judge_error"] = str(e)[:200]
        con.execute("INSERT INTO evals (run, kind, target, metrics, created_at) VALUES (?,?,?,?,?)",
                    (run, "reply", str(m["item_id"]), json.dumps(met), db.now()))
        con.commit()
        results.append(met)
        log(f"- {met['subject'][:50]}: overlap {met['word_overlap']}, length x{met['length_ratio']}"
            + (f", stance {met.get('stance')}, asks {met.get('asks')}, tone {met.get('tone')}" if 'stance' in met else ""))
    done = [x for x in results if x["ok"]]
    avg = lambda k: round(sum(x[k] for x in done if isinstance(x.get(k), (int, float))) / max(1, sum(1 for x in done if isinstance(x.get(k), (int, float)))), 2)
    summary = {"run": run, "cases": len(results), "drafted": len(done), "word_overlap": avg("word_overlap"), "length_ratio": avg("length_ratio"),
               "stance": avg("stance"), "asks": avg("asks"), "tone": avg("tone")}
    log(json.dumps(summary))
    return summary


# ================================================================ extraction: open items found in meetings, mail and chat
# Golden set: evals/golden/extract.json, one case per source item with the commitments (decisions retired 26 Oct 2026) a careful reader
# would record. It holds item ids and labels only, never the source text (that is rebuilt from the database, so mail and
# chat cases fall away after the 30-day purge; meeting cases stay). Cases start "reviewed": false, pre-filled from the
# register; only cases Sam has reviewed count, unless include_unreviewed (a consistency check, not accuracy).
GOLDEN = db.ASSIST / "evals" / "golden" / "extract.json"
COMMIT_KINDS = {"owed_by_me", "owed_to_me"}


def _load_golden():
    return json.loads(GOLDEN.read_text()) if GOLDEN.exists() else []


def seed_extract(con, n=30, log=print):
    """Add up to n new unreviewed cases: recent meetings (and Sam's sent mail), pre-filled with what the register holds for
    each. Sam then corrects them: remove what is not a real commitment, add what was missed, fix owners."""
    cases = _load_golden()
    have = {c["item_id"] for c in cases}
    added = 0
    rows = con.execute("SELECT m.note_item_id AS item_id, m.title FROM meetings m WHERE m.note_item_id IS NOT NULL AND m.status != 'personal' "
                       "ORDER BY m.starts_at DESC LIMIT 200").fetchall()
    rows += con.execute("SELECT s.item_id, s.subject AS title FROM mail_messages s WHERE s.folder='sentitems' ORDER BY s.sent_at DESC LIMIT 60").fetchall()
    for r in rows:
        if added >= n:
            break
        if r["item_id"] in have or profile.PERSONAL.search(r["title"] or "") or SENSITIVE.search(r["title"] or ""):
            continue
        from . import loops
        if not loops.material(con, r["item_id"]):
            continue
        exp = [{"kind": c["kind"], "title": c["title"], "counterparty": c["counterparty"]} for c in con.execute(
            "SELECT c.kind, c.title, c.counterparty FROM commitments c JOIN fact_sources f ON f.fact_type='commitment' AND f.fact_id=c.id WHERE f.item_id=?",
            (r["item_id"],))]
        cases.append({"item_id": r["item_id"], "title": (r["title"] or "")[:120], "reviewed": False, "expected": exp, "note": ""})
        have.add(r["item_id"])
        added += 1
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(cases, ensure_ascii=False, indent=1))
    log(f"golden set: {added} cases added, {len(cases)} in total, {sum(1 for c in cases if c.get('reviewed'))} reviewed · {GOLDEN}")
    return added


def _same(e, p):
    """Does predicted entry p match expected entry e? Same family (commitment vs decision) and similar wording."""
    if (e["kind"] == "decision") != (p["kind"] == "decision"):
        return False
    o = overlap(e["title"], p["title"])
    same_party = bool(e.get("counterparty") and p.get("counterparty") and e["counterparty"].split()[0].lower() == p["counterparty"].split()[0].lower())
    return o >= 0.5 or (same_party and o >= 0.3)


def score_case(expected, predicted):
    """Greedy one-to-one matching. Returns tp, fp, fn and how many matched commitments have the right direction."""
    left, tp, owner_ok = list(predicted), 0, 0
    for e in expected:
        best = max(((overlap(e["title"], p["title"]), i) for i, p in enumerate(left) if _same(e, p)), default=None)
        if best:
            p = left.pop(best[1])
            tp += 1
            owner_ok += 1 if e["kind"] == p["kind"] else 0
    return {"tp": tp, "fp": len(left), "fn": len(expected) - tp, "owner_ok": owner_ok}


def eval_extract(con, include_unreviewed=False, batch=6, log=print, run_model=None):
    """Run the production extraction prompt over golden cases (no EXISTING list) and score precision / recall / direction."""
    from . import loops, feedback
    cases = [c for c in _load_golden() if c.get("reviewed") or include_unreviewed]
    if not cases:
        log(f"no {'' if include_unreviewed else 'reviewed '}cases in {GOLDEN}: run eval-seed-extract, then review the cases")
        return None
    usable = [(c, loops.material(con, c["item_id"])) for c in cases]
    gone = sum(1 for _, m in usable if not m)
    usable = [(c, m) for c, m in usable if m]
    run = "extract-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    tot = {"tp": 0, "fp": 0, "fn": 0, "owner_ok": 0}
    for i in range(0, len(usable), batch):
        part = usable[i:i + batch]
        pr = loops.extract_prompt(con, [m for _, m in part], [])
        out = (run_model or (lambda t: llm.run(t, db.ASSIST, timeout=420, purpose="eval-extract")))(pr)
        try:
            data = llm.parse_json(out, "object")
        except ValueError:
            data = {}
        pred = {}
        for c in data.get("commitments") or []:
            if isinstance(c, dict) and c.get("kind") in COMMIT_KINDS and c.get("title"):
                pred.setdefault(str(c.get("ref", "")).strip(), []).append({"kind": c["kind"], "title": c["title"], "counterparty": c.get("counterparty")})
        for c, _ in part:
            p = pred.get(f"S{c['item_id']}", [])
            s = score_case([e for e in c["expected"] if e["kind"] != "decision"], p)   # decisions retired 26 Oct 2026
            for k in tot:
                tot[k] += s[k]
            con.execute("INSERT INTO evals (run, kind, target, metrics, created_at) VALUES (?,?,?,?,?)",
                        (run, "extract", str(c["item_id"]), json.dumps({**s, "reviewed": bool(c.get("reviewed")), "predicted": p,
                                                                        "prompt_version": loops.EXTRACT_VERSION, "model": feedback.last_model(con, "eval-extract")}), db.now()))
        con.commit()
    prec = round(tot["tp"] / max(1, tot["tp"] + tot["fp"]), 3)
    rec = round(tot["tp"] / max(1, tot["tp"] + tot["fn"]), 3)
    summary = {"run": run, "cases": len(usable), "cases_gone_after_purge": gone, "reviewed_only": not include_unreviewed, **tot,
               "precision": prec, "recall": rec, "f1": round(2 * prec * rec / max(1e-9, prec + rec), 3),
               "direction_accuracy": round(tot["owner_ok"] / max(1, tot["tp"]), 3)}
    log(json.dumps(summary))
    return summary


# ================================================================ online: what Sam's own actions say, no labelling needed
def online(con, days=30, log=print):
    from . import feedback
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"days": days}
    r = con.execute("SELECT SUM(l.status='dropped' AND l.closed_by='sam') AS dropped, SUM(l.status='done') AS done, SUM(l.status='open') AS open, COUNT(*) AS n "
                    "FROM loops l JOIN commitments c ON l.fact_type='commitment' AND c.id=l.fact_id WHERE c.origin='Extracted' AND l.created_at >= ?", (since,)).fetchone()
    out["extracted_items"] = {k: r[k] or 0 for k in r.keys()}
    out["extracted_items"]["dropped_by_sam_rate"] = round((r["dropped"] or 0) / max(1, (r["dropped"] or 0) + (r["done"] or 0)), 3)
    r = con.execute("SELECT SUM(status='done') AS done, SUM(status='dismissed') AS dismissed, COUNT(*) AS n FROM todo WHERE created_at >= ?", (since,)).fetchone()
    out["actions"] = {"proposed": r["n"] or 0, "done": r["done"] or 0, "dismissed": r["dismissed"] or 0,
                      "acceptance": round((r["done"] or 0) / max(1, (r["done"] or 0) + (r["dismissed"] or 0)), 3)}
    r = con.execute("SELECT SUM(rating=1) AS up, SUM(rating=-1) AS down, SUM(copied) AS copied, AVG(CASE WHEN copied=1 THEN edit_ratio END) AS edit "
                    "FROM feedback WHERE created_at >= ?", (since,)).fetchone()
    out["feedback"] = {"thumbs_up": r["up"] or 0, "thumbs_down": r["down"] or 0, "copied": r["copied"] or 0, "avg_edit_ratio_when_copied": round(r["edit"] or 0, 3)}
    pairs = feedback.reply_pairs(con, days=days)
    out["reply_drafts_vs_sent"] = {"pairs": len(pairs), "avg_word_overlap": round(sum(overlap(p["draft"], p["sent"]) for p in pairs) / max(1, len(pairs)), 3),
                                   "avg_length_ratio": round(sum(len(_words(p["draft"])) / max(1, len(_words(p["sent"]))) for p in pairs) / max(1, len(pairs)), 2)}
    r = con.execute("SELECT COUNT(*) AS n, SUM(json_extract(checks, '$.links')) AS links, SUM(json_array_length(json_extract(checks, '$.unverified_links'))) AS bad, "
                    "SUM(json_array_length(json_extract(checks, '$.dropped_actions'))) AS dropped FROM drafts WHERE kind='prep' AND created_at >= ?", (since,)).fetchone()
    out["prep_grounding"] = {"briefs": r["n"] or 0, "links": r["links"] or 0, "links_not_in_evidence": r["bad"] or 0, "actions_dropped": r["dropped"] or 0}
    con.execute("INSERT INTO evals (run, kind, target, metrics, created_at) VALUES (?,?,?,?,?)",
                ("online-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"), "online", None, json.dumps(out), db.now()))
    con.commit()
    log(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------------------------------------------ needs a reply
def eval_needs_reply(con, days=40, log=print, record=True):
    """Does "needs a reply" (replies.asked) match the mail Sam actually answers?

    Cases: mail from people he works with, not automated, that was the one to answer (nobody else wrote in the thread
    before Sam did). Truth: Sam wrote in the thread afterwards (replies.sam_wrote, across Apple Mail and Microsoft 365
    thread ids). Mail under two days old that he has not answered yet is left out. Sam answering is an imperfect label
    (he also answers in meetings and chat), so precision is a floor. Baselines: the rule before 13 Oct 2026 for the
    register (Sam in To) and for Actions (any unanswered mail).

    sam_calls scores the same rule against Sam's own calls on mail in the window (loops.mark_reply in the Inbox, and his
    closes in Open items), the cleanest labels there are: removed (dropped by Sam: no reply needed) and the rule had
    flagged it is a false positive; added (added_by_sam, also set when he reopens a mail item) and the rule left it out
    is a miss. Mail he marked done is left out (he dealt with it, which says nothing about being asked); when he both
    added and removed an email, the later call counts."""
    since =(datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    threads, sent_to, known = replies.sent_threads(con), replies.written_to(con), {}
    rows = con.execute("SELECT m.*, i.noise FROM mail_messages m JOIN items i ON i.id=m.item_id WHERE m.folder='inbox' AND m.received_at >= ? "
                       "ORDER BY m.received_at", (since,)).fetchall()
    by_thread = {}
    for r in rows:
        by_thread.setdefault(replies.thread_key(r["subject"]) or f"c:{r['conversation_id']}", []).append(r)
    cases = []
    for r in rows:
        addr = (r["from_address"] or "").lower()
        if replies.SAM.search(addr) or r["noise"] or replies.AUTOMATED.search(f"{addr} {r['from_name'] or ''}") or replies.NOTIFICATION.search(r["subject"] or ""):
            continue
        if addr not in known:
            known[addr] = replies.known_sender(con, addr, r["from_name"], sent_to)
        if not known[addr]:
            continue
        reply = replies.sam_wrote(threads, r)
        people = replies._addresses(r)
        nxt = next((x for x in by_thread[replies.thread_key(r["subject"]) or f"c:{r['conversation_id']}"]
                    if x["received_at"] > r["received_at"] and (x["conversation_id"] == r["conversation_id"] or replies._addresses(x) & people)), None)
        if nxt and (not reply or nxt["received_at"] < reply["at"]):
            continue   # someone else wrote next: this was not the message to answer
        if not reply and r["received_at"] > fresh:
            continue   # may still be answered
        needs, why = replies.asked(r, engaged=replies.sam_wrote(threads, r, after=False) is not None)
        to_me = any(replies.SAM.search(x.get("address") or "") for x in json.loads(r["to_json"] or "[]"))
        cases.append({"answered": bool(reply), "rule": needs, "why": why, "to_me": to_me, "any": True})

    def score(key):
        tp = sum(1 for c in cases if c[key] and c["answered"])
        fp = sum(1 for c in cases if c[key] and not c["answered"])
        fn = sum(1 for c in cases if not c[key] and c["answered"])
        return {"flagged": tp + fp, "answered_among_flagged": tp, "precision": round(tp / max(1, tp + fp), 3), "recall": round(tp / max(1, tp + fn), 3)}
    out = {"days": days, "cases": len(cases), "answered": sum(c["answered"] for c in cases), "rule": score("rule"),
           "before_register_sam_in_to": score("to_me"), "before_actions_any_unanswered": score("any"), "why": {}}
    for c in cases:   # per reason: how often Sam answered mail the rule kept or left out for that reason
        w = out["why"].setdefault(c["why"], {"n": 0, "answered": 0, "flagged": c["rule"]})
        w["n"] += 1
        w["answered"] += c["answered"]
    from . import loops
    calls = out["sam_calls"] = {"removed": {"n": 0, "in_inbox": 0, "in_open_items": 0, "rule_flagged": 0, "false_positives": {}},
                                "added": {"n": 0, "rule_left_out": 0, "misses": {}}}
    for r in con.execute("SELECT m.*, l.status AS l_status, l.closed_by AS l_closed_by, l.closed_at AS l_closed_at, l.close_reason AS l_reason, "
                         "l.added_by_sam AS l_added FROM loops l JOIN mail_messages m ON m.item_id=l.fact_id AND m.folder='inbox' "
                         "WHERE l.fact_type='mail' AND m.received_at >= ? AND ((l.status='dropped' AND l.closed_by='sam') OR l.added_by_sam IS NOT NULL) "
                         "ORDER BY m.received_at", (since,)).fetchall():
        removed = r["l_status"] == "dropped" and r["l_closed_by"] == "sam" and (r["l_added"] or "") <= (r["l_closed_at"] or "")
        needs, why = replies.asked(r, engaged=replies.sam_wrote(threads, r, after=False) is not None)
        c = calls["removed" if removed else "added"]
        c["n"] += 1
        if removed:
            c["in_inbox" if r["l_reason"] in (loops.REMOVED, *loops.REMOVED_BEFORE) else "in_open_items"] += 1
        if needs == removed:   # the rule flagged mail Sam removed (false positive), or left out mail he added (miss)
            c["rule_flagged" if removed else "rule_left_out"] += 1
            k = c["false_positives" if removed else "misses"]
            k[why] = k.get(why, 0) + 1
    if record:
        con.execute("INSERT INTO evals (run, kind, target, metrics, created_at) VALUES (?,?,?,?,?)",
                    ("needs-reply-" +datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"), "needs-reply", None, json.dumps(out), db.now()))
        con.commit()
    log(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------------------------------------------ links
def eval_links(con, log=print, record=True):
    """How good are the links between items and people / organisations / initiatives (assist/entities.py)?

    The golden set is Sam's own verdicts on links (ticks and crosses on timelines and the Check links page), plus links
    he added by hand. From them:
    - precision: of the links the linker showed that Sam reviewed, the share he ticked (per role: from, speaker, mentioned...)
    - recall: of the links Sam confirmed or added, the share the linker had found and shown by itself
    - hidden_right: links Sam confirmed that the linker found but kept below the display threshold (0.6)
    Coverage (share of items with a shown person / org / initiative link, per kind) is recorded every run, so a change in
    the linker shows up as a jump in the trend even before anything is reviewed."""
    from .entities import ensure_schema
    ensure_schema(con)
    out = {"precision": {}, "recall": {}, "coverage": {}}
    shown = "(m.confidence >= 0.6 AND COALESCE(m.source, 'entities') = 'entities')"
    rows = con.execute(f"SELECT m.entity_type, COALESCE(m.role, '?') AS role, SUM(m.verdict='confirmed') AS ok, SUM(m.verdict='rejected') AS bad "
                       f"FROM mentions m WHERE m.ref_type='item' AND m.verdict IS NOT NULL AND {shown} GROUP BY 1, 2").fetchall()
    tot_ok = tot_bad = 0
    for r in rows:
        n = (r["ok"] or 0) + (r["bad"] or 0)
        out["precision"][f"{r['entity_type']}:{r['role']}"] = {"reviewed": n, "precision": round((r["ok"] or 0) / n, 3) if n else None}
        tot_ok, tot_bad = tot_ok + (r["ok"] or 0), tot_bad + (r["bad"] or 0)
    out["precision"]["all"] = {"reviewed": tot_ok + tot_bad, "precision": round(tot_ok / (tot_ok + tot_bad), 3) if tot_ok + tot_bad else None}
    r = con.execute(f"SELECT COUNT(*) AS n, SUM({shown}) AS found, SUM(m.confidence < 0.6 AND COALESCE(m.source, 'entities')='entities') AS hidden "
                    "FROM mentions m WHERE m.ref_type='item' AND m.verdict='confirmed'").fetchone()
    out["recall"] = {"confirmed": r["n"] or 0, "found_and_shown": r["found"] or 0, "hidden_right": r["hidden"] or 0,
                     "recall": round((r["found"] or 0) / r["n"], 3) if r["n"] else None}
    # a meeting's initiatives are tagged on the meeting (ref_type 'meeting'); "doc" counts working documents only
    # (SharePoint/OneDrive, local), not the product help pages or the knowledge base, which are about no one in particular
    on = lambda t: (f"EXISTS(SELECT 1 FROM mentions m WHERE m.ref_type='item' AND m.ref_id=i.id AND m.entity_type='{t}' AND "
                    f"(m.verdict='confirmed' OR (m.verdict IS NULL AND m.confidence >= 0.6)))"
                    + (" OR EXISTS(SELECT 1 FROM meetings mt JOIN mentions m ON m.ref_type='meeting' AND m.ref_id=mt.id AND m.entity_type='initiative' "
                       "AND COALESCE(m.verdict, '') != 'rejected' WHERE mt.note_item_id=i.id)" if t == "initiative" else ""))
    for k in con.execute("SELECT i.kind, COUNT(*) AS n, " + ", ".join(f"SUM({on(t)}) AS {t}" for t in ("person", "org", "initiative"))
                         + " FROM items i WHERE i.noise=0 AND (i.kind != 'doc' OR i.source_id IN ('sharepoint', 'local')) GROUP BY i.kind"):
        out["coverage"][k["kind"]] = {"items": k["n"], **{t: round((k[t] or 0) / k["n"], 3) for t in ("person", "org", "initiative")}}
    if record:
        con.execute("INSERT INTO evals (run, kind, target, metrics, created_at) VALUES (?,?,?,?,?)",
                    ("links-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"), "links", None, json.dumps(out), db.now()))
        con.commit()
    log(json.dumps(out, indent=1))
    return out
