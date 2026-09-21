# CHANGELOG

Output-affecting changes are listed explicitly; the golden fingerprints (`tests/golden/fingerprints.json`) are
regenerated only together with an entry here.

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
