# Review manifest — analytical MVP slice (plan, v2 / re-gate)

- **Date:** 2026-07-20
- **Gate:** plan (re-run against a ratified DoD)
- **Target:** `plan-under-review.md` (this directory)
- **Prior gate:** `docs/reviews/2026-07-20-analyze-plan/` found the acceptance
  fixture (DoD) was self-contradictory — its `marketing_only` flags were an
  artifact of a `validate.py` misfire on unresolved baselines.
- **What changed since the prior gate (human-ratified):**
  - P1: `marketing_only` is cross-vendor only; `validate.py` FIXED (both vendors
    must be known + differ); same-vendor sparsity is an analyze-layer `sparsity`
    flag. (Committed-code fix + test, suite green.)
  - P2: baseline references trusted; a dangling baseline is flagged
    `unresolved_baseline`. Fixture now includes a dangling "Intel 18A" baseline.
  - `expected_analysis.json` regenerated to the honest target.
- **Scope:** the REVISED design (§ below) folding in every GATE-1 finding as a
  concrete proposal, plus the remaining open decisions.
- **Roles invoked:** injection-attacker, schema-purist, pragmatist-shipper, devils-advocate.
- **Orchestrator:** main session (reviewers as general-purpose + injected personas).
