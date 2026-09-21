# xl2ai

Local, offline-first preparation layer between business Excel files and AI.

The core idea is simple:

```
Excel -> verified SQLite -> catalog/profile/quality -> keys & relations
      -> rules/KPIs -> run-to-run changes -> compact AI context + safe query tools
```

Excel remains the source of truth. AI never needs to open the raw workbook or ingest a 100 MB table.

## What works now

- Excel COM extraction on Windows with a private Excel process, read-only open, crash/dialog handling and verification.
- Incremental refresh: unchanged trusted sources are reused without reopening Excel.
- Run history, live-owner lock, promotion gate and retention. A failed refresh never replaces the last trusted run.
- Stable source/table/column catalog.
- Column profiling and generic quality findings.
- Candidate keys and conservative relationship inference.
- Human-confirmed keys/relations through project rule packs.
- Deterministic business rules, KPIs and dictionary terms.
- Schema, volume, value, category, KPI and row-multiset change detection.
- Compact token-budgeted AI context pack.
- Read-only capped query tools with row, byte and time limits plus SQLite authorizer protection.
- Trace from a returned row back to its Excel row.
- Fast status and optional deep SHA-256 source-integrity check.
- Human-readable project report and environment doctor.
- Installable package and `xl2ai` command.

## Install

Python 3.11+ is required. Extraction additionally requires Windows and Microsoft Excel.

```powershell
python -m pip install -e .
xl2ai --help
```

On Windows, the package installs `pywin32` automatically.

## Start a project

```powershell
xl2ai init "C:\Data\Orders.xlsx" "C:\Data\Customers.xlsx" --name "Sales" --with-pack
xl2ai doctor
xl2ai refresh
xl2ai report
```

A project normally contains:

```
xl2ai.toml
packs/
data/
  current.json
  runs/<run_id>/
```

## Daily use

```powershell
xl2ai status
xl2ai status --deep
xl2ai refresh
xl2ai report
xl2ai query schema
xl2ai query describe <table-id>
xl2ai query sample <table-id>
xl2ai query aggregate <table-id> amount --op sum --group-by department
xl2ai query compare
xl2ai query trace <table-id> 25
```

`status` is deliberately fast and checks file size + modified time. `status --deep` recomputes full SHA-256 when you need the stronger guarantee.

## Trust model

The platform keeps four ideas separate:

1. **Extracted**: what Excel actually returned.
2. **Detected/inferred**: structure, candidate keys and relationships found by generic logic.
3. **Confirmed**: knowledge explicitly declared by a human in a pack.
4. **Calculated**: rules and KPIs produced deterministically by SQL/code.

AI-facing output preserves those distinctions. It does not silently promote an inference into a business fact.

## AI use

Every trusted run can produce:

```
data/runs/<run_id>/ai/context_pack.md
data/runs/<run_id>/ai/context_pack.json
```

The context pack is small by design. When more evidence is needed, use the capped query tools rather than giving the model the raw database.

See `AI_USAGE.md`.

## Business knowledge

Generic code lives only in `xl2ai/`. Department/project knowledge lives in packs.

A pack can define:

- terms and meanings,
- confirmed keys,
- confirmed relationships,
- deterministic assertions,
- KPIs.

See `BUSINESS_RULES.md` and `EXTENDING.md`.

## Current known limits

The platform warns instead of pretending when workbook logic is not fully represented.

Still incomplete:

- several logical tables inside one worksheet,
- multi-row/complex headers with explicit region configuration,
- full formula dependency capture,
- pivot definition/source logic,
- Power Query / Data Model semantics,
- key-based row-level before/after values for confirmed keys,
- a graphical UI.

Current extraction does preserve the visible values and reports structural warning signals such as formulas, pivots and merged data cells.

## Safety guarantees

- source workbooks are opened read-only,
- writes happen inside a new run folder,
- promotion is atomic,
- the previous trusted run survives failure,
- raw SQL is read-only, capped and guarded by SQLite authorization,
- business rows are never copied into the context pack,
- row-diff fingerprints store hashes/counts, not row content.

## Tests

```powershell
python -m unittest discover -s tests
```

The CI matrix runs the COM-free platform tests on Windows and Linux with Python 3.11 and 3.12. Real Excel integration/golden tests are documented in `TESTING.md`.

## Documents

- `ARCHITECTURE.md` design rules and remaining architectural work.
- `DATA_CONTRACT.md` persisted contracts and evidence conventions.
- `EDGE_CASES.md` edge-case coverage.
- `TESTING.md` test strategy.
- `AI_USAGE.md` safe AI workflow.
- `BUSINESS_RULES.md` rule-pack format.
- `EXTENDING.md` how to add a new project/capability.
- `CHANGELOG.md` shipped changes.
