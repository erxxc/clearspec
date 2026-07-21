# Review manifest — analytical MVP slice (precommit)

- **Date:** 2026-07-20
- **Gate:** precommit
- **Target:** the diff — `workstream.diff` in this directory (analyze slice vs the extraction commit).
- **Git ref:** extraction commit `4c8c1b6` → current working tree (uncommitted).
- **Scope:** persistence + entity reconciliation (`store/persist.py`, `db.py` additions),
  `analyze` v1 (`analyze/corroborate.py`), `report` CLI wiring, v3 schema (weakly_corroborated
  + dropped baseline FK, migration 0003), the `validate.py` marketing_only fix, and the
  acceptance fixtures. Excludes the plan-gate review artifacts + uv.lock.
- **Decisions this gate must verify were honored** (from
  `docs/reviews/2026-07-20-analyze-plan-v2/resolution.md`):
  - Class B (honest correctness) fixed: `weakly_corroborated` for clean+sparsity-agree;
    group key includes `is_relative`; suspect members excluded from the corroborated count;
    an absolute claim is handled.
  - Class A (hostile-input guards) DEFERRED, not built: tier-precedence (K), alias gating (G),
    status-level tier-diversity floor (H), resolved-baseline poisoning, conflict storage (I),
    slug tripwire (J) — named in CLAUDE.md, no enforcement code.
  - Reconciliation minimal (alias-union + fill-null); confidence a status→label lookup;
    derive-on-read (no write-back).
- **Test state:** `uv run pytest` → 46 passed, 2 skipped (the 2 live extraction tests). The
  acceptance golden `test_acceptance_golden` passes deterministically.
- **Roles invoked:** injection-attacker, schema-purist, pragmatist-shipper, devils-advocate.
- **Orchestrator:** main session (reviewers as general-purpose + injected personas).
