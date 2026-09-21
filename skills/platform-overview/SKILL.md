---
name: platform-overview
description: Start here. What xl2ai is, what tools exist today, and the rules every agent must follow when working with Excel-derived data.
---

# xl2ai overview

xl2ai turns Excel workbooks into verified SQLite databases so you never read raw Excel or dump big tables.
Code does extraction, checks and calculations; you read small outputs and query small slices.

## Tools available now
| Tool | Use it when | Skill |
|---|---|---|
| `python -m xl2ai extract <file\|folder> [-o OUT]` | a workbook is new or changed and you need it as SQLite | `extract-workbook` |

Later stages (quality, profile, relations, dictionary, rules, diff, pack, query) are planned; if a command is not
listed by `python -m xl2ai --help`, it does not exist yet. Do not invent it.

## Rules (all agents)
1. Never open a workbook in any other way to read its data (no openpyxl/pandas on the source). Sources may be DRM-wrapped; only `extract` handles that.
2. Never print or load a whole table. Ask for counts, aggregates, or a small slice with a `LIMIT`.
3. Read the extraction database's `_extraction_log` and `_verification` before trusting any table.
4. Anything not `verified` or marked `inferred` is a hypothesis; say so.
5. Cite where a number came from: database, table, `_xl_row`, run time (`_meta.extracted_at`).
6. Use PowerShell on this machine, never bash.

## Minimum-token habit
Answer from `_extraction_log` (sheet list, row counts, warnings) first, then `_columns` for one table, then a
`SELECT ... LIMIT 20`. Stop as soon as the question is answered.
