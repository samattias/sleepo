"""Claude Code PostToolUse hook for the Teams pull (assist/teams_capture.py; Sam, 17 Nov 2026: "make the Teams and Slack
synchronization much faster"). It keeps each Microsoft 365 connector result as it comes back, one JSON file per call, in the
folder named by ASSIST_CAPTURE, so SleePO builds the messages from the raw results in code and the model never retypes them
(it had spent most of a pull writing every message out again into the bundle: 33,000 output tokens, 4 minutes, for 125).

Standalone and stdlib only (it runs once per tool call, inside Claude Code). Without ASSIST_CAPTURE it does nothing, and it
never fails the tool call: any error is swallowed and it exits 0 with no output.
"""
import json
import os
import sys
import time


def main():
    folder = os.environ.get("ASSIST_CAPTURE")
    if not folder:
        return
    try:
        ev = json.load(sys.stdin)
        if not str(ev.get("tool_name") or "").startswith("mcp__claude_ai_Microsoft_365__"):
            return
        os.makedirs(folder, exist_ok=True)
        rec = {"tool": ev["tool_name"].rsplit("__", 1)[-1], "input": ev.get("tool_input"), "response": ev.get("tool_response"),
               "at": time.time()}
        path = os.path.join(folder, f"{time.time_ns()}-{os.getpid()}.json")
        with open(path + ".tmp", "w") as f:
            json.dump(rec, f)
        os.replace(path + ".tmp", path)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
