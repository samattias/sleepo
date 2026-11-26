"""Actions proposed by the brief and meeting briefs that leave the app: an Outlook draft or a Slack draft.

Nothing is ever sent. Each runs a short headless Claude Code session that may use exactly one or two drafting tools
(no Bash, no file access), with the arguments already built here from what Sam saw and edited on the page, so the
model only relays them. Teams messages and "open in Outlook" need no server: the page opens Microsoft's own compose
links with the text prefilled, and Sam presses send himself.
"""
import html
import json
import os
import re
import subprocess
import threading
import time
import uuid

JOBS = {}   # id -> {"running", "ok", "result", "error", "started", "finished", "kind"}
M365 = "mcp__claude_ai_Microsoft_365__"
SLACK = "mcp__plugin_productivity_slack__"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _html(body):
    paras = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paras)


def _claude(prompt, tools, cwd, timeout=300):
    claude = os.path.expanduser("~/.local/bin/claude")
    cmd = [claude if os.path.exists(claude) else "claude", "-p", prompt, "--output-format", "text", "--allowedTools"] + tools
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    return p.returncode == 0, (p.stdout or "").strip(), (p.stderr or "").strip()


def outlook_prompt(a):
    """mode: new (default when no reply_to) | reply | replyall | forward. Arguments are built here, the model only relays them."""
    to = [x for x in (a.get("to") or []) if EMAIL.match(x)]
    cc = [x for x in (a.get("cc") or []) if EMAIL.match(x)]
    mode = a.get("mode") or ("reply" if a.get("reply_to") else "new")
    body = _html(a.get("body"))
    if mode == "forward":
        if not to:
            raise ValueError("a forward needs at least one recipient address")
        body += "<hr>" + _html(a.get("forward_block") or "")
        steps = [(M365 + "outlook_create_draft", {"to": to, "cc": cc, "subject": (a.get("subject") or "")[:255], "body": body, "bodyType": "html"})]
    elif mode in ("reply", "replyall"):
        if not a.get("reply_to"):
            raise ValueError("a reply needs the original message")
        tool = M365 + ("outlook_create_reply_all_draft" if mode == "replyall" else "outlook_create_reply_draft")
        steps = [(tool, {"messageId": a["reply_to"], "body": body, "bodyType": "html"})]
        if cc:   # add people: replace the reply's Cc with the full list computed by the server
            steps.append((M365 + "outlook_update_draft", {"messageId": "<id returned by the first call>", "cc": cc}))
    else:
        if not to:
            raise ValueError("an email needs at least one valid recipient address")
        steps = [(M365 + "outlook_create_draft", {"to": to, "cc": cc, "subject": (a.get("subject") or "")[:255], "body": body, "bodyType": "html"})]
    tools = ["ToolSearch"] + sorted({t for t, _ in steps})
    lines = [f"{i + 1}. call {t} with exactly these arguments: {json.dumps(args, ensure_ascii=False)}" for i, (t, args) in enumerate(steps)]
    prompt = (f"Create exactly one Outlook draft. Load the tools with ToolSearch query 'select:{','.join(tools[1:])}', then:\n" + "\n".join(lines) +
              "\nDo not send anything and do not call any other tool. Reply with only the draft's webLink.")
    return prompt, tools


def slack_prompt(a):
    target, message = (a.get("channel") or a.get("user") or "").strip(), (a.get("message") or "").strip()
    if not target or not message:
        raise ValueError("a Slack draft needs a channel or person and a message")
    tools = ["ToolSearch", SLACK + "slack_search_users", SLACK + "slack_search_channels", SLACK + "slack_send_message_draft"]
    prompt = (f"Create exactly one Slack draft (do not send). Load the tools with ToolSearch query 'select:{','.join(tools[1:])}'. "
              f"Find the Slack conversation for this target: {json.dumps(target)} "
              "(a channel name or id, or a person: for a person use their user id as channel_id). "
              f"Then call {SLACK}slack_send_message_draft once with that channel_id and exactly this message:\n{json.dumps(message, ensure_ascii=False)}\n"
              "If a draft already exists there, stop and say so. Reply with only the channel link, or the reason it failed.")
    return prompt, tools


def start(kind, a, cwd):
    prompt, tools = (outlook_prompt if kind == "outlook" else slack_prompt)(a)   # raises ValueError on bad input
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"kind": kind, "running": True, "ok": None, "result": "", "error": "", "started": time.strftime("%H:%M:%S"), "finished": None}

    def work():
        j = JOBS[jid]
        try:
            ok, out, err = _claude(prompt, tools, cwd)
            link = (re.search(r"https://\S+", out) or [None])[0]
            j["ok"] = ok and bool(link)
            j["result"] = link.rstrip(").,") if link else ""
            j["error"] = "" if j["ok"] else (out or err)[-400:]
        except Exception as e:  # pragma: no cover
            j["ok"], j["error"] = False, str(e)
        j["running"], j["finished"] = False, time.strftime("%H:%M:%S")

    threading.Thread(target=work, daemon=True).start()
    return jid
