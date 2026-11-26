---
name: draft
description: Write an email, Teams/Slack message, agenda or one-pager in the user's voice into drafts/. Use when the user says "draft", "write a reply to", "send a note to" (draft only), or invokes /draft <what>.
argument-hint: "<what to write, for whom>"
---

# /draft

Read `memory/context/preferences.md` for voice and the section "In what goes out under my name" of `memory/context/cpo-soul.md` (no date, scope, price or IP position that is not decided: `[FILL: …]` instead). Never put a judgement about anyone's reliability or motives in a draft (`memory/context/soul.md`, rule 8). Read `memory/people/<recipient>.md` if it exists, and the latest relevant Granola summary or thread so the draft reflects what was actually said.

Write to `drafts/YYYY-MM-DD-<slug>.md`:
```
---
to: <name>
channel: email | teams | slack
re: <topic>
status: draft
source: <granola url / thread reference>
---
<subject line, if email>

<body>
```
Rules: follow `memory/context/preferences.md` for channel and audience: purpose or ask first, short sentences, lists once there are three or more points, the spelling in the user's profile (`~/.assist/venv/bin/python -m assist.cli profile`: spelling). Email signs off "Thanks," or "Best," then the sign-off in the profile (signoff, e.g. "-Milo"; no signature block); Teams and Slack have no sign-off. Mark anything the user has not actually said with `[check]`. Do not send. If the user says "send it" after reading, use the connector that matches `channel` and record the sent time in the frontmatter.

## Refresh the UI
If you wrote a document, add it to the database with an ingest bundle (`documents` section, see `assist/ingest.py`) and run `~/.assist/venv/bin/python -m assist.cli ingest`.
