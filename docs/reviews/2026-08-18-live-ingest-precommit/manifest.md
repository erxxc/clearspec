# Review manifest — live-ingest WS-2a (precommit)

- **Date:** 2026-08-18
- **Gate:** precommit
- **Target:** the WS-2a diff (`workstream.diff` in this directory = `git diff
  5a8af2c..d6adb94` on `feat/ws2a-trust`; the plan-gate resolution at
  `docs/reviews/2026-08-18-live-ingest-plan/resolution.md` is the contract it
  implements)
- **Git ref:** d6adb94 (feat/ws2a-trust; stacked on fix/sparsity-grounding = PR #4)
- **Scope:** schema v4 + migration 0004 (conflict record, two-layer content
  bounds); validate G1 alias grounding + identity presence-grounding;
  read-compare-write reconciliation with persisted conflicts (K1/K2, G3 on both
  paths); extraction artifacts + refold (`forget`, `db rebuild`, revision
  supersession, S1/S2); analyze H1 publisher floor + group-key normalization +
  advisory flags + conflict surfacing; CLI Cf display stripping + refusal UX;
  named hostile suite + honest-corpus regression + flag budget; CLAUDE.md/
  ROADMAP/README updates. Pre-gate verification already run: appsec review
  (3 findings, all fixed in d6adb94) + operator UAT (no blockers; A1-A3/C1-C2
  fixed) + full live suite (115 passed, 0 skipped).
- **Roles invoked:**
  - injection-attacker
  - schema-purist
  - pragmatist-shipper
  - devils-advocate (after the above)
- **Orchestrator:** main session
