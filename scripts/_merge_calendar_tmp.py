"""Temporary: merge inbox/calendar/pull-<date>.json into inbox/calendar/events.json (replace by id, keep older)."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parent.parent
events_path = root / "inbox/calendar/events.json"
pull_path = root / sys.argv[1]
data = json.loads(events_path.read_text())
pull = json.loads(pull_path.read_text())
by_id = {e["id"]: e for e in data["events"]}
added = replaced = 0
for e in pull["events"]:
    e["start_tz"] = "UTC"
    e["summary"] = (e.get("summary") or "")[:200]
    old = by_id.get(e["id"])
    if old:
        if not e.get("join_url") and old.get("join_url"):
            e["join_url"] = old["join_url"]
        replaced += 1
    else:
        added += 1
    by_id[e["id"]] = {**(old or {}), **e}
data["events"] = sorted(by_id.values(), key=lambda e: e.get("start") or "")
data["windows"].append(pull["window"])
data["pulled"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
events_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
print(f"events: {len(data['events'])} total, {added} added, {replaced} replaced")
