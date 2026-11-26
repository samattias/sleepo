---
name: brief
description: The user's daily chief-of-staff brief, on demand (not part of the morning refresh). Use when the user asks for the brief, "what matters today", "what should I focus on", or invokes /brief. Produces briefs/<date>.md (and an HTML page when asked).
---

# /brief

Read `CLAUDE.md` first. Since 12 Oct 2026 the morning refresh no longer writes a brief; this skill runs only when the user asks. Its
"1. Gather" section is also what the refresh's connector pull follows, so keep it current. The brief is written **from the database** by a tool-free run (`assist/briefgen.py`); this skill's job is to make sure the database is current, then run it.

## 1. Gather
1. Run `python3 scripts/collect_granola.py` so any new meetings are digested. Read `inbox/granola/latest.md` (summaries and candidates only; open a transcript only if a candidate is ambiguous).
2. **Read everything in the window, not the first page.** Every search tool returns 25 items per page; keep calling with `offset`/`nextOffset` (or `cursor`) until `moreResults` is false, and record the totals in `inbox/coverage.json` (available / digested / analysed per source). Mail noise (BambooHR, AppRiver, SharePoint notices, Gartner, Teams digests, mail to Pat's address) is counted but not analysed.
3. If the Microsoft 365 connector is authenticated: today's and tomorrow's calendar; mail threads where the user was asked something and has not replied; Teams mentions/DMs ending in a question the user has not answered (last 2 days). If Slack is authenticated: same for Slack. If Atlassian is reachable: Jira issues assigned to the user that are due or flagged.
4. **Calendar file.** First run `~/.assist/venv/bin/python -m assist.cli calendar-local`: exit 0 means the calendar came from Calendar.app on this Mac (live, with the user's own replies; moved and removed meetings are already applied), so skip the connector pull below and go straight to `python3 scripts/reconcile_calendar.py`. Exit 2 (no Full Disk Access) or 3 (Calendar.app has not synced lately): pull from the connector as follows. Write today's calendar pull (yesterday to next 14 days, paginated to the end; older events are already stored) to `inbox/calendar/pull-<today>.json` as `{"window": {afterDateTime, beforeDateTime, totalResultCount, events_fetched}, "events": [...]}` in the events.json schema (`id, subject, start, start_tz, end, organizer, attendees, location, isCancelled, isOrganizer, isAllDay, showAs, webLink, summary≤200, join_url`; `join_url` is the Teams/Zoom/Meet join link from the event's summary or, if absent there, `onlineMeeting.joinUrl` via `read_resource` on the event — never store passcodes or dial-ins). Merge it with `~/.assist/venv/bin/python -m assist.cli calendar-merge inbox/calendar/pull-<today>.json` (replaces events by `id`, keeps older ones; a complete pull, `events_fetched` equal to `totalResultCount`, also marks events in its window that it no longer has as removed, so record both counts truthfully; do not write your own merge script), then run `python3 scripts/reconcile_calendar.py` so Granola notes pick up the real subject and attendees.
5. Save what the connectors returned as a metadata snapshot in `inbox/live/YYYY-MM-DD.md` (who, when, subject or first line, link; times in the user's time zone (the profile); mark noise). No bodies, no addresses. This is what the UI shows under *Live pulls*.
6. If a connector is not authenticated, say so in one line at the end of the brief and carry on with what is available. Never fabricate calendar or inbox content.

## 2. Load what you pulled
Write ONE ingest bundle `inbox/queue/pull-YYYY-MM-DD.json` (format at the top of `assist/ingest.py`): `pulls` (one per source window, with
available / pulled / noise and `complete: true` only if you paginated to the end), `items` (calendar only; `noise: true` for noise),
`chat_messages` (every Teams and Slack message you read, its text verbatim, `noise` set for bots and notifications; never a summary or gist,
and no Teams or Slack `items`: ingest drops them), `source_health`, `gaps`. Do **not** write commitments or the brief yourself (decisions are retired). Then run:
```
~/.assist/venv/bin/python -m assist.cli ingest
~/.assist/venv/bin/python -m assist.cli sync-granola     # imports the calendar file you merged
```

## 3. Build the brief (no tools touch untrusted text from here)
```
~/.assist/venv/bin/python -m assist.cli link             # tie new items to people, organisations, initiatives
~/.assist/venv/bin/python -m assist.cli loops all        # new commitments from new material, sync the open-items register, close items from evidence
~/.assist/venv/bin/python -m assist.cli tasks sync       # the user's tasks: steps closed by evidence, new suggestions (no model)
~/.assist/venv/bin/python -m assist.cli brief            # writes briefs/YYYY-MM-DD.md and ingests it
```
The brief's format, ranking rules and voice live in `assist/briefgen.py` (INSTRUCTIONS). The user's list is Tasks (`assist/tasks.py`,
Tasks page: initiative → task → step → action); the brief points at his next steps there rather than keeping its own list. The
`loops` register underneath holds what the sources say is owed; edit status in the app, not in the Markdown.

## 4. Finish
Append a one-line entry to `briefs/README.md` (date · headline). Tell the user the three things in chat, then the file path.
If a connector was not authenticated, say so in one line; never fabricate calendar or inbox content.

## HTML page (only when asked)
Render the same content with the `morning` skill's page design into `briefs/YYYY-MM-DD.html`. Markdown remains the durable copy.
