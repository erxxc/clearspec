# Analytical MVP Slice — Implementation Plan (under review)

GATE 1 target. Reviewers: attack from your angle; ground in `CLAUDE.md`,
`schema/extraction_schema_v2.yaml`, and the acceptance fixtures at
`tests/fixtures/analyze/tsmc_n2_corroboration/`. Write your opinion to `<role>.md`
here; return a verdict line + one sentence.

## 0. The MVP acceptance test (already written — the definition of done)
`tests/fixtures/analyze/tsmc_n2_corroboration/`: three curated post-extraction
sources about TSMC N2 + `expected_analysis.json`. Load all three → persist with
reconciliation → analyze → must equal the expected verdict:
- **N2 reconciles to one entity** across 3 docs (alias union `{N2, TSMC 2nm, 2nm-class}`);
  N3E across 2 docs.
- **logic_speed corroborated** — foundry 1.15x (tier 2) + conference 1.18x (tier 1),
  same baseline N3E, ~2.6% spread → agreement, tier-weighted `high`.
- **perf_per_watt contradicted** — foundry iso-power 1.3x (tier 2) vs vendor 1.8x
  (tier 3, **sparsity**), ~38% spread → divergence, favored toward tier 2, flagged.
- **throughput uncorroborated** — vendor 2.0x (tier 3, sparsity), single source → suspect.
The load-bearing assertions are STATUS + membership + flags; exact numerics
(tolerance, spread, confidence labels) encode design choices you should confirm.

## 1. Objective & Definition of Done
- New `analyze` golden passes deterministically (no live model — the corpus is
  curated claim sets, so analysis logic is isolated from extraction flakiness).
- `semianalyst report` prints the corroborated-vs-diverged readout.
- Persistence + reconciliation land in `store/`; `analyze/` is built read-only over
  the store; `cli.py` stays thin; `ingest/`, `extract/`, `config.py` untouched.

## 2. Workstream 1 — Persistence + entity reconciliation (`store/`)
The extraction GATE-2 left inserts **fail-loud** precisely because cross-document
reconciliation was undesigned. This workstream designs it.
- **Loading:** a `store.persist_extraction(document, ExtractionResult)` library
  call inserts the document, reconciles entities, and inserts doc-scoped claims.
- **Entity identity (MVP):** exact `entity_id` (slug) equality = same real thing.
  On a repeat entity_id: **reconcile** — union `aliases`, fill null node/chip
  attributes from the newcomer, and if a non-null attribute **conflicts** (a
  different grounded value), record it as a conflict rather than overwrite. So the
  entity insert becomes a *reconciling upsert*, replacing fail-loud **for entities**.
  - Known limitation (Decision A): slug equality misses a source that slugs N2
    differently (e.g. name "2nm" → `tsmc_2nm`). Alias-based canonical resolution
    is deferred; the fixtures assume consistent slugs.
- **Claim identity (Decision D):** the extractor emits doc-agnostic `claim_id`
  (`entity_metric`), which collides across documents. `persist_extraction`
  doc-scopes them (`{doc_id}:{claim_id}`) so two docs' `logic_speed` claims
  coexist. Documents stay fail-loud on duplicate `doc_id` (re-ingest is idempotent
  upstream).
- **DoD:** the 3 sources persist; store holds one `tsmc_n2` (merged aliases) + all
  five claims; a synthetic attribute conflict is flagged, not clobbered.

## 3. Workstream 2 — `analyze` v1 (`analyze/`, read-only over `store`)
- **Grouping:** all claims joined to their `document.source_tier`; grouped by
  `(entity_id, metric, baseline_entity)`. **Same baseline is required** to compare
  relative claims — never reconstruct an absolute to compare across baselines.
- **Per group verdict** (writes `CorroborationStatus`):
  - **corroborated** — ≥2 members within tolerance; `related_claim_ids` linked;
    `confidence` from tier span (multiple/high tiers agreeing → `high`).
  - **contradicted** — members spread beyond tolerance; `favored_tier` = the
    highest-trust (lowest-numbered) source; `flags` carry marketing_only/sparsity.
  - **uncorroborated** — a single member; flagged (marketing_only/sparsity/single_source).
- **Sparsity/marketing rule:** a `marketing_only` or `sparsity=true` claim can
  NEVER by itself make a group `corroborated`; if it's the outlier it's the named
  suspect. This is the schema's anti-inflation principle, enforced in analysis.
- **Tolerance (Decision B):** propose a flat **±10%** relative spread. Per-metric
  or per-claim-class tolerance is deferred.
- **Write-back vs derive (Decision C):** propose analyze **writes back**
  `claim.corroboration.status` + `related_claim_ids` into the store (the schema has
  the fields) AND returns an `AnalysisReport` (the `assessments` in the fixture) for
  the report/CLI. Alternative: derive on read, store stays immutable.

## 4. Workstream 3 — `report` + CLI
- `analyze.run_analysis(config) -> AnalysisReport` is the library entry point.
- `semianalyst report` calls it and prints per-entity assessments (corroborated /
  contradicted / suspect). CLI stays thin — no analysis logic in `cli.py`.

## 5. Testing strategy
- **Acceptance golden:** load fixtures → `persist_extraction` ×3 → `run_analysis`
  → assert `== expected_analysis.json`. Deterministic, offline.
- **Unit tests:** reconciliation (alias union, null-fill, conflict-flag, claim-id
  doc-scoping, duplicate-doc fail-loud); corroboration (tolerance boundary at ±10%,
  tier-weighting, same-baseline requirement, sparsity-never-corroborated,
  single-source suspect). No untested branch (per the standing pragmatist bar).

## 6. Open decisions for the human (the gate should sharpen these)
- **A. Reconciliation matching** — exact-slug only (MVP) vs alias-based canonical
  resolution now.
- **B. Tolerance model** — flat ±10% vs per-metric/per-class.
- **C. Write-back vs derive** — analyze mutates `claim.corroboration` vs computes on read.
- **D. `claim_id` doc-scoping scheme** — `{doc_id}:{claim_id}` vs a hash vs changing
  the extractor's id scheme (would touch the immutable v1 prompt).
- **E. Confidence labels** (`high`/`low`/`none`) — keep for MVP or drop as premature.
- **F. Entities become a reconciling upsert** — this partially reverses the
  extraction GATE-2 fail-loud decision *for entities only*; documents/claims stay
  fail-loud/doc-scoped. Confirm the split.

## 7. Files touched
New: `analyze/corroborate.py` (+ report types), `store/persist.py` (or extend
`store/db.py`) for `persist_extraction` + reconciling upsert, `tests/test_analyze.py`,
`tests/test_reconciliation.py`. Edited: `store/db.py` (entity upsert), `cli.py`
(`report` wired), `store/__init__.py` exports. Already written: the acceptance
fixtures. **Not touched:** `ingest/`, `extract/`, `config.py`, the v1 prompt/schema.
