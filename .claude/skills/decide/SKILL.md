---
name: decide
description: Pull everything said about a topic across meetings, lay out options and a recommendation, and record the call on its task. Use when the user says "help me decide", "what are my options on", "what have we said about", or invokes /decide <topic>.
argument-hint: "<topic>"
---

# /decide

1. Search `../Granola Export/transcripts/` titles and AI summaries for the topic (and its glossary synonyms). Read summaries first; open transcript segments only for the two or three most relevant meetings.
2. Read prior positions from the tasks on the topic (`curl -s localhost:8765/api/tasks`: decide steps and their notes) and open items (`curl -s localhost:8765/api/loops`), and `memory/projects/`, `memory/context/soul.md` and `memory/context/cpo-soul.md`. Use the CPO soul's questions for the options: say whether it is a one-way or two-way door, give its money story, and name what stops if the user says yes. In "What has been said", attribute every point, note each speaker's likely stake, flag figures that rest only on a Granola summary, and mark the recommendation's key facts confirmed / likely / unverified.
3. Write `drafts/decision-YYYY-MM-DD-<slug>.md`:

```
# Decision · <topic>
## What has been said (chronological, with who and source)
## Options
| Option | For | Against | Who favours it |
## Recommendation
One paragraph: the option, why, what would change the answer.
## What it takes to decide
Who needs to be in the room, what information is missing, by when.
```
4. Ask the user for the call. Decisions are not logged on their own any more (retired 26 Oct 2026): what the user decides lives on
   the task it belongs to. When he takes it, he ticks the decide step in Tasks (or closes its open item:
   `curl -s -X PATCH localhost:8765/api/loops/<id> -H 'Content-Type: application/json' -d '{"status":"done","note":"<the call, one line>"}'`).
   If there is no task for it, suggest one with a decide step; never write a `decisions` bundle section (ingest drops it)
   or `memory/decisions.md` (retired).

## Refresh the UI
If you wrote a document, add it to the database with an ingest bundle (`documents` section, see `assist/ingest.py`) and run `~/.assist/venv/bin/python -m assist.cli ingest`.
