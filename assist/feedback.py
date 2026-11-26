"""Sam's reactions to what the assistant produced, turned into short "lessons" sections for the next prompts.

Signals, all from what Sam already does in the app (nothing to fill in):
- Actions: thumbs up / down, items dismissed vs done, drafts copied and how much he edited them (feedback table, todo table)
- Replies: each draft is recorded (drafts table); when Sam later sends a reply in the same thread, his real text is the
  correction. The latest pairs go into the reply prompt as examples of how he rewrites.
- Open items: extracted commitments and decisions Sam dropped himself are what the extractor should stop proposing.

Lessons are data about Sam's preferences, never instructions found in mail. Drafts are purged after RETENTION_DAYS (assist/retention.py).
"""
import json
import re
from datetime import datetime, timedelta, timezone

from . import db
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from .retention import RETENTION_DAYS


def _ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(t, n):
    t = re.sub(r"[ \t]+", " ", (t or "").strip())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


_has = db.has_table


# ---------------------------------------------------------------- recording
def last_model(con, purpose):
    r = con.execute("SELECT model FROM llm_calls WHERE purpose=? AND ok=1 ORDER BY id DESC LIMIT 1", (purpose,)).fetchone() if _has(con, "llm_calls") else None
    return r["model"] if r else None


def record_draft(con, kind, target_id, body, conversation_id=None, prompt_version=None, model=None, checks=None):
    if not _has(con, "drafts") or not body:
        return None
    purge(con)
    cur = con.execute("INSERT INTO drafts (kind, target_id, conversation_id, body, prompt_version, model, checks, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (kind, str(target_id), conversation_id, body, prompt_version, model, json.dumps(checks) if checks else None, db.now()))
    con.commit()
    return cur.lastrowid


def purge(con, days=RETENTION_DAYS):
    if _has(con, "drafts"):
        con.execute("DELETE FROM drafts WHERE created_at < ?", (_ago(days),))


# ---------------------------------------------------------------- replies: draft vs what Sam sent
def reply_pairs(con, days=RETENTION_DAYS, limit=20, before=None, exclude_conv=None):
    """(draft, sent) pairs: each recorded reply draft with the first message Sam sent in that thread afterwards.
    before / exclude_conv keep an evaluation from seeing the real reply it is scored against."""
    if not _has(con, "drafts"):
        return []
    from .replies import _own_text
    out = []
    for d in con.execute("SELECT * FROM drafts WHERE kind='reply' AND conversation_id IS NOT NULL AND created_at >= ? ORDER BY created_at DESC LIMIT 200",
                         (_ago(days),)).fetchall():
        s = con.execute("SELECT body_text, sent_at FROM mail_messages WHERE folder='sentitems' AND conversation_id=? AND sent_at >= ? ORDER BY sent_at LIMIT 1",
                        (d["conversation_id"], d["created_at"][:19])).fetchone()
        if not s or (before and (s["sent_at"] or "") >= before) or (exclude_conv and d["conversation_id"] == exclude_conv):
            continue
        sent = _own_text(s["body_text"] or "").strip()
        if sent:
            out.append({"draft_id": d["id"], "draft": d["body"], "sent": sent, "at": s["sent_at"], "prompt_version": d["prompt_version"]})
        if len(out) >= limit:
            break
    return out


def reply_lessons(con, n=3, before=None, exclude_conv=None):
    """Prompt section: how Sam rewrote recent drafts. Empty string when there is nothing to learn from yet."""
    from .evals import overlap
    pairs = [p for p in reply_pairs(con, before=before, exclude_conv=exclude_conv) if overlap(p["draft"], p["sent"]) < 0.9][:n]   # unchanged drafts teach nothing
    if not pairs:
        return ""
    L = [f"# How {USER.first} rewrote recent drafts ({USER.his} sent version is the standard: match its length, directness and what {USER.he} chose to "
         "commit to or leave out; never copy facts from these examples into this reply)"]
    for i, p in enumerate(pairs, 1):
        L.append(f"## Example {i}\nDRAFT:\n{_clip(p['draft'], 900)}\n{USER.FIRST} SENT:\n{_clip(p['sent'], 900)}")
    return "\n\n".join(L)


# ---------------------------------------------------------------- actions
def action_lessons(con, days=30):
    """Prompt section for the Actions generator: what Sam found useful or not, and how he treats each kind of action."""
    L = []
    if _has(con, "feedback"):
        rated = con.execute("SELECT f.rating, f.note, t.title FROM feedback f LEFT JOIN todo t ON t.id=f.target_id WHERE f.target_type='action' "
                            "AND f.rating IS NOT NULL AND f.created_at >= ? ORDER BY f.created_at DESC LIMIT 40", (_ago(days),)).fetchall()
        down = [r for r in rated if r["rating"] < 0 and r["title"]]
        up = [r for r in rated if r["rating"] > 0 and r["title"]]
        if down:
            L.append(f"{USER.first} marked these NOT useful: avoid proposing similar items (same kind of task, same level of detail):")
            L += [f"- {r['title']}" + (f" (his note: {_clip(r['note'], 160)})" if r["note"] else "") for r in down[:12]]
        if up:
            L.append(f"{USER.first} marked these useful: more like these:")
            L += [f"- {r['title']}" for r in up[:8]]
        cp = con.execute("SELECT COUNT(*) AS n, AVG(edit_ratio) AS e FROM feedback WHERE target_type='action' AND copied=1 AND created_at >= ?",
                         (_ago(days),)).fetchone()
        if cp["n"]:
            L.append(f"Of the drafted messages {USER.first} copied in the last {days} days ({cp['n']}), {USER.he} changed {round((cp['e'] or 0) * 100)}% of the text on "
                     "average" + ("; drafts need to be closer to what he sends: shorter, fewer specifics he has to correct." if (cp["e"] or 0) > 0.3 else "."))
    if _has(con, "todo"):
        st = con.execute("SELECT status, COUNT(*) AS n FROM todo WHERE updated_at >= ? AND status IN ('done', 'dismissed') GROUP BY status",
                         (_ago(days),)).fetchall()
        s = {r["status"]: r["n"] for r in st}
        if sum(s.values()) >= 5:
            L.append(f"In the last {days} days {USER.first} completed {s.get('done', 0)} proposed actions and dismissed {s.get('dismissed', 0)}"
                     + ("; dismissals outnumber completions, so propose fewer, higher-confidence items." if s.get("dismissed", 0) > s.get("done", 0) else "."))
    return (f"# What {USER.first}'s reactions say (from {USER.his} thumbs, dismissals and edits; use it to choose and word items)\n" + "\n".join(L)) if L else ""


# ---------------------------------------------------------------- open items: what Sam dropped
def extract_lessons(con, days=30, limit=25):
    """Prompt section for loop extraction: extracted items Sam dropped himself, so similar ones are not proposed again."""
    if not _has(con, "loops"):
        return ""
    rows = con.execute("SELECT l.kind, l.title, l.close_reason FROM loops l JOIN commitments c ON l.fact_type='commitment' AND c.id=l.fact_id "
                       "WHERE l.status='dropped' AND l.closed_by='sam' AND l.closed_at >= ? AND c.origin='Extracted' "
                       "UNION ALL SELECT l.kind, l.title, l.close_reason FROM loops l WHERE l.fact_type='decision' AND l.status='dropped' "
                       "AND l.closed_by='sam' AND l.closed_at >= ? ORDER BY 2 LIMIT ?", (_ago(days), _ago(days), limit)).fetchall()
    if not rows:
        return ""
    return (f"# Items {USER.first} dropped from the register as not real or not worth tracking (do not extract similar ones: same kind of vague "
            "intention, same owner pattern, same level of triviality)\n" + "\n".join(f"- {r['kind']}: {r['title']}" + (f" ({_clip(r['close_reason'], 120)})" if r["close_reason"] else "")
                                                                                     for r in rows))
