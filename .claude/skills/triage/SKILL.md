---
name: triage
description: Review what came out of recent meetings, mail and chat (the suggested tasks and steps on the Tasks page), let the user accept, move or dismiss each, and update people, project and glossary memory. Use when the user says "triage", "process my inbox", "what came out of my meetings", or invokes /triage.
---

# /triage

Read `CLAUDE.md` and `memory/context/soul.md`: a candidate is a claim by a named person, not a fact; keep who said it, and mark
single-source or transcript-only items as unverified.

Tasks (database table `tasks`, Tasks page; `assist/tasks.py`, DESIGN.md §3.3) is the one list the user works from: initiative →
task → step → action. Only what he made or accepted is on it. New promises and waits (a decision to take is a "Decide …" promise) the register (`loops`) finds in
mail, chat and meetings, and the assistant's own pass, arrive as *suggestions*: a new task, or a step for a task he has. `/triage`
is the user's review of those, plus the memory updates the extractor does not make. Never write tasks or decisions to `TASKS.md` or
`memory/decisions.md`: both are retired archives.

## 1. Bring the suggestions up to date
```
~/.assist/venv/bin/python -m assist.cli loops all     # extract new commitments, sync, close what evidence shows is done
~/.assist/venv/bin/python -m assist.cli tasks sync    # new register items become suggestions; steps closed by evidence close
```
Then read them: `curl -s localhost:8765/api/tasks` (`suggestions`; `tasks[].decide_or_drop` for the stale ones).

## 2. Present before changing anything
Show the user one compact list, each line ≤ 20 words with its source (meeting, mail or message), its initiative and age:
- *Suggested* (new tasks, and steps for tasks he has, naming the task)
- *Decide or drop* (accepted tasks with `decide_or_drop` set)
- *Questions for you* (unknown people or terms)

The user can say "take 1 and 4", "dismiss 2", "3 is a step of the budget task", "1 under Pricing", "done 5", "snooze 6 to Monday".
Apply with (PATCH takes field edits and a status together):
```
curl -s -X PATCH localhost:8765/api/tasks/<id> -H 'Content-Type: application/json' -d '{"status":"open"}'        # accept (or reopen)
curl -s -X PATCH localhost:8765/api/tasks/<id> -H 'Content-Type: application/json' -d '{"status":"dismissed"}'   # a suggestion he does not want
curl -s -X PATCH localhost:8765/api/tasks/<id> -H 'Content-Type: application/json' -d '{"parent_id": <task id>}' # make it a step of a task
curl -s -X PATCH localhost:8765/api/tasks/<id> -H 'Content-Type: application/json' -d '{"initiative_id": <id>}'  # file it
#   done | dropped | snoozed (+ "snooze_until") for accepted tasks and steps
```
Dismissals teach the next suggestion pass what not to propose. In an unattended run, change nothing; leave the list in
`inbox/questions.md`.

## 3. Memory the task list does not hold
For each meeting digest in `inbox/granola/` (except `latest.md` and `.state.json`), oldest first:

| Kind | Where it goes |
|---|---|
| Status change on an initiative | one dated bullet under *Timeline* in `memory/projects/<initiative>.md` |
| New fact about a person's role or what they own | *Owns* / *Recent interactions* in `memory/people/<name>.md` |
| Unknown term or person | ask the user once, then `memory/glossary.md` |

To record who was in a meeting, use an ingest bundle `meetings[].attendees` (format in `assist/ingest.py`) and run
`~/.assist/venv/bin/python -m assist.cli ingest`.

## Finish
Move processed digests to `inbox/processed/`. Report: n suggestions accepted, n dismissed, n moved or filed, n memory updates.
