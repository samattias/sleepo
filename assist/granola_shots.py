"""Granola screenshots of the shared screen (slides, demos, documents), pulled through Granola's MCP server.

Granola's public API (granola_update.py) returns notes and transcripts but no screenshots; its MCP server
(https://mcp.granola.ai/mcp) lists them per meeting (id, capture time, a machine description) and returns each image.
Use of the MCP was approved by Sam on 20 Oct 2026 (memory: granola-screenshots-route).

Sign-in: SleePO has its own Granola OAuth client (registered once by `assist.cli granola-login`, which Sam runs
himself), approved with a device code; the refresh token sits in the Keychain (service granola-mcp, account sam) next
to the API key. It never borrows Claude Code's sign-in: both would rotate the same refresh token.

Data: one row per screenshot in meeting_shots, linked to the meeting through the note's Granola URL (the MCP's meeting
id is the UUID in it). Image files live outside OneDrive next to the database, with a JPEG thumbnail, and are deleted
RETENTION_DAYS after capture (assist/retention.py); the description stays, like a summary. Personal
meetings are skipped. Nothing is sent: the MCP calls only read.
"""
import base64
import html
import json
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db
from .promptkit import USER   # the user in prompt text (assist/profile.py)
from . import profile
from .retention import RETENTION_DAYS

MCP = "https://mcp.granola.ai/mcp"
AUTH = "https://mcp-auth.granola.ai"
KEYCHAIN = ("granola-mcp", db.keychain_account())
SCOPE = "openid profile email offline_access"
BATCH = 5   # get_meeting_attachment takes at most 5 ids (and about 6 MB) per call


class NotSignedIn(Exception):
    pass


def shots_dir():
    return db.db_path().parent / "granola-shots"


# ---- sign-in --------------------------------------------------------------------------------------------------------

def _load():
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN[0], "-a", KEYCHAIN[1], "-w"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout.strip())
    except ValueError:
        return None


def _save(tok):
    subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN[0], "-a", KEYCHAIN[1], "-w", json.dumps(tok)],
                   check=True, capture_output=True)


def _post_form(url, data):
    import requests
    r = requests.post(url, data=data, timeout=60)
    try:
        body = r.json()
    except ValueError:
        body = {"error": r.text[:200]}
    return r.status_code, body


def login():
    """Register SleePO's client (first time only) and sign in with a device code. Run by Sam in the terminal."""
    import requests
    tok = _load() or {}
    if not tok.get("client_id"):
        r = requests.post(AUTH + "/oauth2/register", json={
            "client_name": f"SleePO ({USER.name}, this Mac)", "token_endpoint_auth_method": "none",
            # Granola's registration (27 Oct 2026) wants a redirect address and a response type even for a device-code client,
            # and no longer knows the "mcp" scope
            "grant_types": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token", "authorization_code"],
            "response_types": ["code"], "redirect_uris": ["http://127.0.0.1:8765/granola/callback"],
            "scope": SCOPE}, timeout=60)
        if r.status_code >= 300:
            raise SystemExit(f"Granola refused the client registration ({r.status_code}): {r.text[:300]}")
        tok = {"client_id": r.json()["client_id"]}
        _save(tok)
    code, flow = _post_form(AUTH + "/oauth2/device_authorization", {"client_id": tok["client_id"], "scope": SCOPE, "resource": MCP})
    if code >= 300 or "device_code" not in flow:
        raise SystemExit(f"could not start the Granola sign-in ({code}): {json.dumps(flow)[:300]}")
    print(f"Open {flow.get('verification_uri_complete') or flow.get('verification_uri')} and approve"
          + (f" (code {flow['user_code']})" if flow.get("user_code") else ""), flush=True)
    wait, deadline = int(flow.get("interval") or 5), time.time() + int(flow.get("expires_in") or 600)
    while time.time() < deadline:
        time.sleep(wait)
        code, res = _post_form(AUTH + "/oauth2/token", {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                                        "device_code": flow["device_code"], "client_id": tok["client_id"]})
        if "access_token" in res:
            _store(tok, res)
            print("signed in to Granola; screenshots will come in with the next sync")
            return
        err = res.get("error")
        if err == "slow_down":
            wait += 5
        elif err != "authorization_pending":
            raise SystemExit(f"Granola sign-in failed: {res.get('error_description') or err}")
    raise SystemExit("Granola sign-in timed out; run granola-login again")


def _store(tok, res):
    tok = dict(tok, access_token=res["access_token"], expires_at=time.time() + int(res.get("expires_in") or 3600))
    if res.get("refresh_token"):   # rotated on every refresh
        tok["refresh_token"] = res["refresh_token"]
    _save(tok)
    return tok


def token():
    tok = _load()
    if not tok or not tok.get("refresh_token") and not tok.get("access_token"):
        raise NotSignedIn()
    if tok.get("access_token") and tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise NotSignedIn()
    code, res = _post_form(AUTH + "/oauth2/token", {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": tok["client_id"]})
    if "access_token" not in res:
        raise NotSignedIn(res.get("error_description") or res.get("error") or f"HTTP {code}")
    return _store(tok, res)["access_token"]


# ---- MCP over streamable HTTP (JSON-RPC; no SDK: the venv is Python 3.9) ----------------------------------------------

class Client:
    def __init__(self):
        import requests
        self.s = requests.Session()
        self.sid = None
        self.n = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "sleepo", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        h = {"Authorization": "Bearer " + token(), "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        r = self.s.post(MCP, json=msg, headers=h, timeout=180)
        if r.status_code == 401:
            raise NotSignedIn("the Granola MCP refused the token")
        r.raise_for_status()
        self.sid = r.headers.get("Mcp-Session-Id") or self.sid
        return r

    def _rpc(self, method, params):
        self.n += 1
        r = self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        msg = _reply(r.headers.get("Content-Type", ""), r.text, self.n)
        if "error" in msg:
            raise RuntimeError(f"Granola MCP {method}: {msg['error'].get('message')}")
        return msg.get("result") or {}

    def call(self, tool, args):
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        if res.get("isError"):
            raise RuntimeError(f"Granola MCP {tool}: " + " ".join(c.get("text", "") for c in res.get("content") or [])[:300])
        return res.get("content") or []


def _reply(ctype, body, want):
    """The JSON-RPC answer with id `want`, from a JSON body or a server-sent event stream."""
    if "text/event-stream" in ctype:
        for chunk in body.split("\n\n"):
            data = "\n".join(l[5:].lstrip() for l in chunk.splitlines() if l.startswith("data:"))
            if data:
                try:
                    msg = json.loads(data)
                except ValueError:
                    continue
                if msg.get("id") == want:
                    return msg
        return {"error": {"message": "no answer in the event stream"}}
    return json.loads(body)


def _text(content):
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


# ---- parsing the MCP's answers ----------------------------------------------------------------------------------------

ATTR = re.compile(r'(\w+)="([^"]*)"')


def parse_list(text):
    """list_meetings -> [{id, title, meeting_at, updated_at, screenshot_count}] for meetings with screenshots."""
    out = []
    for tag in re.findall(r"<meeting\s[^>]*>", text):
        a = {k: html.unescape(v) for k, v in ATTR.findall(tag)}
        if a.get("id") and int(a.get("screenshot_count") or 0):
            out.append({"id": a["id"], "title": a.get("title", ""), "meeting_at": a.get("meeting_at", ""),
                        "updated_at": a.get("updated_at", ""), "screenshot_count": int(a["screenshot_count"])})
    return out


def parse_meetings(text):
    """get_meetings -> {meeting id: [{id, captured_at, description}]} in capture order."""
    out = {}
    parts = re.split(r'(?=<meeting id=")', text)
    for part in parts:
        m = re.match(r'<meeting id="([^"]+)"', part)
        if not m:
            continue
        shots = []
        for attrs, desc in re.findall(r"<attachment\s([^>]*)>(.*?)</attachment>", part, re.S):
            a = dict(ATTR.findall(attrs))
            if a.get("id") and a.get("type", "screenshot") == "screenshot":
                shots.append({"id": a["id"], "captured_at": a.get("captured_at", ""), "description": html.unescape(desc.strip())})
        out[m.group(1)] = shots
    return out


def parse_images(content):
    """get_meeting_attachment -> {attachment id: (bytes, mime)}. Each image is followed by a text block with its
    metadata; an attachment that failed comes back as text naming its id, with no image."""
    out, pending = {}, None
    for c in content:
        if c.get("type") == "image":
            pending = (base64.b64decode(c.get("data") or ""), c.get("mimeType") or "image/png")
        elif c.get("type") == "text":
            m = re.search(r'"attachment_id"\s*:\s*"([0-9a-fA-F-]{36})"', c.get("text", ""))
            if m and pending:
                out[m.group(1)] = pending
            pending = None
    return out


def png_size(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None, None


# ---- placing a screenshot in the transcript ----------------------------------------------------------------------------

def local_secs(iso_utc):
    """Seconds since local midnight (Europe/London) of a UTC timestamp: the transcript files' [HH:MM:SS] clock."""
    from zoneinfo import ZoneInfo
    d = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(profile.zone())
    return d.hour * 3600 + d.minute * 60 + d.second


def rel_seconds(iso_utc, start_secs):
    """Seconds from the start of the recording (the first transcript line), as the transcript view counts them."""
    s = local_secs(iso_utc)
    return s - start_secs if s >= start_secs - 300 else s + 86400 - start_secs   # meetings that cross midnight


def first_clock(text):
    m = re.search(r"\*\*\[(\d\d):(\d\d):(\d\d)\]", text or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None


# ---- the pull ---------------------------------------------------------------------------------------------------------

def _note_for(con, gid):
    """The SleePO note item and meeting for a Granola meeting id (the UUID in the note's URL). A note that continued
    another recording (assist/granola_stitch.py) belongs to the meeting it was appended to."""
    it = con.execute("SELECT id, external_id, retention FROM items WHERE kind='note' AND url LIKE ?", (f"%/d/{gid}",)).fetchone()
    if not it:
        return None, None, None
    m = con.execute("SELECT id, status FROM meetings WHERE note_item_id=?", (it["id"],)).fetchone()
    if not m:
        host = con.execute("SELECT m.id, m.status FROM meetings m JOIN items i ON i.id=m.note_item_id WHERE i.payload LIKE ?",
                           (f'%"_continued_by"%{it["external_id"]}%',)).fetchone()
        m = host
    return it, m, it["retention"]


def _thumb(src, dst):
    """A small JPEG for the filmstrip (macOS sips; the full image is kept as captured)."""
    try:
        subprocess.run(["sips", "-Z", "480", "-s", "format", "jpeg", "-s", "formatOptions", "70", str(src), "--out", str(dst)],
                       check=True, capture_output=True, timeout=60)
        return True
    except Exception:
        return False


def sync(con, days=3, log=print):
    """Pull screenshots for meetings in the last `days` days that have new ones, then delete images past RETENTION_DAYS."""
    days = min(days, RETENTION_DAYS)
    for r in con.execute("SELECT DISTINCT granola_meeting FROM meeting_shots WHERE meeting_id IS NULL").fetchall():   # meeting made since
        _, m, _ = _note_for(con, r["granola_meeting"])
        if m:
            con.execute("UPDATE meeting_shots SET meeting_id=? WHERE granola_meeting=? AND meeting_id IS NULL", (m["id"], r["granola_meeting"]))
    cli = Client()
    start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    listed = parse_list(_text(cli.call("list_meetings", {"time_range": "custom", "custom_start": start,
                                                         "custom_end": datetime.now(timezone.utc).date().isoformat(),
                                                         "involvement": {"captured_by_me": True}})))
    have = {r["granola_meeting"]: r["n"] for r in con.execute("SELECT granola_meeting, COUNT(*) AS n FROM meeting_shots GROUP BY granola_meeting")}
    todo = []
    for g in listed:
        it, m, _ = _note_for(con, g["id"])
        if not it:
            continue   # the note is not in SleePO yet (the API pull runs first); next sync
        if m and m["status"] == "personal":
            continue   # personal meetings are out of scope
        if have.get(g["id"], 0) < g["screenshot_count"]:
            todo.append(g)
    new = fetched = 0
    for i in range(0, len(todo), 10):   # get_meetings takes 10 ids
        batch = todo[i:i + 10]
        found = parse_meetings(_text(cli.call("get_meetings", {"meeting_ids": [g["id"] for g in batch]})))
        for g in batch:
            it, m, retention = _note_for(con, g["id"])
            for s in found.get(g["id"], []):
                cur = con.execute("INSERT OR IGNORE INTO meeting_shots (id, granola_meeting, note_item_id, meeting_id, captured_at, description, retention, created_at) "
                                  "VALUES (?,?,?,?,?,?,?,?)", (s["id"], g["id"], it["id"], m["id"] if m else None, s["captured_at"], s["description"],
                                                               retention or "general", db.now()))
                new += cur.rowcount
        con.commit()
    keep_from = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    want = con.execute("SELECT id, granola_meeting FROM meeting_shots WHERE file IS NULL AND purged_at IS NULL AND captured_at >= ? "
                       "AND (tries IS NULL OR tries < 3) ORDER BY captured_at", (keep_from,)).fetchall()
    by_meeting = {}
    for r in want:
        by_meeting.setdefault(r["granola_meeting"], []).append(r["id"])
    out = shots_dir()
    for gid, ids in by_meeting.items():
        (out / gid).mkdir(parents=True, exist_ok=True)
        for j in range(0, len(ids), BATCH):
            chunk = ids[j:j + BATCH]
            try:
                imgs = parse_images(cli.call("get_meeting_attachment", {"meeting_id": gid, "attachment_ids": chunk}))
            except RuntimeError as e:
                log(f"  {gid}: {e}")
                imgs = {}
            for aid in chunk:
                if aid not in imgs:   # too large for this batch or failed: tried again alone next sync
                    con.execute("UPDATE meeting_shots SET tries=IFNULL(tries,0)+1 WHERE id=?", (aid,))
                    continue
                data, mime = imgs[aid]
                f = out / gid / (aid + (".png" if "png" in mime else ".jpg"))
                f.write_bytes(data)
                w, h = png_size(data)
                th = out / gid / (aid + ".thumb.jpg")
                con.execute("UPDATE meeting_shots SET file=?, thumb=?, mime=?, width=?, height=?, bytes=?, fetched_at=? WHERE id=?",
                            (str(f), str(th) if _thumb(f, th) else None, mime, w, h, len(data), db.now(), aid))
                fetched += 1
            con.commit()
    purged = purge(con)
    log(f"granola screenshots: {len(listed)} meetings with screenshots in {days} days · {len(todo)} with new ones · "
        f"{new} new · {fetched} images fetched · {purged} past {RETENTION_DAYS} days deleted")
    return {"meetings": len(listed), "new": new, "fetched": fetched, "purged": purged}


def purge(con, days=RETENTION_DAYS):
    """Delete image files captured more than `days` days ago; the row and its description stay."""
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    for r in con.execute("SELECT id, file, thumb FROM meeting_shots WHERE purged_at IS NULL AND captured_at < ?", (cut,)).fetchall():
        for p in (r["file"], r["thumb"]):
            if p:
                Path(p).unlink(missing_ok=True)
        con.execute("UPDATE meeting_shots SET file=NULL, thumb=NULL, purged_at=? WHERE id=?", (db.now(), r["id"]))
        n += 1
    con.commit()
    return n


# ---- reading ----------------------------------------------------------------------------------------------------------

def for_meeting(con, meeting_id, start_secs=None):
    """The meeting's screenshots in capture order, each placed at its second of the recording when the start is known."""
    try:
        rows = con.execute("SELECT * FROM meeting_shots WHERE meeting_id=? ORDER BY captured_at", (meeting_id,)).fetchall()
    except Exception:   # table not migrated yet
        return []
    out = []
    for r in rows:
        out.append({"id": r["id"], "captured_at": r["captured_at"], "description": r["description"] or "",
                    "t": rel_seconds(r["captured_at"], start_secs) if start_secs is not None and r["captured_at"] else None,
                    "available": bool(r["file"] and Path(r["file"]).exists()), "width": r["width"], "height": r["height"],
                    "sensitive": r["retention"] == "hr_legal"})
    return out


def file_for(con, shot_id, thumb=False):
    r = con.execute("SELECT file, thumb, mime FROM meeting_shots WHERE id=?", (shot_id,)).fetchone()
    if not r:
        return None, None
    p = r["thumb"] if thumb and r["thumb"] else r["file"]
    if not p or not Path(p).exists():
        return None, None
    return Path(p), ("image/jpeg" if p.endswith(".jpg") else r["mime"] or "image/png")


def pack_lines(shots, mmss):
    """Lines for a tool-free pack (follow-ups): what was on screen, by moment. Descriptions are Granola's, machine-made."""
    if not shots:
        return []
    L = [f"## On the shared screen ({len(shots)} screenshots; Granola's machine descriptions, lossy; [mm:ss] when captured)"]
    for s in shots:
        L.append(f"- [{mmss(s['t']) if s['t'] is not None else '?'}] {s['description'][:600]}")
    L.append("")
    return L
