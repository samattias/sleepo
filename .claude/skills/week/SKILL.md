---
name: week
description: Weekly strategy review for the user. Use on Mondays or when the user asks "how did the week go", "weekly review", "where is my time going", or invokes /week. Writes briefs/<year>-W<week>-review.md.
---

# /week

Read `CLAUDE.md`, `memory/context/strategy.md`, `memory/context/soul.md`, `memory/context/cpo-soul.md` (the standard for the role: where the week shows one of its failure modes, such as most hours on work a direct report could own, a date given outside without engineering's sign-off or no direct customer contact, say so once, plainly, with the evidence), the open-items register (`curl -s 'http://localhost:8765/api/loops?closed_days=7'`: promises, waits, replies and decisions, open and closed this week, with ages and sources), and the last 7 days of transcripts' frontmatter and summaries in `../Granola Export/transcripts/` (summaries only). `TASKS.md` and `memory/decisions.md` are retired archives: do not read them as current.

## First: initiative updates
Run `~/.assist/venv/bin/python -m assist.cli ini-updates` so every initiative has this week's five-line update drafted for the user to approve
on its page (Initiatives in the app). Use those drafts and the initiative pages (`GET http://localhost:8765/api/initiatives` and
`/api/initiatives/<slug>`: timeline, people; and `GET /api/tasks` for the tasks under each, their steps and who owns them) as the main input for sections 1, 2 and 3 below; link each initiative's page
(`#/initiatives/<slug>`). Do not approve updates yourself.

## Produce `briefs/YYYY-Www-review.md`
1. **Where the week went** — a table: initiative · meetings · approx hours (from meeting_start/end when present, else count) · share. Flag any top-weight initiative with no time against it.
2. **Movement by initiative** — one line each: what moved, what didn't, who is on the critical path. Source links.
3. **Decisions** — decide steps and tasks of kind `decide` the user closed in the last 7 days (Tasks); open ones and ageing; the one the user should take next week and the recommended option.
4. **Tasks and commitments** — from Tasks: accepted, closed this week (and how: by the user, or from evidence), steps others owe the user, tasks flagged decide-or-drop, and suggestions left unanswered; from the register, promises made this week that never became a task.
5. **People** — direct reports or key partners the user has not spoken with in 2+ weeks.
6. **Next week** — three suggested focus items, each tied to a method or goal in the user's plan (the profile's plan document), and one thing to stop or delegate.

Keep it under a page. If the user asks to share it, publish as a private artifact; never include people/performance detail in a shared version.

## Refresh the UI
If you wrote a document, add it to the database with an ingest bundle (`documents` section, see `assist/ingest.py`) and run `~/.assist/venv/bin/python -m assist.cli ingest`.
