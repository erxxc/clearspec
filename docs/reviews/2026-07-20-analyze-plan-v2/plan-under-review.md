# Analytical MVP Slice — Implementation Plan (v2, under review)

Re-gate target. GATE 1 (v1) found the DoD encoded a `validate.py` misfire; that's
fixed and the fixture is regenerated. This v2 folds every prior finding into a
concrete proposal and names what's still open. Ground in `CLAUDE.md`,
`schema/extraction_schema_v2.yaml`, and the **regenerated** fixture at
`tests/fixtures/analyze/tsmc_n2_corroboration/`.

## 0. Ratified since v1
- **P1 (done):** `marketing_only` is cross-vendor only. `validate.py` now requires
  both vendors known + different (fix + test committed to the working tree, suite
  green). Same-vendor sparsity → an analyze-layer `sparsity` flag, not a completeness label.
- **P2 (in fixture):** a baseline that resolves to a stored entity is used; a
  dangling baseline (fixture's `intel_18a`, never ingested) is kept and flagged
  `unresolved_baseline`.
- Regenerated `expected_analysis.json`: 4 assessments — logic_speed **corroborated**
  (tier 1+2), perf_per_watt **contradicted** (foundry iso 1.3x vs vendor sparsity
  1.8x; `flags:["sparsity"]`, favored tier 2), throughput **uncorroborated**
  (`["sparsity","single_source"]`), logic_density **uncorroborated**
  (`["unresolved_baseline","single_source"]`).

## 1. Workstream 1 — Persistence + reconciliation (`store/`)
- `store.persist_extraction(document, ExtractionResult)`: insert document
  (fail-loud on dup `doc_id`), reconcile entities, insert doc-scoped claims
  (`claim_id -> {doc_id}:{claim_id}`).
- **Reconciling entity upsert (scoped down per pragmatist):** union `aliases`;
  **null-fill** node/chip attributes AND their `attribute_citations` together —
  never populate a value without carrying its citation (schema-purist F3). Fill is
  **tier-aware / order-independent**: the higher-trust (lower `source_tier`)
  document's value wins a null-fill race (injection F1). A non-null conflict is
  **logged, not stored** — no new conflict schema this MVP (pragmatist F1;
  CLAUDE.md "change the schema first"). Persisted conflict-tracking → deferred (Decision I).
- **Exact-slug matching (Decision A, retained):** same `entity_id` = same thing.
  **New tripwire (schema-purist risk):** after a load, if two entities share
  `(entity_type, vendor)` with high alias-token overlap, emit a warning — so a
  same-thing-slugged-differently miss is *loud*, not silent under-corroboration.

## 2. Workstream 2 — `analyze` v1 (`analyze/`, read-only over `store`)
- **Grouping key `(entity_id, metric, is_relative, baseline_entity)`** (schema-purist
  F1 — `is_relative` added). A relative claim with **no** baseline
  (`baseline_stated=false` / `baseline_entity=null`) forms its own singleton and is
  never comparable. A **dangling** baseline (not resolvable in the store) → singleton
  + `unresolved_baseline` flag (P2).
- **Corroboration count excludes suspect members (schema-purist F2):** a
  `sparsity=true` or `marketing_only` claim may *ride along* but does NOT count
  toward the `≥2 within tolerance` needed for `corroborated`; its presence adds the
  `sparsity`/`marketing_only` flag to the group. So a clean+marketing pair that
  agrees is NOT `corroborated`.
- **Verdicts** (tolerance = flat **±10%**, Decision B): `corroborated` (≥2
  non-suspect within tolerance), `contradicted` (spread beyond tolerance;
  `favored_tier` = min tier among non-suspect members), `uncorroborated` (singleton).
  `related_claim_ids` linked **symmetrically for every non-singleton group**,
  contradicted included (schema-purist F1 secondary).
- **Confidence (Decision H, proposed):** MVP status-derived, but with a
  **tier-diversity cap** — an all-tier-3 corroboration is capped at `low`, never
  `high` (injection F3: colluding tier-3 docs can't manufacture `high`). A fixture
  case forcing confidence≠status will be added iff this is ratified (answers
  pragmatist E's "no fixture forces them apart").
- **Write-back (Decision C → derive-on-read for MVP, per pragmatist):** `analyze`
  returns an `AnalysisReport`; it does NOT mutate `claim.corroboration` in the store
  this iteration. Write-back is a fast-follow when a direct reader of the stored
  verdict exists.

## 3. Workstream 3 — `report` + CLI
- `analyze.run_analysis(config) -> AnalysisReport`; `semianalyst report` prints
  per-entity assessments. CLI stays thin.

## 4. Testing
- **Acceptance golden:** load 3 sources → `persist_extraction` → `run_analysis`
  → `== expected_analysis.json`. Deterministic, offline.
- **Unit tests (no untested branch):** null-fill tier-precedence + citation
  propagation; alias union; slug-collision tripwire; doc-scoped claim_id;
  group-key `is_relative`/unstated-baseline singleton; dangling-baseline flag;
  clean+marketing agree → NOT corroborated; contradicted `related_claim_ids`
  symmetry; tier-diversity confidence cap (if H ratified).

## 5. Open decisions for the re-gate
- **G — alias acceptance gating:** ungated union (current fixture keeps tier-3
  `"2nm-class"`) vs tier-restricted vs citation-required. (injection F2 / advocate)
- **H — confidence / tier-diversity model:** status-derived + all-tier-3 cap
  (proposed) vs full tier-weighted vs drop confidence for MVP.
- **I — reconciliation conflict handling:** log-only (proposed) vs a persisted
  conflict record (needs a `_v3` schema field).
- **J — slug-collision tripwire strength:** warn (proposed) vs fail-loud vs
  alias-based canonical matching now.

## 6. Files touched
New: `analyze/corroborate.py` (+ `AnalysisReport`), `store/persist.py`
(`persist_extraction` + reconciling upsert + tripwire), `tests/test_analyze.py`,
`tests/test_reconciliation.py`. Edited: `store/db.py` (entity upsert helper),
`store/__init__.py`, `cli.py` (`report`). Already done: `validate.py` marketing_only
fix (+ test), the regenerated acceptance fixtures. **Not touched:** `ingest/`,
`extract/` (beyond the marketing_only fix), `config.py`, the v1 prompt.
