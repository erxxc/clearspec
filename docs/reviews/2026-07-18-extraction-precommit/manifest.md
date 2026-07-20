# Review manifest — extraction-engine (precommit)

- **Date:** 2026-07-18
- **Gate:** precommit
- **Target:** the diff — `workstream.diff` in this directory (extraction engine vs scaffold).
- **Git ref:** scaffold commit `620106d` → current working tree (uncommitted).
- **Scope:** the extraction-engine implementation: v2 schema + migration + models, the
  extractor (`extract/base.py`, `pdf.py`, `validate.py`), the prompt, fixtures, and tests.
  Excludes the GATE-1 review artifacts and `uv.lock` (noise).
- **Decisions this gate must verify were honored** (from
  `docs/reviews/2026-07-17-extraction-plan/resolution.md`):
  - ENFORCE — live tests are the real anchor; offline never fabricates model output.
  - Decision C — entity attributes code-grounded via a real v2 schema slot (no shadow schema).
  - location_type fail-safe to `unknown`.
- **Test state at gate:** `uv run pytest --run-live` → 23 passed (golden + injection live);
  `uv run pytest` (offline) → 21 passed, 2 skipped.
- **Roles invoked:** injection-attacker, schema-purist, pragmatist-shipper, devils-advocate.
- **Orchestrator:** main session (reviewers run as general-purpose with injected personas,
  as in GATE 1 — the named agent types aren't registered this session).
