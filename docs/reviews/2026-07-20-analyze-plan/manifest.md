# Review manifest — analytical MVP slice (plan)

- **Date:** 2026-07-20
- **Gate:** plan
- **Target:** `plan-under-review.md` (this directory)
- **Git ref:** extraction commit `4c8c1b6` + working-tree additions:
  `tests/fixtures/analyze/tsmc_n2_corroboration/` (the MVP acceptance fixtures,
  written first as the definition-of-done).
- **Scope:** the design for the analytical MVP slice — (1) persistence + cross-document
  entity reconciliation in `store/`, (2) `analyze` v1 (corroboration/divergence,
  tier-weighted), (3) `report` + CLI wiring. Proven on the curated 3-source corpus.
- **Roles invoked:** injection-attacker, schema-purist, pragmatist-shipper, devils-advocate.
- **Orchestrator:** main session (reviewers run as general-purpose with injected personas).
