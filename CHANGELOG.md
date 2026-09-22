# CHANGELOG

## 0.7.0 - Agent readiness, phase 3: structural truth (2026-09-22)

**Extraction database schema change**: `_extraction_log` gained `header_confidence`/`header_reasons` columns.
Golden fingerprints (`tests/golden/fingerprints.json`) must be regenerated with `python tests/regen_golden.py` on
a Windows machine with Excel before this change is considered fully validated -- that could not be run in this
environment (no Excel/COM available here). `test_golden.py` will fail on a real Windows+Excel run until then;
it is currently skipped wherever pywin32 is unavailable, so this was not caught by this environment's test run.

* Added header-detection confidence scoring (`xl2ai/extract/layout.py:header_confidence`): a score in [0,1] plus
  plain-language reasons (columns filled, text ratio, repeated/grouped labels, whether data follows), computed as
  a pure function of already-read cell values so it is unit-testable without Excel. Carried through
  `_extraction_log` into the catalog's `_tables.header_confidence`/`header_reasons`.
* Added totals/subtotal-row detection (`_row_flags`, flag `totals_candidate`): rows whose text column reads as a
  totals label ("Total", "Grand Total", "Subtotal", "إجمالي", "المجموع", ...) are flagged by `_xl_row`, with a new
  `DQ_TOTALS_ROW_IN_DATA` quality finding -- a default aggregate over such a table would otherwise double-count them.
* Added table-kind classification (`_table_kind`): `data | notes | report | dashboard | empty`, a small explicit
  rule set over signals already computed (row/column count, header presence, formula density, pivot presence,
  totals rows), always `inferred` with a method and reasons, never presented as confirmed.
* `xl2ai query meta table_kind` / `row_flags` expose both directly. The context pack's `tables[]` entries gained
  `kind`. `xl2ai brief` downgrades a table with an unresolved totals row from `ready` to `needs_review` and lists
  it under `gaps`.
* Documented (`EDGE_CASES.md`) that full region detection (several tables per sheet), multi-row/hierarchical
  headers and transposed-table reconstruction remain out of scope for this phase -- they change the extraction
  identity model itself and need validation against real, messy workbooks on Windows+Excel, which this
  environment cannot provide. See `AGENT_READINESS_PLAN.md` phase 3 for the reasoning and what remains.

## 0.6.0 - Agent readiness, phase 2: honest gaps (2026-09-22)

**Extraction database schema change**: new `_unsupported` and `_formulas` tables in both the per-workbook
extraction database and the run catalog. Golden fingerprints must be regenerated with `python tests/regen_golden.py`
on a Windows machine with Excel before this change is fully validated -- see the note on this in 0.7.0 below,
which applies equally here; both phases landed in the same session with no Excel/COM environment available.

* Added detection of content this platform cannot fully read, so a run reports it instead of silently treating
  the workbook as fully understood: Power Query steps, the Excel Data Model, external workbook links (workbook
  scope), and charts (sheet scope), each with a plain-language explanation of what is not captured. New
  `_unsupported` table in both the per-workbook extraction database and the run catalog.
* Added stale-calculation detection: if Excel reports pending recalculation immediately on opening a workbook
  (before this tool's own manual-calculation setting could mask it), that is recorded as a blind spot -- any
  formula-derived value in that workbook may not reflect its latest inputs.
* Added per-column formula detection (`_formulas`): a column backed by at least one formula is now distinguishable
  from one that was typed in, with a sample R1C1 formula for context.
* The AI context pack gained a `blind_spots` section (JSON and Markdown), populated from `_unsupported`, so an
  agent reading only the compact pack still sees what could not be fully read -- not just what could.
* Added `xl2ai query meta unsupported` to inspect the full list without opening the workbook.
* `xl2ai brief`'s per-table readiness now downgrades a table with an unresolved blind spot from `ready` to
  `needs_review`, and lists each one under `gaps`.

## 0.5.0 - Agent readiness, phase 1: a truthful entry point (2026-09-22)

* Added `xl2ai brief`: one bounded call that orients a cold agent — current run, freshness, a per-table readiness
  verdict (`ready`/`needs_review`/`not_ready`) derived from verification and quality findings, an explicit `gaps`
  list, and ordered `next_commands`. Exit codes: 0 ready, 1 needs review, 2 not ready.
* Rewrote `skills/platform-overview/SKILL.md`: it previously told agents that every stage after `extract` was
  still "planned" and to "not invent" commands that had in fact shipped long ago — any agent obeying it would
  bypass the whole platform and read Excel directly. It now lists every shipped command and states the platform's
  actual purpose (pre-digest workbooks once so later agents never re-derive that understanding from raw Excel).
* Added `skills/agent-start/SKILL.md`: the concrete first command a cold agent runs, and how to read `brief`'s
  exit code and `gaps` before proceeding.
* Added `skills/query-playbook/SKILL.md`: a question -> tool map for the query layer, with an explicit "stop
  reading here" rule per tool and the trust-discipline reminders (cite evidence, never flatten inferred into
  confirmed, never silently drop a flagged gap from an answer).

See `AGENT_READINESS_PLAN.md` for the full six-phase plan this starts.

## 0.4.0 - Observability: live run view and failure diagnosis (2026-09-22)

* Added `xl2ai watch`: refreshes with a live, step-by-step terminal view built on a new dependency-free `xl2ai/ui/`
  toolkit (capability detection, colour/glyph fallbacks, display-width-aware tables/panels/trees/bars/spinners,
  flicker-free live region). `--demo` simulates a run so the interface is visible and testable without Excel.
* Added `xl2ai diagnose`: explains a finished run from its event journal, surfacing the first real failure (not its
  downstream symptoms) and the events around it; `--ai` prints that as plain text to paste into an AI assistant.
* Added `xl2ai/observe/`: an event vocabulary, a bus whose subscribers can never break the pipeline, and a JSON
  Lines journal (`data/runs/<run_id>/journal.jsonl`) written by every run and readable even after a killed process.
* Fixed extraction on non-Windows machines failing with an unrelated `AttributeError` instead of reporting plainly
  that Excel and pywin32 are required.
* Fixed rules/KPIs sharing one SQL deadline per pack, letting an earlier slow rule starve or fail later fast ones
  and abort the whole run; each rule/KPI now gets its own deadline and KPI failures are caught and surfaced rather
  than aborting the stage.
* Fixed a lock-acquisition crash when another process's lock file is mid-write, and a `pid_alive()` case where
  "permission denied" was treated as "process is dead" (could let two refreshes hold the lock at once).
* Fixed uncaught tracebacks from SQLite errors in query `aggregate`/`trace`/`sample`, now returned as the documented
  `{ok:false, error}` envelope; `sample()` no longer returns one row more than `--limit`.
* Fixed context-pack building being O(n^2) (300 tables: 5.7s -> 0.04s) by tracking token cost incrementally.
* Fixed row fingerprinting detecting the Excel row-position column by value-type guessing, which could silently
  strip a real integer business column; it is now detected by name (`_xl_row`).
* Fixed relation inference always running before rule-pack keys/relationships were applied, and never using
  confirmed keys as parent candidates; rules now run first, and inference preserves confirmed relationships while
  treating confirmed keys as fully trusted.
* Fixed source-freshness comparison using a local-time string, which could make every source look modified across a
  timezone/DST change; now compared as UTC mtime.
* 36 new tests; full suite 167 pass (138 run by default, 29 skipped without Windows/Excel).

## 0.3.0 - AI-ready platform completion/hardening (2026-09-21)

* Added run catalog with source/sheet/name-based stable identities; schema/type/position drift is tracked separately.
* Added profiling, generic data-quality findings, candidate keys and conservative relationship inference.
* Added TOML rule packs with confirmed terms, keys, relationships, deterministic rules and KPIs.
* Added run-to-run source/schema/volume/value/category/distribution/KPI and exact row-multiset change detection.
* Added compact token-budgeted AI context pack and capped schema/describe/sample/aggregate/compare/trace/SQL tools.
* Added SQLite read-only authorizer protection for AI/rule SQL.
* Added project init, doctor, report and deep SHA-256 status verification.
* Fixed Windows file-handle leaks by explicitly closing read-only SQLite connections.
* Added installable package metadata and the `xl2ai` console command.
* Added Windows/Linux Python 3.11/3.12 CI plus a COM-free cross-stage smoke test.

Output-affecting changes are listed explicitly; the golden fingerprints (`tests/golden/fingerprints.json`) are
regenerated only together with an entry here.

## 0.2.0 - Incremental refresh (2026-09-21)

* `xl2ai refresh` now skips Excel entirely for a source when the previous promoted run passed and the source path,
  SHA-256, size, mtime and extraction-affecting settings are all unchanged.
* Source fingerprinting now uses full SHA-256 by default, including files above 256 MB; the former first/last-chunk
  shortcut remains available only as explicit opt-in and is never used by normal refresh caching.
* Reused databases are materialized inside the new run (NTFS hard link when possible, copy fallback), so retention can
  safely remove old runs without breaking the current dataset.
* Reuse is recorded per source in the manifest with `reused`, `reused_from_run` and `reuse_mode`.
* `xl2ai refresh --force` bypasses reuse and re-extracts every source.
* Added COM-free regression tests proving unchanged reuse, changed-input invalidation, extraction-config invalidation,
  retention-policy independence and self-contained reused artifacts.

## 0.1.0 - Phase 0: package split (2026-09-21)

* `excel_to_sqlite.py` (1,140 lines) split into `xl2ai/extract/` (`common com names dates coltypes layout store sheet verify
  sources pipeline`). `python -m xl2ai extract ...` added; `python excel_to_sqlite.py ...` kept as a shim.
  **Output unchanged**: 4 regression databases (2 synthetic, 2 specimen) byte-identical to the monolith.
* New tests: golden fingerprints, structure (every global name resolves; platform has no specimen words; platform
  never imports packs; CLI/shim entry points), leak checks by exact Excel PID (the tool now logs `Excel started (pid N)`).
* Fixed `xl2ai/__main__.py` running `main()` at import time. Fixture builder now waits for its Excel to exit.
* Environment knowledge (DRM file prefix) isolated in `sources.WRAPPER_PREFIXES`.
* Documentation: README, ARCHITECTURE, DATA_CONTRACT, EDGE_CASES, TESTING; `skills/` for the extract stage.

## Extractor history before the package (same code, earlier state)

* Excel COM extraction with private instance, watchdog, crash restart/retry, dialog detection (password prompt).
* True extent via `Find`; filters cleared in the in-memory copy because `Find` skips filtered rows (a real
  data-loss bug found on the specimen: 92% of one sheet was missing before the fix).
* Header detection with preamble kept; whole-column typing; Excel error cells recorded; dates incl. 1904 and the 1900 leap-year bug.
* Verification against Excel itself, including a whole-sheet `COUNTA` that is independent of the chosen extent.
* Atomic `.partial` database; a failed run keeps the previous database.
