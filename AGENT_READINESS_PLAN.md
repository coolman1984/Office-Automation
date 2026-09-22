# AGENT READINESS PLAN

How xl2ai becomes the only thing an AI agent ever needs to touch when the real data lives in large, messy Excel
workbooks — so the expensive work of *understanding* those workbooks happens once, deterministically, and every
later agent inherits it for a few hundred tokens instead of re-deriving it (badly) for tens of thousands.

This plan is written from one point of view: **a new agent walking in cold**. Every phase below exists because
that agent would otherwise have to open Excel, guess, or spend tokens re-discovering something code already knows.

Status legend: **[built]** exists and is tested · **[partial]** exists but incomplete · **[missing]** not built.

---

## 1. The contract this plan commits to

An agent starting a project on this company's data must be able to answer all of the following **without opening a
single workbook** and **without inventing anything**:

1. What files exist, which matter, which are stale, which are duplicates.
2. What is inside each file, and which sheets are real data versus reports, notes, or settings.
3. Where each table actually starts and ends, what its headers are, and whether one sheet holds several tables.
4. What each column *means* — not just `REAL`, but "unit price, EGP, per line item".
5. What one row represents (the table's **grain**) — the single most important fact for any correct aggregation.
6. Which rows are traps: totals, subtotals, notes, blank separators.
7. How tables relate to each other, and which relationships are confirmed versus guessed.
8. What the tool could **not** read, stated explicitly.
9. How much to trust every one of the above.
10. Where any number came from, down to the Excel cell.

Anything on that list the layer cannot answer is a token bill (and a hallucination risk) transferred to every
future agent. That is the measure of success for this plan — not feature count.

---

## 2. The cold agent's journey, and where it breaks today

Each step is what a competent agent would do. `Gap` is what forces it to open Excel, guess, or burn tokens.

| # | Agent's question | Available today | Gap |
|---|---|---|---|
| 1 | "What am I looking at?" | `skills/` folder is the documented entry point | **[missing]** `skills/platform-overview` still says stages after `extract` are "planned … do not invent it". Every stage it names as missing has shipped. An agent that obeys this skill will bypass the whole platform and read Excel itself. **This single file defeats the project's purpose.** |
| 2 | "Which files, how fresh, any duplicates?" | `sources` inventory: path, size, mtime, SHA-256 **[built]** | **[missing]** no duplicate detection (same content, two names), no stale/live classification, no importance ordering |
| 3 | "What's in each file?" | `_extraction_log`: per-sheet status, rows, header row, error cells **[built]** | **[missing]** no sheet *kind* classification (data table / formatted report / notes / config / dashboard). Agent cannot tell a real table from a printed report |
| 4 | "Where does the table start and end?" | one table per sheet, single header row, preamble preserved **[partial]** | **[missing]** several tables per sheet, multi-row/hierarchical headers, transposed tables, side-by-side blocks. Published research names this the dominant real-world failure mode |
| 5 | "What does this column mean?" | name, SQL type, kind, stats, top-k, samples **[built]** | **[missing]** semantic role (identifier / date / money / quantity / ratio / category / code / free text), unit, currency. Agent must guess from the header string |
| 6 | "What is one row?" (grain) | nothing | **[missing]** No grain detection at all. Without it an agent cannot know whether `SUM(amount)` is correct or double-counts. **Highest-risk silent error in the whole system.** |
| 7 | "Are there traps in the rows?" | blank rows skipped; `DQ_*` findings for nulls, constants, mixed types, null tokens, Excel errors, merged cells, formulas, pivots **[built]** | **[missing]** totals/subtotal row detection. An agent that sums a column containing a totals row silently doubles the answer |
| 8 | "How do tables relate?" | inclusion/name inference with containment + score, confirmed vs inferred **[built]** | **[partial]** no cross-file "same table, newer copy" detection |
| 9 | "What couldn't you read?" | formulas/pivots/merged flagged as quality findings **[partial]** | **[missing]** Power Query, Data Model, external links, linked data types are not detected or reported. The agent believes it saw everything. **Silent, confident blindness.** |
| 10 | "How much do I trust this?" | four trust labels; `_verification` proves stored == Excel (COUNTA/SUM) **[built]** | **[missing]** no per-table readiness verdict combining verification, structure confidence, and quality into one signal an agent can branch on |
| 11 | "Where do I start reading?" | `ai/context_pack.md` + `.json`, token-budgeted, deterministic **[built]** | **[partial]** written in handles (`t3.c7`) for compactness, with no question→tool playbook and no statement of what the pack deliberately omits in *agent* terms |
| 12 | "Is this still true?" | incremental refresh reuses unchanged sources **[built]** | **[missing]** nothing scheduled. A stale pack is worse than no pack: the agent trusts it completely |

---

## 3. Phases

Ordered by *risk removed per unit of work*, not by difficulty. Every phase keeps the existing invariants: nothing
silently lost, everything labelled with its trust level, every derived fact carries evidence, extraction output
never changes without a `CHANGELOG.md` entry and regenerated goldens.

### Phase 1 — A truthful entry point  ·  smallest, most urgent

Nothing else in this plan matters while the documented front door tells agents the platform does not exist.

1. Rewrite `skills/platform-overview/SKILL.md`: the real command list, the tiered reading order, the trust
   vocabulary, the hard rules (never open the source workbook, never dump a table, always cite evidence).
2. New `skills/agent-start/SKILL.md`: the one file an agent reads first. Ends with a concrete first command.
3. New `skills/query-playbook/SKILL.md`: a question→tool map ("how big is X" → `query describe`; "why did this
   number change" → `query compare` then `query trace`), including *when to stop*.
4. New command `xl2ai brief`: one call that prints run identity, freshness, per-table readiness, known gaps and
   the next commands — the single "orient me" call, so onboarding costs one tool call instead of five.
5. Remove the PowerShell-only assumption from the skills; the layer runs read-side on any OS.

**Proof:** an agent given only `skills/agent-start` answers three questions about an unfamiliar project using
only xl2ai commands, and opens no workbook.

### Phase 2 — Honest gaps  ·  cheap, prevents the worst failure

Confident blindness is worse than a missing feature: an agent that believes it saw everything reports wrong
conclusions with full confidence.

1. Detect and record **unsupported content** per sheet/workbook: Power Query queries, Data Model tables,
   external workbook links, linked data types, charts backed by data not on the sheet. New `_unsupported`
   table (already reserved in `DATA_CONTRACT.md` §2 phase 3).
2. Surface every one of them in the context pack as an explicit `blind_spots` section — never as a silent absence.
3. Capture formula presence as R1C1 run-length patterns per column (`_formulas`), so "this column is computed,
   not entered" becomes a fact the agent can use.
4. Detect stale cached values (manual calculation mode, file saved unrecalculated) and warn.

**Proof:** a fixture whose real logic lives in Power Query yields a pack that says so; no agent reading it can
conclude the data is complete.

### Phase 3 — Structural truth  ·  hardest, highest value

This is where real workbooks actually break. Research on spreadsheet understanding consistently identifies these
as the dominant failure modes: multiple regions per sheet, hierarchical headers, and embedded totals.

1. **Region detection**: find rectangular data blocks in one sheet (side-by-side and stacked), each becoming its
   own table with its own identity, instead of one flattened wide table.
2. **Multi-row / hierarchical headers**: reconstruct grouped headers (`Q1 → {Plan, Actual}`) into flat, unambiguous
   column names while preserving the hierarchy in `_columns`.
3. **Totals and subtotal rows**: detect and mark them (never delete them) so aggregation tools can exclude them by
   default and say that they did.
4. **Sheet kind classification**: `data | report | notes | config | dashboard | empty`, so an agent knows which
   sheets are analysable at all.
5. **Transposed tables**: detect fields-in-rows layouts and record the orientation.
6. **Header confidence**: every detection carries a score and reasons, and is overridable from config — a low
   score is a request for human confirmation, not a silent guess.

**Proof:** synthetic fixtures for each layout; every one yields correct table boundaries, and a totals row is
never counted in a default aggregate.

### Phase 4 — The semantic layer  ·  what turns data into meaning

Structure without meaning still forces the agent to guess. All outputs here are `inferred` with a method and
score, and only a human (via a pack) can promote them to `confirmed`.

1. **Column roles**: `identifier | date | money | quantity | ratio | percentage | category | code | boolean |
   free_text | geo | contact`, from value shape, distribution, header tokens and type — deterministic rules with
   published scores, never a model call.
2. **Units and currency**: detect from header tokens, formats and value ranges; record `unit` and `currency` with
   confidence; flag mixed units in one column as an error-level finding.
3. **Grain detection**: derive what one row represents from confirmed/candidate keys plus column roles, expressed
   in words ("one row per order line: order_id + line_no"). Where grain is uncertain, say so loudly — this is the
   fact that makes or breaks every aggregation an agent will ever run.
4. **Time coverage**: per table, the date column(s), min/max, and detected period type (daily/weekly/monthly).
5. **Draft descriptions**: one generated sentence per table and per column, stored as `origin=auto`,
   `status=inferred` in `_dictionary` — the raw material for the human confirmation loop (goal 3 of the six-goal plan).
6. **Cross-file duplicate/version detection**: same schema fingerprint + high row-hash overlap → "likely a newer
   copy of X", surfaced rather than silently treated as two unrelated tables.

**Proof:** on seeded fixtures every role/unit/grain is either correct or explicitly low-confidence; no wrong
answer is ever returned at high confidence.

### Phase 5 — Repairs, strictly opt-in and reversible

Repairs are the one place where the layer could corrupt the truth, so they are off by default, recorded
cell-by-cell, and never overwrite the extracted value.

1. Null-token normalization (`N/A`, `-`, `(blank)` → NULL) — already *detected* today, not applied.
2. Whitespace/case/near-duplicate category consolidation ("Cairo " / "cairo" / "CAIRO"), always as a mapping
   table, never an in-place edit.
3. Text-as-number and text-as-date coercion, with original text preserved alongside.
4. Every repair written to `_repairs` with before/after and the rule that caused it; the context pack reports
   repair counts so an agent knows the data was touched.

**Proof:** repairs off → byte-identical output to today. Repairs on → every change reversible from `_repairs`.

### Phase 6 — The agent interface and staying true

1. **Agent-facing pack**: an `ai/agent_brief.md` written for a cold agent (plain names, grain, roles, blind
   spots, readiness, next commands) alongside today's compact handle-based pack for token-tight cases.
2. **Access decision — CLI first, MCP as a thin wrapper.** Current industry findings are that MCP tool schemas
   cost context on every call while a CLI costs tokens only when used; the CLI already returns strict JSON
   envelopes. Recommendation: keep the CLI as the contract, add an MCP wrapper only if a host cannot spawn
   processes. Decide before building.
3. **Scheduled refresh + change alert** (goal 2 of the six-goal plan): a stale pack is trusted blindly, so
   freshness is a safety feature, not a convenience. Refresh on a schedule, and emit "what changed and why it
   matters" from the existing deterministic change detection.
4. **Readiness gate**: `xl2ai brief` exits non-zero when the current run is stale or unverified, so an automated
   agent can refuse to proceed on untrustworthy data instead of quietly using it.

---

## 4. Analyses, verifications, repairs, and expected failures

### Analyses the layer must perform before any agent arrives

| Class | What it produces |
|---|---|
| Structural | table regions, header rows/hierarchy, orientation, totals rows, sheet kind |
| Statistical | per column: n, nulls, distinct, min/max/mean, top-k, samples, distribution shape |
| Semantic | column role, unit, currency, table grain, time coverage, draft descriptions |
| Relational | candidate/confirmed keys, inclusion relationships with containment + score, cross-file duplicates |
| Temporal | run-to-run schema/volume/value/category/distribution/KPI/row-multiset changes |
| Quality | the `DQ_*` family, extended with totals-in-data, mixed units, near-duplicate categories |
| Integrity | stored-vs-Excel verification, cross-artifact audit, per-table readiness verdict |

### Verifications (each must be a test, not an intention)

- Stored cell count equals Excel `COUNTA`; per-column non-null counts and numeric sums equal Excel's. **[built]**
- Cross-artifact audit: catalog, source databases and manifest agree. **[built]**
- Determinism: same input → byte-identical pack. **[built for the pack]**
- Structure: detected regions/headers reproduce known fixture layouts exactly. **[Phase 3]**
- Semantics: inferred roles/units/grain match seeded fixtures, or are correctly marked low-confidence. **[Phase 4]**
- Budget: the pack stays inside its token budget on every fixture. **[built]**
- Cold-agent evaluation: a fresh agent answers a fixed question set from the pack and tools alone, and its
  answers are checked for correctness *and* for citing evidence. **[Phase 1 onwards]**

### Repair policy

Detect always, repair never by default, record everything, keep the original. A repair that cannot be reversed
from `_repairs` is a bug.

### Expected failures the layer must handle without lying

| Failure | Required behaviour |
|---|---|
| Password-protected / DRM / corrupt file | fail fast with a stable error code; previous trusted data untouched **[built]** |
| Excel crash, hang, or blocking dialog | watchdog kills only our own process, restarts, resumes **[built]** |
| Verification mismatch | run is not promoted; data is marked untrusted **[built]** |
| Two refreshes at once | lock; a live owner is never displaced on age alone **[built]** |
| Sheet is a formatted report, not a table | classified as `report`, not silently flattened **[Phase 3]** |
| Several tables on one sheet | separate tables with separate identities **[Phase 3]** |
| Totals row inside data | marked and excluded from default aggregates **[Phase 3]** |
| Logic lives in Power Query / Data Model | reported as a blind spot; never presented as complete data **[Phase 2]** |
| Ambiguous grain | stated as unknown with the reason; aggregation guidance withheld **[Phase 4]** |
| Mixed units in one column | error-level finding; unit-blind aggregation refused **[Phase 4]** |
| Source changed since last run | change detection + alert; stale pack refuses readiness **[Phase 6]** |
| Agent asks for a whole table | tools cap and say they capped **[built]** |

---

## 5. Documentation plan

Documentation is part of the product here, because the primary reader is an agent. Each phase updates docs in the
same commit as its code — the rule that was broken once already in this repo (the watch/diagnose feature shipped
with no `CHANGELOG.md` entry).

| Document | Change |
|---|---|
| `skills/*` | **Phase 1, urgent.** Rewrite to reflect shipped reality; add `agent-start` and `query-playbook`. These are the agent's entry point and are currently actively misleading |
| `AI_USAGE.md` | Add the cold-start sequence, the readiness gate, blind spots, grain, and the "stop at the tier that answers the question" rule stated for agents rather than humans |
| `ARCHITECTURE.md` | Add this plan's phases to the roadmap; state that the primary consumer is an agent, not a person; record the CLI-vs-MCP decision and its reasoning |
| `DATA_CONTRACT.md` | New/extended tables per phase: `_unsupported`, `_formulas` (P2); `_tables` regions/header hierarchy/kind, totals rows (P3); roles/units/grain/time coverage/`_dictionary` auto-drafts (P4); `_repairs` (P5). Contract version bumps: additive = minor |
| `EDGE_CASES.md` | Move each newly covered case from `planned Pn` to `covered [test_name]`; add the new cases this plan introduces |
| `BUSINESS_RULES.md` | Document confirming auto-drafted terms/roles/grain through a pack — the human confirmation loop |
| `EXTENDING.md` | How to add a detector (role, unit, structure) without embedding domain vocabulary in the platform |
| `TESTING.md` | The fixture families each phase needs, and the cold-agent evaluation harness |
| `README.md` | Reframe the opening: this is a pre-digestion layer for AI agents. Keep the human commands documented, but stop implying a person is the main reader |
| `CHANGELOG.md` | One entry per phase, listing output-affecting changes explicitly |

---

## 6. Success criteria

The plan is done when all of the following hold on a workbook set nobody on the project has seen before:

1. A cold agent, given only `skills/agent-start`, answers a fixed question set correctly using xl2ai alone.
2. It opens no workbook and calls no Excel library.
3. Its total context cost for orientation is a few hundred tokens, not tens of thousands.
4. Every answer cites evidence down to run, table and Excel row.
5. Every uncertain fact is labelled uncertain, and the agent repeats that uncertainty rather than flattening it.
6. Anything the layer could not read is stated in the agent's own words, not omitted.
7. Running it again on unchanged inputs produces byte-identical output; on changed inputs it names what changed.

---

## 7. Sequencing note

Phase 1 is hours of work and unblocks the entire premise; it should ship before anything else. Phase 2 is small
and removes the most dangerous class of error (confident blindness). Phase 3 is the largest engineering effort in
the plan and should not start until 1 and 2 are done, because it is the phase most likely to consume a whole
session's budget on its own.
