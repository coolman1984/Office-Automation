# xl2ai

A local, offline "data preparation operating system for AI": unfamiliar business Excel files go in, a safe, verified,
traceable SQLite dataset comes out, and (in later phases) a tiny AI Context Pack plus capped query tools so an AI
never reads raw Excel or huge tables. Nothing here is specific to any one workbook; project knowledge lives in rule packs.

## What works today (extraction + safe refresh lifecycle)

```powershell
python -m xl2ai extract "path\to\file.xlsx"            # one workbook -> <name>.db beside it
python -m xl2ai extract "folder" -o out                # every workbook in a folder -> out\<name>.db
python -m xl2ai extract file.xlsb --no-verify --sheet "Sheet 1"
python -m xl2ai refresh                                # process configured sources; reuse exact unchanged inputs
python -m xl2ai status                                 # current trusted run + freshness
python -m xl2ai refresh --force                        # deliberately re-extract everything
```

`refresh` fingerprints every source and records extraction-affecting settings. If a source is exactly unchanged
(path, hash, size, mtime, settings) and the previous promoted run fully passed, its trusted database is materialized
into the new run with a hard link when possible (copy fallback) and Excel is not started for that source. Any doubt
falls back to a normal extraction. Recurring refreshes therefore scale with what actually changed.

Requires Windows, Excel, and `pip install pywin32`. It opens files read-only in a private Excel (works on DRM-wrapped
files that no zip parser can read), survives Excel crashes, password prompts and phantom ranges, never modifies the source,
never replaces the previous database on failure, and verifies the result against Excel itself.
Exit codes: 0 ok, 1 file failed, 2 some sheets failed, 3 verification mismatch.
Old entry point `python excel_to_sqlite.py ...` still works.

## Roadmap

`extract` + safe/incremental `refresh` (built) -> quality -> profile -> relations -> dictionary -> rules/KPIs ->
change detection -> AI context pack -> safe query tools. Phases and gates: `ARCHITECTURE.md` section 6.

## Documents

| File | Purpose | Status |
|---|---|---|
| `ARCHITECTURE.md` | principles, review, module structure, token strategy, roadmap | written |
| `DATA_CONTRACT.md` | what each stage reads/writes, ids, evidence, error codes | written (extract built, rest target) |
| `EDGE_CASES.md` | test matrix with honest coverage status | written |
| `TESTING.md` | how to run, rules for tests | written |
| `CHANGELOG.md` | what changed, incl. output-affecting changes | written |
| `skills/` | instructions for AI agents, one folder per tool | extract stage only |
| `AI_USAGE.md`, `EXTENDING.md`, `BUSINESS_RULES.md` | written when the features they describe exist (phases 5-7) | planned |

## Layout

`xl2ai/` generic platform (no domain words; enforced by a test) | `tests/` unit, integration, golden, structure |
`skills/` agent instructions | `Price Comparison Data/` and `output/` a demanding specimen and its output (not the spec) |
`extract_excel.py`, `test_output/` a superseded first draft (contains a known truncation bug; safe to delete).
