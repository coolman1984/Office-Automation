# EXTENDING

## New workbook/project

Prefer configuration and packs before changing platform code.

1. Run `xl2ai init ... --with-pack`.
2. Run `xl2ai doctor`.
3. Run the first `xl2ai refresh`.
4. Inspect `xl2ai report` and `xl2ai query schema`.
5. Confirm important keys/relationships and business terms in the pack.
6. Add rules/KPIs only after their definitions are agreed.
7. Refresh again and inspect changes.

## Add a generic platform capability

A feature belongs in `xl2ai/` only when it is workbook/domain independent.

Requirements:

- deterministic behavior where possible,
- provenance/evidence for derived outputs,
- explicit inferred vs confirmed status,
- bounded AI-facing output,
- a unit test and a failing/edge case,
- no project/company-specific vocabulary inside the platform.

## Add a new command

Register it in `xl2ai/cli.py`, keep imports lazy, add command help and tests, then include it in the CI regression set if it has a dedicated test module.

## Add a new catalog field/table

Prefer additive schema changes. Update:

- `xl2ai/catalog.py`,
- `DATA_CONTRACT.md`,
- context/query/report consumers where relevant,
- tests that prove both writing and reading the new contract.

Per-run catalogs are rebuilt, so migrations are mainly needed only when older runs must be read by a newer command.

## Change extraction output

Extraction is the highest-risk boundary. Any intentional output change should be documented in `CHANGELOG.md` and validated against the real Excel/golden suite before release.
