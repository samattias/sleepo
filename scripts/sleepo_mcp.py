"""Relays SleePO's MCP tools to the Claude desktop app, which runs this as "sleepo" from
~/Library/Application Support/Claude/claude_desktop_config.json.

macOS does not let processes the desktop app starts read the OneDrive folder (14 Oct 2026: "Operation not permitted"), so
SleePO's code cannot run here. This relay lives outside OneDrive, uses only the standard library, and passes each JSON-RPC
message to the running SleePO server (POST http://127.0.0.1:8765/api/mcp, assist/mcp_server.py behind it). When SleePO is
not running it still starts, answering the handshake from the last tool list it saw, and each tool call says to open
SleePO. The terminal `claude` runs assist/mcp_server.py directly, since it can read OneDrive.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = os.environ.get("SLEEPO_MCP_URL", "http://127.0.0.1:8765/api/mcp")
CACHE = Path.home() / ".assist" / "sleepo_mcp_cache.json"   # the last initialize and tools/list answers: tool definitions, no data
DOWN = "SleePO is not running, so its tools cannot answer. Open SleePO (Open SleePO.command in your SleePO folder), then try again."


def log(msg):
    print(f"sleepo relay: {msg}", file=sys.stderr, flush=True)


def ask(msg):
    req = urllib.request.Request(URL, data=json.dumps(msg).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
    return json.loads(body) if body.strip() not in (b"", b"null") else None


def cached():
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def remember(msg, resp):
    """Keep the handshake and the tool list, so Claude still sees the tools when it starts before SleePO does."""
    if isinstance(msg, dict) and msg.get("method") in ("initialize", "tools/list") and isinstance(resp, dict) and "result" in resp:
        c = cached()
        c[msg["method"]] = resp["result"]
        try:
            CACHE.write_text(json.dumps(c))
        except OSError as e:
            log(f"could not save {CACHE}: {e}")


def offline(msg, why):
    """The answer when the server cannot answer: the cached handshake and tool list, `why` for anything else."""
    method, mid = msg.get("method"), msg.get("id")
    c = cached()
    if method == "initialize":
        result = c.get("initialize") or {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or "2025-06-18",
                                         "capabilities": {"tools": {"listChanged": False}},
                                         "serverInfo": {"name": "sleepo", "title": "SleePO", "version": "relay"}, "instructions": why}
    elif method == "tools/list":
        result = c.get("tools/list") or {"tools": []}
    elif method == "ping":
        result = {}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": why}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": why}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def reply(resp):
    sys.stdout.buffer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def main():
    log(f"relaying to {URL}")
    for line in iter(sys.stdin.buffer.readline, b""):
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        msgs = msg if isinstance(msg, list) else [msg]
        asks = [m for m in msgs if isinstance(m, dict) and "method" in m and "id" in m]
        if not asks:
            continue   # notifications (and replies to requests we never make): nothing to answer
        try:
            resp = ask(msg)
            remember(msg, resp)
        except urllib.error.HTTPError as e:
            log(f"server answered {e.code}")
            why = f"SleePO's server returned an error ({e.code}). It may be restarting after a code change: try again in a few seconds."
            resp = [offline(m, why) for m in asks] if isinstance(msg, list) else offline(msg, why)
        except (urllib.error.URLError, OSError, ValueError) as e:
            log(f"server unreachable: {e}")
            resp = [offline(m, DOWN) for m in asks] if isinstance(msg, list) else offline(msg, DOWN)
        if resp:
            reply(resp)


if __name__ == "__main__":
    main()
