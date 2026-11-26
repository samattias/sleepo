---
name: docs-read
description: Read recent SharePoint/OneDrive documents in full through the Microsoft 365 connector and write document cards for them, so Assist knows what they are about. Runs as part of the morning full refresh; also use when the user says "read my SharePoint documents" or invokes /docs-read.
---

# /docs-read

READ ONLY: never change, move, share or delete anything in SharePoint or OneDrive.

1. List what to read: `~/.assist/venv/bin/python -m assist.cli sp-read-list --limit 15`
   It prints recent files (last 30 days) whose full text Assist does not have yet: `item_id`, `name`, `uri`.
2. For each file: load `mcp__claude_ai_Microsoft_365__read_resource` (ToolSearch) and call it with the `uri` and
   `startPage: 1`, `endPage: 6` (the first six pages or slides are enough for a card). Keep the text exactly as returned;
   do not summarise or translate it. If a file cannot be read, skip it.
3. Write all results to `inbox/docs-raw/<today>.json` as `[{"item_id": 123, "text": "…"}]` (text capped at 12 000
   characters each). If a result was saved to a tool-results file, read that file to get the text.
4. Store and summarise:
   ```
   ~/.assist/venv/bin/python -m assist.cli sp-text inbox/docs-raw/<today>.json
   ~/.assist/venv/bin/python -m assist.cli doc-cards
   ```
5. Delete `inbox/docs-raw/` (`rm -rf inbox/docs-raw`): it holds document text outside the database. The tool-results
   files are deleted by the server after a refresh (`purge_tool_copies`); when you run this by hand, delete those too.
6. Report one line: files read, cards written, files skipped.
