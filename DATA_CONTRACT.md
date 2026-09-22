# DATA CONTRACT

Contracts between stages. **[built]** = implemented today (extraction). Everything else is the agreed target;
each stage adds tables/fields, never changes an earlier stage's meaning. `contract_version` is semver:
additive = minor, breaking = major (a major bump requires a migration note in `CHANGELOG.md`).

## 0. Conventions

* Identifiers: `source_id` (stable id of a source file, preferably from config alias), `run_id`
  (`YYYYMMDDTHHMMSS-<4hex>`), `table_id` (source id + normalized sheet identity), and `column_id`
  (table id + normalized unique SQL column name). Schema fingerprints and positions are deliberately separate from identity,
  so adding/reordering columns does not rewrite the identities of unchanged columns. In AI-facing output these are shortened
  to handles (`t3`, `t3.c7`) with a legend.
* Trust labels on every derived fact: `detected | config | inferred | confirmed`, plus `method` and `score` (0-1).
* **Evidence object** `{run_id, source_id, sheet, table, xl_row, xl_col, rule_id, pack}`; fields not applicable are omitted.
* Severity: `info | warn | error`. An `error` finding blocks promotion only if the project config says so.
* Never store secrets; paths are stored as given in config plus `sha256` fingerprint.
* Excel error cells are NULL in data tables and listed in `_cell_errors`. Dates are ISO-8601 text. Nothing is coerced silently.

## 1. Stage `sources` [phase 1]  -> `sources.json` in the run folder

`[{source_id, path, kind: xlsx|xlsm|xlsb|xls|other, size, mtime, sha256, wrapper: none|drm|encrypted, exists, locked}]`

## 2. Stage `extract` -> `<source>.db` per workbook  [built unless marked]

| Table | Contract |
|---|---|
| one data table per extracted table | first column `_xl_row` INTEGER (Excel row); typed columns; NULL = empty or error cell |
| `_meta` [built] | key/value: schema_version, source_path/size/modified, extracted_at, tool, excel_restarts, verify_checks, verify_mismatches, total_seconds |
| `_extraction_log` [built] | per sheet: status (`extracted|skipped|error`), message, header_row, first/last row/col, data_rows, columns, blank_rows_skipped, error_cells, formula_cells, pivot_tables, filter_active, merged_areas, merged_in_data, read/write/total seconds |
| `_columns` [built] | table_name, position, sql_name, original_header, xl_col, xl_col_letter, sql_type, kind, date_format, non_null, error_cells |
| `_cell_errors`, `_sheet_preamble`, `_merged_areas` [built] | as named |
| `_verification` [built] | table_name, column_name, check_name (`counta|sum|cells_total`), excel_value, sqlite_value, ok (1/0/NULL), note |
| `_tables` extras [built] | `header_confidence` (0-1), `header_reasons` (plain-language list) -- computed from the chosen header row's own values, no COM cost beyond what extraction already reads |
| `_tables` regions [phase 2] | region, header_rows[] (multi-row/hierarchical), source (`detected|config`) -- one table per sheet remains the identity model until this phase |
| `_formulas` [built, per-column only] | table_name, sql_name, has_formula, sample_r1c1 (one sample per column; full run-length R1C1 patterns remain phase 3) |
| `_unsupported` [built] | scope (`workbook`\|`sheet`), sheet_name, kind (`power_query`\|`data_model`\|`external_link`\|`stale_calculation`\|`chart`), count, detail |
| `_pivots`, `_names` [phase 3] | pivot definitions, defined names (pivot *output* and formula *values* are already extracted; their definitions are not) |

Invariants (checked by `_verification`): stored cells == Excel `COUNTA` of the whole sheet; per-column non-null and
numeric sum equal Excel's; a failed sheet is recorded, never dropped. Exit codes: 0 ok, 1 file failed, 2 some sheets failed, 3 verification mismatch.

## 3. Later stages -> `catalog.db` per run  [phases 4-7]

| Table | Key fields |
|---|---|
| `_profile_columns` | column_id, n, nulls, distinct, min, max, mean, stddev, top_k (value,count), sample (<=5), date_min/max, pattern |
| `_dq_findings` | id, code (`DQ_*`), severity, column_id/table_id, count, examples (<=3), message, evidence |
| `_keys` | table_id, columns[], uniqueness (0-1), status inferred/confirmed |
| `_relationships` | from_column, to_column, kind (`inclusion|name`), containment (0-1), status, method, score, evidence |
| `_dictionary` | term, meaning, aliases[], unit, applies_to (column_id patterns), status, origin (`pack|config|auto`) |
| `_rule_results` | rule_id, pack, pack_version, status (`pass|fail|error|skipped`), expected, actual, tolerance, evidence |
| `_kpi_results` | kpi_id, value, unit, dims, definition_ref, evidence |
| `_changes` | kind (`schema|volume|value|row|category|distribution|kpi|source|baseline`), severity, subject, before, after, evidence |
| `_unsupported` [built] | source_id, table_id (NULL for workbook-scope findings), scope, sheet_name, kind, count, detail |
| `_formulas` [built] | column_id, table_id, has_formula, sample_r1c1 |
| `_table_kind` [built] | table_id, kind (`data\|notes\|report\|dashboard\|empty`), confidence, method, reasons -- always `inferred` |
| `_row_flags` [built] | table_id, xl_row, flag (`totals_candidate`), detail -- label-matched, never value-sum-matched |

## 4. Run manifest [phase 1] `manifest.json`

`{contract_version, run_id, project, started, finished, status: running|passed|failed|partial, promoted: bool,
inputs: [{source_id, sha256}], stages: [{name, status, seconds, artifacts[], warnings, error}]}`.
`data/current.json` = `{run_id}` of the last promoted run; written atomically after every required stage passes.

## 5. AI-facing contracts [phases 6-7]

Context pack JSON: `{contract_version, run_id, generated, budget_tokens, est_tokens, hash, sources[], schema_families[],
tables[], relationships[], definitions[], kpis[], rule_results, changes[], warnings[], omitted[{what, count, use_tool}]}`.
Markdown is rendered from the JSON, never authored separately.

Tool response envelope (all query tools):
`{ok, tool, columns[], rows[], row_count, total_rows|null, truncated, bytes, elapsed_ms, hint, evidence[], error?{code,message}}`.
Caps (config): rows 50, bytes 8192, timeout 5 s. `sql` accepts exactly one SELECT/WITH statement on a `mode=ro`
connection; anything else returns `error.code = "E_NOT_ALLOWED"`.

## 6. Error taxonomy (stable codes)

`E_SRC_MISSING E_SRC_LOCKED E_SRC_ENCRYPTED E_SRC_CORRUPT E_EXCEL_START E_EXCEL_DIED E_EXCEL_BLOCKED E_EXTENT
E_VERIFY_MISMATCH E_STAGE_INPUT E_CONFIG E_RULE E_BUDGET E_NOT_ALLOWED` — each has a one-line remedy in `AI_USAGE.md`.
