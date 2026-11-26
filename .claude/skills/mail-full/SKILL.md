---
name: mail-full
description: Pull the user's new Outlook mail (Inbox and Sent Items) in full through the Microsoft 365 connector into the Assist database. Runs as part of the morning full refresh; also use when the user says "pull my mail in full" or invokes /mail-full.
---

# /mail-full

Full emails (body, recipients, attachment text) for the user's private assistant database. The user approved this as a business
purpose on 2026-10-06; retention is 30 days (DESIGN.md §8). READ ONLY: never send, reply, move, flag or delete mail.
Do the work yourself in this session, step by step. Do not hand it to background agents or subagents: in the headless
morning refresh they are stopped when the run ends, and the brief after this step is lost.

## 1. Window
Find where the last pull ended, per folder:
`~/.assist/venv/bin/python -m assist.cli mail-window`
It prints the after-time for `inbox` and `sent` (one hour of overlap is built in; records are idempotent by graph_id).

## 2. List
Load the tools: ToolSearch `select:mcp__claude_ai_Microsoft_365__outlook_email_search,mcp__claude_ai_Microsoft_365__read_resource`.
For folderName `Inbox` and then `Sent Items`: `outlook_email_search` with `folderName`, `afterDateTime` = the printed time,
`limit` 25, `offset` 0, and keep passing `nextOffset` until there are no more results. No `query`, no `order`.
Record the total listed per folder; it must equal the records you write.

## 3. Read each message
`read_resource(uri)`. Build one record per message:
```json
{"graph_id": "<message id exactly>", "folder": "inbox | sent", "subject": "...", "from": {"name": "...", "address": "..."},
 "to": [{"name": "...", "address": "..."}], "cc": [], "bcc": [], "received_at": "<receivedDateTime>", "sent_at": "<sentDateTime>",
 "conversation_id": "...", "internet_message_id": "...", "web_link": "<webLink>", "importance": "...", "is_read": true,
 "body_text": "...", "attachments": [{"id": "<part after /attachments/ in its uri>", "name": "...", "content_type": "...",
 "size": 0, "is_inline": false, "text": "<extracted text or null>"}]}
```
- **body_text**: the body converted from HTML to plain text, words VERBATIM and in order, paragraphs on new lines. Never
  summarise, paraphrase, correct or translate. Keep quoted reply history. Cap at 15000 characters, then append
  `\n[truncated — open in Outlook for the rest]`. Automated mail (GitLab, Jira, SharePoint, HR and mail-security tools, Teams and
  Slack notifications, newsletters, cold outreach): cap at 2000 characters with the same marker. If a message is too
  large to show inline (read_resource saves it to a file), convert it with
  `~/.assist/venv/bin/python -m assist.cli mail-saved <inbox|sent> <saved file>...` — it writes its own bundle to
  `inbox/queue/` (body converted, caps applied, attachment metadata) and deletes the saved files. Do not write your own
  script: the headless pull may only run `assist.cli`, so an ad-hoc script is blocked and the mail is lost. For an
  attachment on such a message that needs text, read it as usual and add it to a separate record only if the bundle lacks it.
- **attachments**: non-inline only. For .pdf .docx .doc .pptx .ppt .xlsx .xls .txt .csv .md, `read_resource` the
  attachment uri and keep the text (cap 30000 characters + `\n[truncated]`). Images, .ics, .eml, .html, archives and
  anything the connector cannot return: metadata only, `"text": null`.
- Do not mask anything yourself: `assist.cli ingest` masks social security numbers and home addresses (the user's choice).

## 4. Write and load
Write bundles of at most 20 records to `inbox/queue/mailfull-<YYYY-MM-DD>-<folder>-<NN>.json`:
`{"agent": "claude-code:mail-full", "prompt_version": "mail-full-2026-10", "mail_messages": [ ... ]}`
Validate each with `python3 -m json.tool <file> > /dev/null`, then load them by name:
`~/.assist/venv/bin/python -m assist.cli ingest inbox/queue/mailfull-<YYYY-MM-DD>-*.json`
Ingest stores, masks, applies the 30-day purge and deletes the bundle files. Never leave mail text anywhere else:
delete any scratch copies you made.

## 5. Report
One line for the refresh log and the brief's sources line: messages listed and stored per folder, attachments with text,
anything unreadable (subject only, no content). If listed ≠ stored, say so as a gap; do not paper over it.
