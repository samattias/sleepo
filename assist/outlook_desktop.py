"""Open a new message in Outlook for Mac, filled in (Sam, 28 Oct 2026: "open in Outlook desktop rather than the web app").

Until IT approves SleePO's Outlook access (outlook_drafts.py, 22 Oct 2026), Open in Outlook could not save a real draft and
fell back to Outlook on the web's compose page. This opens the desktop app instead: a mailto: link handed to Outlook itself
(`open -a`), whatever the Mac's default mail app is. Outlook opens a new message with To, Cc, Subject and the text; Sam sends
it or not. Like the web fallback it is a new message, not a reply in the email's thread. Nothing is sent from here."""
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

APP = Path("/Applications/Microsoft Outlook.app")
ADDR = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[A-Za-z]{2,}")


def url(to, cc, subject, body):
    """The mailto: link: only real addresses, the subject and text percent-encoded (so nothing can add headers)."""
    clean = lambda xs: [x.strip() for x in (xs or []) if isinstance(x, str) and ADDR.fullmatch(x.strip())]
    parts = [f"cc={quote(','.join(clean(cc)), safe='@,')}"] if clean(cc) else []
    parts += [f"subject={quote((subject or '')[:250], safe='')}", f"body={quote((body or '')[:20000], safe='')}"]
    return "mailto:" + ",".join(quote(a, safe="@") for a in clean(to)) + "?" + "&".join(parts)


def compose(to, cc, subject, body):
    if not APP.is_dir():
        raise FileNotFoundError("Outlook for Mac is not installed")
    subprocess.run(["open", "-a", str(APP), url(to, cc, subject, body)], check=True, timeout=15, capture_output=True)
