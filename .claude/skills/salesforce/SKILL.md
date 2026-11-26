---
name: salesforce
description: Pull Acme open pipeline and closed deals since Q1 2026 (company and deal data only) from Salesforce through the Acme Account Intelligence connector into the Assist database. Runs as part of the morning full refresh; also use when the user says "pull Salesforce", "refresh the pipeline", or invokes /salesforce.
---

# /salesforce

Open opportunities for the user's private assistant database. READ ONLY: never create or change anything in Salesforce.
Policy (org instructions): company and deal data only. Never show, store or summarise owner names, contacts, the MEDDICC
person fields (Champion, Economic Buyer) or free-text fields (Description, Next Steps, Mgmt comments). `assist.cli
ingest` enforces this with an allowlist (`assist/ingest.py` SF_FIELDS); do not work around it.

## 1. Pull
Load the tool: ToolSearch `select:mcp__claude_ai_Acme_Account_Intelligence__sf_get_open_opportunities`.
The tool returns at most 500 rows and has no offset, and Salesforce holds thousands of stale "open" deals from
2005–2011, so pull opportunities created since 2024-01-01 in created-date windows. Call it once per window with
`detail_level: "summary"`, `limit: 500`, `created_date_from` / `created_date_to`:

| from | to |
|---|---|
| 2024-01-01 | 2024-12-31 |
| 2025-01-01 | 2025-06-30 |
| 2025-07-01 | 2025-12-31 |
| 2026-01-01 | 2026-06-30 |
| 2026-07-01 | today |

From 2027-01-01 add half-year windows in the same pattern. Never use `detailed`, `full` or `include_meddicc`.

### 1b. Closed deals (Closed Won / Closed Lost since 2026-01-01)
Load `mcp__claude_ai_Acme_Account_Intelligence__sf_search_opportunities`. It returns at most 100 rows and has no
offset, so call it per quarter of close date, once with `stage_name: "Closed Won"` and once with `"Closed Lost"`:
`close_date_from` / `close_date_to` = each calendar quarter from 2026-01-01 to today (the current quarter ends today),
`limit: 100`, `detail_level: "summary"`. If a result's `totalSize` is 100 or more, split that quarter into months.
Past quarters rarely change: after the first full pull, the current and previous quarter are enough each morning
(older closed deals stay in the database).

### 1c. Account facts (Mondays, or when the user asks for logos or partner types)
Company fields only, for People › Companies: each account's Type (a Partner account is listed as a partner) and its
website and mail domain (its logo is looked up by them). Load `mcp__claude_ai_Acme_Account_Intelligence__sf_list_accounts_by_type`
and call it four times with `detail_level: "detailed"` (the only level with the website; the bundler keeps nothing else) and
`limit: 500`: `account_type` "Partner", "Customer", "Former Customer", "Prospect". Save each result as in step 2, never
read it, and bundle it with `sf-accounts` (step 3). The results hold owner names, phones and addresses: delete them after.

## 2. Save each result
Results are large, so the harness usually saves them to a `tool-results/…txt` file and returns its path: use that
path. If a result comes back inline, Write it unchanged to `inbox/salesforce-raw/<from>.json`. Do not read the
records yourself, and do not summarise or quote them.

## 3. Bundle, ingest, clean up
```
~/.assist/venv/bin/python -m assist.cli sf-bundle <file1> <file2> ...
~/.assist/venv/bin/python -m assist.cli ingest inbox/queue/salesforce-<today>.json
```
If `sf-bundle` prints INCOMPLETE for a window, split that window in two, pull again, and rerun with all files.
Closed-deal results go through their own bundler (never mix them into `sf-bundle`, which would treat them as open):
```
~/.assist/venv/bin/python -m assist.cli sf-closed <closed-file1> <closed-file2> ...
~/.assist/venv/bin/python -m assist.cli ingest inbox/queue/salesforce-closed-<today>.json
```
An inline result: Write it to `inbox/salesforce-raw/closed-<from>-<stage>.json` unchanged.
Account lists (step 1c, Mondays) go through theirs, which keeps only name, Type, website and mail domain:
```
~/.assist/venv/bin/python -m assist.cli sf-accounts <account-file1> <account-file2> ...
~/.assist/venv/bin/python -m assist.cli ingest inbox/queue/salesforce-accounts-<today>.json
```
Then delete `inbox/salesforce-raw/` (`rm -rf inbox/salesforce-raw`): it still holds owner names. The tool-results
files are deleted by the server after a refresh (`purge_tool_copies`); when you run this by hand, delete those too.

## 4. Report
One line: open opportunities stored, how many are no longer open, closed won / lost since Q1 2026, accounts updated
(Mondays), and whether the pull was complete. Closed deals are shown on the Pipeline page's Closed deals tab (`/api/pipeline/closed`). Pipeline figures
for the brief come from the database (`items` where `source_id='salesforce'`, open ones have `payload.is_open = true`),
by account, stage, region and use case. No person names.
