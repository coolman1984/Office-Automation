# CHANGELOG

## 0.3.0 - AI-ready platform completion/hardening (2026-09-21)

* Added run catalog with stable source/table/column identities.
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
