# Resolution — extraction-engine (precommit)

Merge of the four opinions in this directory, written by the main session.
Unlike GATE 1 (a philosophical fork), GATE 2 found concrete bugs — so this is a
findings-and-disposition record: each finding is fixed-and-tested or flagged.

> **Process note:** reviewers ran as `general-purpose` with injected personas (as
> in GATE 1). The devil's advocate was interrupted mid-run by a session limit and
> was re-run to completion.

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | **BLOCK** | `completeness` + `claim.entity_id` never cross-checked; log-injection via `Rejection.target`. |
| schema-purist | **BLOCK** | `%` in `RATIO_UNITS` destroys grounded absolute-% claims (yield); entity-merge loses values; a silent unlogged drop. |
| pragmatist-shipper | **CONDITIONAL** | untested normalization branches; dead base.py branches; the model pays to emit a `location_type` that's always discarded. |
| devils-advocate | (challenge) | The corruption **primitive** (`INSERT OR REPLACE` on model-derived ids) lives in out-of-scope `store/`; the same-proposal check is a false middle, and the upsert also silently destroys legit corroboration. |

## Agreements (verified in the diff, not re-litigated)
Value/attribute grounding, API-key handling (env-only, never logged), per-item
shape-drop, the v2 schema field (not a shadow schema), prompt-caching cut, and
scope discipline (`ingest/`/`cli.py`/`analyze/`/`config.py` untouched) all hold.

## Findings & dispositions

### Blocking bugs — FIXED (with tests)
1. **`%`-in-`RATIO_UNITS` destroys absolute-% claims** (schema-purist F1). → Split
   `RATIO_UNITS = {x,X,×}` vs `RELATIVE_OK_UNITS = {…,%}`: an absolute 65% yield
   survives, a relative 30% survives, `x` still requires `is_relative`. Tests:
   `test_absolute_percentage_survives`, `test_relative_percentage_survives`.
2. **`completeness` self-reported → "set all complete" injection bypass**
   (injection F1). → A relative claim with no baseline is downgraded to
   `missing_baseline` regardless of the model's label. The injection test now
   asserts the downgrade on the hostile fixture. Test:
   `test_completeness_downgraded_when_baseline_missing`.
3. **`claim.entity_id` unchecked + `INSERT OR REPLACE` cross-entity poisoning**
   (injection F2 / advocate). → **Split fix**, honestly scoped:
   - `validate.py` now drops a claim whose `entity_id` isn't an entity from its
     own proposal (per-document boundary). Test: `test_claim_referencing_unknown_entity_is_dropped`.
   - `store/db.py` inserts changed from silent-clobber `INSERT OR REPLACE` to
     **fail-loud `INSERT`** (a duplicate id raises).
   - Cross-document reconciliation is documented as a **blocking prerequisite for
     persistence** in CLAUDE.md. The advocate is right that the validate check
     alone can't fix poisoning — the store change + prereq carry that weight.
4. **Entity merge lost node/chip values, orphaning citations** (schema-purist F2).
   → Merge now reconciles attribute VALUES, not just citations. Test:
   `test_entity_merge_reconciles_attribute_values`.
5. **Silent unlogged stray-citation drop** (schema-purist F3). → Now emits a
   `Rejection`. Test: `test_stray_attribute_citation_is_dropped_and_logged`.
6. **Log-injection via unsanitized `Rejection.target`** (injection F3). → `_safe()`
   strips control chars + truncates before logging; docstring corrected to be
   accurate about what's a model-supplied value.

### Conditional items — DONE
7. Untested normalization branches (pragmatist 1) → tests added (kW→W; the
   stray-citation branch); small unit table kept.
8. Dead base.py branches — JSON-fence fallback + refusal guard (pragmatist 2) →
   covered offline with a fake `ModelClient` in `tests/test_extract.py`.

### Flagged — need your read (not pure bug fixes)
- **A. `location_type` fail-safe wiring.** The GATE-1 decision said "flag via
  `review_status`," but `review_status` is a **Document** field, not extractor
  output. Disposition applied: `location_type=unknown` on every citation IS the
  queryable fail-safe signal (never `body`); wiring `review_status` would need the
  extractor to also emit a Document-level flag (a larger change). **Accept
  `unknown` as the signal, or wire `review_status` later?** *(recommend accept.)*
- **B. Fail-loud inserts.** Changing `INSERT OR REPLACE` → `INSERT` is my call to
  prevent silent corruption now. **Confirm, or prefer to leave the upsert and
  defer entirely to the store workstream with only a doc warning?** *(recommend
  the fail-loud change, as done.)*
- **C. Live-golden determinism.** pragmatist suggested `temperature=0` — **not
  applicable**: sampling params are removed on Opus 4.8 (400 if sent). The live
  exact-match assertion may occasionally flake on wording; the deterministic
  offline replay is the primary green signal. Accepted residual; revisit by
  softening the live assertion (grounded-invariants instead of byte-exact) if
  flake appears in CI.

### Residual risks (accepted, with triggers)
- Hidden/invisible PDF text (GATE-1 accepted; revisit at `pdfplumber`).
- Delimiter has no escaping of embedded `</document_content>` (defense-in-depth
  only; blast radius bounded now that categorical + entity checks exist).
- Fuller `completeness` derivation (only the missing-baseline case is enforced);
  `marketing_only` "competitor" is defined as cross-vendor.

## Named conflict (advocate) — NOT averaged
**Where the entity-poisoning fix belongs:** `validate.py` (per-document) vs
`store/` (cross-document, declared out of scope). Resolved by splitting rather
than pretending one side covers it — per-document check in `validate.py` now;
cross-document reconciliation is a documented store-workstream blocker plus a
fail-loud stopgap. The question the advocate said was "decided nowhere" is now
decided: a duplicate entity id **raises** until reconciliation is designed.

## Outcome
**BLOCKs resolved** — bugs fixed and tested; offline 34 passed / 2 skipped, live
`--run-live` **36 passed**. **Pending your sign-off** on flagged decisions **A**
and **B** before the workstream commit.
