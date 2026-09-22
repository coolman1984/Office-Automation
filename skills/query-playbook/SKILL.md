---
name: query-playbook
description: Question-to-tool map for xl2ai's read-only query layer, and when to stop reading.
---

# query-playbook

Every tool here returns the same bounded envelope: `{ok, tool, columns, rows, row_count, total_rows, truncated,
bytes, elapsed_ms, hint, evidence, error?}`. `truncated=true` means there is more — refine the question with a
filter/group-by instead of assuming you saw everything.

## Question -> tool

| You need to know | Run | Notes |
|---|---|---|
| "What's here at all?" | `xl2ai brief` | always first; see `skills/agent-start` |
| "What tables/columns exist?" | `xl2ai query schema` | lists every table with its columns; no row data |
| "Tell me about this one table" | `xl2ai query describe <table>` | types, nulls, distinct, min/max, top-k, samples, quality/key counts |
| "Show me some real rows" | `xl2ai query sample <table> [--limit N]` | capped; never the whole table |
| "Sum/count/avg by group" | `xl2ai query aggregate <table> <column> --op sum\|avg\|count\|min\|max [--group-by col]` | deterministic SQL, not an LLM guess |
| "How are tables related?" | `xl2ai query meta relationships` | inclusion/name-based, each with `status` (inferred/confirmed) and `score` |
| "What does this term/column mean?" | `xl2ai query meta definitions` | only pack-confirmed or auto-drafted meanings; missing = not yet defined |
| "What are the KPIs?" | `xl2ai query meta kpis` | values computed by deterministic pack SQL, never by the model |
| "Did any business rule fail?" | `xl2ai query meta rules` | `status`, `severity`, `message` per rule |
| "What quality problems exist?" | `xl2ai query meta quality` | `DQ_*` codes with severity, subject, message |
| "Which keys are trustworthy?" | `xl2ai query meta keys` | `status=confirmed` (human-declared) vs `inferred` (score attached) |
| "What couldn't the platform read?" | `xl2ai query meta unsupported` | Power Query, Data Model, external links, stale-calculation, unread charts -- also summarized in `brief`'s `gaps` |
| "Is this sheet actually a data table?" | `xl2ai query meta table_kind` | `data\|notes\|report\|dashboard\|empty`, always `inferred` with reasons -- a `report`/`dashboard` sheet may not aggregate the way a plain data table would |
| "Are there totals rows mixed into the data?" | `xl2ai query meta row_flags` | `_xl_row`-level flags (`totals_candidate`); exclude these rows explicitly before summing a column |
| "What does this column actually mean?" | `xl2ai query meta column_roles` | `identifier\|date\|money\|quantity\|percentage\|category\|code\|boolean\|free_text\|geo\|contact`, with unit/currency where detected -- always `inferred`, never treat as a confirmed definition |
| "What does one row of this table represent?" | `xl2ai query meta grain` | if `status=unknown`, say so and do not aggregate as if a row's meaning were settled |
| "What date range does this table cover?" | `xl2ai query meta time_coverage` | min/max per date column |
| "Is this the same data as another file?" | `xl2ai query meta duplicates` | schema + row-hash-overlap based; a high score means "likely a copy", not proof |
| "Are there messy values worth cleaning up?" | `xl2ai query meta repairs` / `xl2ai query repaired <table>` | null markers, inconsistent category spelling, text-as-number -- suggestions only, empty unless `[repair].enabled=true`, never applied to the actual data |
| "What changed since last time?" | `xl2ai query compare [--kind schema\|volume\|value\|row\|category\|distribution\|kpi]` | already computed; do not recompute by diffing samples yourself |
| "Where did this row/value come from?" | `xl2ai query trace <table> <xl_row>` | returns the exact Excel row; use this before asserting provenance |
| "Something not covered above" | `xl2ai query sql <source_id> "SELECT ..."` | single SELECT/WITH only, read-only, capped, authorizer-enforced |

## When to stop

Stop as soon as the question is answered. Concretely:

1. `brief` answers "is this safe to use and where do I go" — most sessions need nothing else to get oriented.
2. `context_pack.md` answers "what exists and roughly what does it mean" for the whole project in one read.
3. `describe` answers almost everything about one table without touching row data.
4. Only reach for `sample`/`aggregate`/`sql` when you need an actual number or actual rows as evidence.

Never chain `sql` calls to reconstruct something `describe`, `meta`, or `compare` already computed deterministically
— that recomputation is exactly the token/hallucination cost this platform exists to remove.

## Trust discipline while answering

- State whether a fact is confirmed, inferred, calculated, or raw sample — do not flatten the distinction into a
  single confident sentence.
- If `query meta quality` or `brief`'s `gaps`/`blind_spots` flag the table you are using, mention the flag in your
  answer, even briefly. A caveat the user never sees is the same as not knowing it.
- Cite `evidence` (run id, table, `_xl_row`) for any number you state as fact.
