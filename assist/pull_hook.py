"""Claude Code PostToolUse hook for the pulls that are built in code: the SharePoint & OneDrive index (assist/sp_index.py)
and the knowledge-base sync (assist/kb_sync.py). For each connector call:
1. it keeps the result's objects, one JSON file per call, in the folder named by ASSIST_CAPTURE, so SleePO builds the
   records from the raw results in code and the model never retypes them;
2. it replaces what the model sees with one line (how many results a search page held and its nextOffset; which note was
   read), so a run can make hundreds of calls without carrying their results in its context (17 Nov 2026: SharePoint pages
   of 37,000 to 87,000 characters).
A listing is shown to the model as it is: the model needs it. An empty or failed call is kept as its own words and also
reaches the model unchanged.

Standalone and stdlib only (it runs once per tool call, inside Claude Code). Without ASSIST_CAPTURE it does nothing, and it
never fails the tool call: on any error it prints nothing and the model sees the real result. `load(folder)` is what the
pulls read back, in the server's own Python.
"""
import json
import os
import re
import sys
import time
from pathlib import Path


def _texts(x):
    """The text parts of a tool result, however the hook is handed it (a string, MCP content blocks, a wrapper)."""
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        return [t for y in x for t in _texts(y)]
    if isinstance(x, dict):
        if isinstance(x.get("text"), str):
            return [x["text"]]
        for k in ("content", "result", "structuredContent"):
            if k in x:
                return _texts(x[k])
    return []


def objs(texts):
    """Every JSON object in the result: the connectors return objects one after another ("{…}{…}{…}"), one object, or an array."""
    dec, out = json.JSONDecoder(), []
    for text in texts:
        i = 0
        while i < len(text):
            while i < len(text) and text[i] in " \t\r\n,":
                i += 1
            if i >= len(text):
                break
            try:
                o, i = dec.raw_decode(text, i)
            except ValueError:
                break
            if isinstance(o, dict):
                out.append(o)
            elif isinstance(o, list):
                out += [y for y in o if isinstance(y, dict)]
    return out


def brief(tool, found):
    """The one line the model sees instead of the result, or None to show it the result as it is."""
    if tool.endswith("sharepoint_search"):
        results = [o for o in found if o.get("webUrl")]
        meta = [o for o in found if "nextOffset" in o or "totalResultCount" in o or "moreResults" in o]
        if not results and not meta:
            return None
        nxt = next((o["nextOffset"] for o in reversed(meta) if o.get("nextOffset") is not None), None)
        tot = next((o["totalResultCount"] for o in reversed(meta) if o.get("totalResultCount") is not None), None)
        return (f"Kept by SleePO: {len(results)} results on this page. "
                + (f"nextOffset {nxt}" if nxt is not None else "No nextOffset: this was the last page")
                + (f"; totalResultCount {tot}." if tot is not None else "."))
    if tool.endswith("igxkb_read_note"):
        note = next((o for o in found if isinstance(o.get("content"), str)), None)
        return f"Kept by SleePO: {note.get('path')}, {len(note['content'])} characters." if note else None
    return None


def main():
    folder = os.environ.get("ASSIST_CAPTURE")
    if not folder:
        return
    try:
        ev = json.load(sys.stdin)
        tool = str(ev.get("tool_name") or "")
        if not tool.startswith("mcp__"):
            return
        texts = _texts(ev.get("tool_response"))
        found = objs(texts)
        os.makedirs(folder, exist_ok=True)
        rec = {"tool": tool.rsplit("__", 1)[-1], "input": ev.get("tool_input"), "objs": found,
               "raw": [] if found else [t[:20000] for t in texts], "at": time.time()}   # a folder listing is text (sp_index.folder_lookup)
        path = os.path.join(folder, f"{time.time_ns()}-{os.getpid()}.json")
        with open(path + ".tmp", "w") as f:
            json.dump(rec, f)
        os.replace(path + ".tmp", path)
        out = brief(tool, found)
        if out:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": out}}))
    except Exception:
        pass


def load(folder):
    """The calls this hook kept, oldest first: [{tool, input, objs, raw}] (raw: an empty or failed call's own words). A
    result over the connector's size limit is saved by Claude Code to a tool-results file: it is read from there and the
    file deleted (connector text outside the database is never kept)."""
    calls = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            c = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        saved = re.search(r"saved to (/\S+?\.(?:txt|json))", " ".join(c.get("raw") or []))
        if saved and saved.group(1).startswith(str(Path.home() / ".claude")):
            try:
                c["objs"], c["raw"] = objs([Path(saved.group(1)).read_text()]), []
                Path(saved.group(1)).unlink()
            except OSError:
                pass
        calls.append({"tool": c.get("tool"), "input": c.get("input") or {}, "objs": c.get("objs") or [], "raw": c.get("raw") or []})
    return calls


def settings(matcher):
    """--settings JSON that installs this hook for one run, on the tools the matcher names."""
    import shlex
    py = os.path.expanduser("~/.assist/venv/bin/python")
    py = py if os.path.exists(py) else sys.executable
    cmd = f"{shlex.quote(py)} {shlex.quote(str(Path(__file__)))}"
    return json.dumps({"hooks": {"PostToolUse": [{"matcher": matcher, "hooks": [{"type": "command", "command": cmd, "timeout": 30}]}]}})


if __name__ == "__main__":
    main()
    sys.exit(0)
