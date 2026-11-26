"""The single runner for every model call (claude -p).

- No tools and no MCP servers by default, so untrusted text in a prompt cannot make the model act.
- Model per purpose: settings key llm_model_<purpose>, else llm_model_default, else the Claude Code default.
  (A small model suits classification; briefs and drafts want the strongest.)
- Every call is logged in llm_calls: purpose, model, duration, tokens and cost (from claude's JSON output).
- parse_json() pulls the first JSON object or array out of a reply, so callers validate one way.
- Pictures (images=[{media_type, data}]) go in as image blocks before the prompt, still with no tools (19 Nov 2026: the
  pictures in an email, assist/mail_images.py): the prompt then travels on stdin as one stream-json message.
"""
import base64
import inspect
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

CLAUDE = os.path.expanduser("~/.local/bin/claude")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _caller():
    for f in inspect.stack()[2:6]:
        mod = inspect.getmodule(f.frame)
        name = getattr(mod, "__name__", "") or ""
        if name.startswith("assist.") and not name.endswith((".llm", ".todo")) or name == "assist.todo" and f.function != "_run_model":
            return name.split(".")[-1]
    return "unspecified"


def model_for(con, purpose):
    for key in (f"llm_model_{purpose}", "llm_model_default"):
        r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if r and r["value"]:
            return r["value"]
    return None


def _message(prompt, images):
    """One stream-json user message: the pictures first, then the prompt (the order the model reads best)."""
    content = [{"type": "image", "source": {"type": "base64", "media_type": im["media_type"], "data": base64.b64encode(im["data"]).decode()}}
               for im in images] + [{"type": "text", "text": prompt}]
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def _result(stdout):
    """The final "result" event of a stream-json run, which carries what --output-format json gives."""
    for line in reversed((stdout or "").splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "result":
            return ev
    return {}


def run(prompt, cwd, timeout=420, purpose=None, model=None, tools="", images=None):
    """Run one prompt; return the text. Raises RuntimeError on failure. Logs the call (cost, tokens, model, time).
    images: pictures the model sees with the prompt, [{media_type, data (bytes)}]."""
    from . import db
    purpose = purpose or _caller()
    con = db.connect()
    try:
        model = model or model_for(con, purpose)
    finally:
        con.close()
    exe = CLAUDE if os.path.exists(CLAUDE) else "claude"
    images = [im for im in (images or []) if im.get("data") and im.get("media_type")]
    if images:
        cmd = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--tools", tools, "--strict-mcp-config"]
    else:
        cmd = [exe, "-p", prompt, "--output-format", "json", "--tools", tools, "--strict-mcp-config"]
    if model:
        cmd += ["--model", model]
    started, t0 = _now(), time.time()
    rec = {"purpose": purpose, "model": model, "started_at": started, "prompt_chars": len(prompt), "ok": 0}
    try:
        p = _call(cmd, cwd, timeout, purpose, stdin=_message(prompt, images) if images else None)
        if images:
            d = _result(p.stdout)
        else:
            try:
                d = json.loads(p.stdout or "{}")
            except ValueError:
                d = {}
        u = d.get("usage") or {}
        mu = d.get("modelUsage") or {}
        rec.update(model=model or (next(iter(mu)) if mu else None), cost_usd=d.get("total_cost_usd"),
                   input_tokens=u.get("input_tokens"), output_tokens=u.get("output_tokens"),
                   cache_read_tokens=u.get("cache_read_input_tokens"), cache_write_tokens=u.get("cache_creation_input_tokens"))
        if p.returncode != 0 or d.get("is_error") or "result" not in d:
            err = (d.get("result") if d.get("is_error") else None) or p.stderr or p.stdout or "claude failed"
            rec["error"] = str(err).strip()[-400:]
            raise RuntimeError(rec["error"])
        out = d["result"]
        rec.update(ok=1, output_chars=len(out))
        return out
    except subprocess.TimeoutExpired:
        rec["error"] = f"timed out after {timeout}s"
        raise RuntimeError(rec["error"])
    finally:
        rec.update(finished_at=_now(), secs=round(time.time() - t0, 1))
        _record(rec)


def running_dir():
    """jobs/llm: one small file per claude -p process llm.run has running (<pid>.json, its purpose), so the Agents page
    can say which agent a live process belongs to without reading its prompt (16 Nov 2026: it matched the prompt's first
    words, which named the user and broke silently whenever a prompt was reworded)."""
    from . import db
    return db.db_path().parent / "jobs" / "llm"


def running_purpose(pid):
    """The purpose llm.run recorded for a live process, or None."""
    try:
        return json.loads((running_dir() / f"{int(pid)}.json").read_text()).get("purpose")
    except (OSError, ValueError):
        return None


def _call(cmd, cwd, timeout, purpose, stdin=None):
    """subprocess.run(cmd, capture_output, text, timeout), with the process's purpose on file while it runs; stdin, when
    given, is written to the process (a stream-json message)."""
    p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         stdin=subprocess.PIPE if stdin is not None else None)
    mark = running_dir() / f"{p.pid}.json"
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(json.dumps({"purpose": purpose, "started": _now()}))
    except OSError:
        mark = None
    try:
        out, err = p.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    finally:
        if mark:
            try:
                mark.unlink()
            except OSError:
                pass
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _record(rec):
    """One row in llm_calls (purpose, model, time, tokens, cost); never fails the caller."""
    try:
        from . import db
        con = db.connect()
        cols = list(rec)
        con.execute(f"INSERT INTO llm_calls ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [rec[c] for c in cols])
        con.commit()
        con.close()
    except Exception:
        pass


def record_stream_result(ev, purpose, model=None, prompt_chars=None):
    """Log a tool-using run (`claude -p --output-format stream-json`: the pulls, agent runs) from its final "result" event,
    so its cost and tokens are counted like every llm.run (22 Oct 2026: the pulls were missing from llm_calls). Call it for
    each event; anything but a result event is ignored."""
    if not isinstance(ev, dict) or ev.get("type") != "result":
        return
    secs = round((ev.get("duration_ms") or 0) / 1000, 1)
    u, mu = ev.get("usage") or {}, ev.get("modelUsage") or {}
    rec = {"purpose": purpose, "model": model or (next(iter(mu)) if mu else None),
           "started_at": datetime.fromtimestamp(time.time() - secs, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "finished_at": _now(), "secs": secs, "prompt_chars": prompt_chars, "ok": 0 if ev.get("is_error") else 1,
           "cost_usd": ev.get("total_cost_usd"), "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
           "cache_read_tokens": u.get("cache_read_input_tokens"), "cache_write_tokens": u.get("cache_creation_input_tokens"),
           "output_chars": len(ev.get("result") or "")}
    if ev.get("is_error"):
        rec["error"] = str(ev.get("result") or ev.get("subtype") or "error")[-400:]
    _record(rec)


def parse_json(text, kind=None):
    """First JSON array or object in a model reply. kind='array' or 'object' to insist on one."""
    t = text or ""
    starts = {"array": "[", "object": "{"}
    for ch in ([starts[kind]] if kind else ["[", "{"]):
        i = t.find(ch)
        if i < 0:
            continue
        depth, end = 0, None
        for j in range(i, len(t)):
            if t[j] in "[{":
                depth += 1
            elif t[j] in "]}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end:
            try:
                return json.loads(t[i:end])
            except ValueError:
                m = re.search(r"\[[\s\S]*\]" if ch == "[" else r"\{[\s\S]*\}", t)
                if m:
                    return json.loads(m.group(0))
    raise ValueError("no JSON in the model output")


def costs(con, days=7):
    """Spend and volume per purpose and model over the last `days`."""
    rows = con.execute("SELECT purpose, model, COUNT(*) AS calls, SUM(ok) AS ok, ROUND(SUM(cost_usd), 3) AS cost_usd, ROUND(AVG(secs), 1) AS avg_secs, "
                       "SUM(input_tokens + COALESCE(cache_read_tokens,0) + COALESCE(cache_write_tokens,0)) AS in_tokens, SUM(output_tokens) AS out_tokens "
                       "FROM llm_calls WHERE started_at >= datetime('now', ?) GROUP BY purpose, model ORDER BY cost_usd DESC", (f"-{days} days",)).fetchall()
    return [dict(r) for r in rows]
