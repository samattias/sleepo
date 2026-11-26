"""Split one email's plain-text body into the conversation it quotes: the newest message first in the text,
then each quoted message under an Outlook (EN/FR/DE) or Gmail-style header. Signatures, confidentiality
footers and separator lines are trimmed so each message reads as what the person actually wrote."""
import re

HEAD = re.compile(
    r"^[ \t>]*(?:From|De|Von)\s?:\s*(?P<from>.+?)\s*\n+"
    r"[ \t>]*(?:Sent|Envoyé|Gesendet|Date)\s?:\s*(?P<date>.+?)\s*\n+"
    r"(?:[ \t>]*(?:To|À|An)\s?:\s*(?P<to>.*?)\s*\n+)?"
    r"(?:[ \t>]*(?:Cc)\s?:\s*(?P<cc>.*?)\s*\n+)?"
    r"(?:[ \t>]*(?:Subject|Objet|Betreff)\s?:\s*(?P<subject>.*?)\s*\n)?"
    r"|^[ \t>]*On (?P<gdate>[^\n]{5,160}?),? (?P<gfrom>[^\n]{2,120}?) wrote:\s*\n"
    r"|^[ \t>]*Le (?P<fdate>[^\n]{5,160}?),? (?P<ffrom>[^\n]{2,120}?) a écrit\s?:\s*\n",
    re.M)
FOOTER = re.compile(r"(This email and any files transmitted|Cet e-mail et tous les fichiers|This message (?:and any attachments )?is confidential|CONFIDENTIALITY NOTICE)", re.I)
SIGLINE = re.compile(r"@|\b[\w-]+\.(?:com|fr|de|io|net)\b|^\+?\(?\d[\d \-().]{6,}$|\b(Officer|Director|Manager|President|VP|Head of|Engineer|Consultant|Lead|Founder|CEO|CTO|CFO|Sales|Marketing)\b|Named a Leader|^Sent from my|^Get Outlook", re.I)


def _name(s):
    s = (s or "").strip().strip('"')
    m = re.match(r"(.+?)\s*<[^>]+>", s)
    s = m.group(1) if m else s
    return re.sub(r"\s*\[mailto:[^\]]*\]", "", s).strip().strip('"') or s


def clean(text, sender=""):
    text = re.sub(r"^[ \t]*_{8,}[ \t]*$", "", text or "", flags=re.M)
    text = "\n".join(re.sub(r"^\s*>\s?", "", l) for l in text.splitlines())
    m = FOOTER.search(text)
    if m:
        text = text[:m.start()]
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    first = (sender or "").split(" ")[0].lower()
    # drop the signature block: trailing short lines that look like name / title / email / phone / web
    while lines and len(lines) > 1 and len(lines[-1]) < 90 and (SIGLINE.search(lines[-1]) or lines[-1].lower() in {sender.lower(), first} or lines[-1].lower().startswith((first + " ") if first else "\0")):
        lines.pop()
    return "\n".join(lines).strip()


def split(body_text, latest_from="", latest_date="", latest_to=""):
    """-> messages oldest first: {from, date, to, cc, subject, text, latest}"""
    t = (body_text or "").replace("\r\n", "\n")
    out, pos, cur = [], 0, {"from": latest_from, "date": latest_date, "to": latest_to, "cc": "", "subject": "", "latest": True}
    for m in HEAD.finditer(t):
        cur["text"] = clean(t[pos:m.start()], cur["from"])
        out.append(cur)
        g = m.groupdict()
        cur = {"from": _name(g["from"] or g["gfrom"] or g["ffrom"]), "date": (g["date"] or g["gdate"] or g["fdate"] or "").strip(),
               "to": ", ".join(_name(x) for x in re.split(r";\s*", g["to"] or "") if x.strip()), "cc": ", ".join(_name(x) for x in re.split(r";\s*", g["cc"] or "") if x.strip()),
               "subject": (g["subject"] or "").strip(), "latest": False}
        pos = m.end()
    cur["text"] = clean(t[pos:], cur["from"])
    out.append(cur)
    return [x for x in reversed(out) if x["text"] or x["latest"]]
