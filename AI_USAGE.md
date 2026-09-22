# AI_USAGE

## The rule

Do not give the model the raw workbook or whole SQLite tables unless a human explicitly chooses to do that outside xl2ai.

Use the smallest evidence tier that answers the question.

## Tier 0: orientation

Read:

```
data/runs/<run_id>/ai/context_pack.md
```

It contains the run identity, sources, tables, relationships, confirmed definitions, KPIs, changes and important data-quality warnings, within the configured token budget.

## Tier 1: understand one table

```powershell
xl2ai query describe <table-id>
```

Use it to inspect column names/types, nulls, distinct counts, ranges, top values, samples and quality context.

## Tier 2: ask for small evidence

```powershell
xl2ai query sample <table-id>
xl2ai query aggregate <table-id> amount --op sum --group-by department
xl2ai query compare --kind row
xl2ai query meta relationships
xl2ai query meta quality
xl2ai query meta definitions
xl2ai query trace <table-id> 25
```

Every response is bounded by configured row/byte limits.

## Tier 3: read-only SQL

```powershell
xl2ai query sql <source-id> "SELECT ..."
```

Only a single SELECT/WITH statement is accepted. SQLite is opened read-only, `query_only` is enabled, an authorizer rejects writes/schema/attach/pragma operations, and a timeout is enforced.

## Evidence discipline

A good AI answer should distinguish:

- confirmed business definitions,
- inferred keys/relationships,
- deterministic KPI/rule results,
- raw sampled evidence.

When a definition is missing, the correct answer is “definition not confirmed yet”, not an invented interpretation.

## Token discipline

Increase `[ai].context_tokens` only when the context pack itself genuinely needs more schema/meaning. For detailed data questions, keep the pack small and query targeted slices instead.
