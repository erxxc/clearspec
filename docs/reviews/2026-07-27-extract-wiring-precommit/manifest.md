# Review manifest — extract-wiring (precommit)

- **Date:** 2026-07-27
- **Gate:** precommit
- **Target:** diff — `docs/reviews/2026-07-27-extract-wiring-precommit/workstream.diff`
- **Git ref:** working tree @ `def696f` (analyze commit); base branch `feat/analyze-v1`
- **Scope:** WS-1 — wire `run_extract` (extract E2E on operator-fed raw docs). Files:
  - `src/semianalyst/extract/pipeline.py` — `run_extract` orchestration (was a stub)
  - `src/semianalyst/ingest/base.py` — provenance sidecar (`write_sidecar` / `read_raw_docs` / `RawDoc`)
  - `src/semianalyst/ingest/pipeline.py` — operator `ingest_file`
  - `src/semianalyst/cli.py` — `ingest-file` command, `extract` output, `_ansi_safe` report sanitizer
  - `src/semianalyst/store/db.py` + `store/__init__.py` — `existing_doc_ids` (idempotent skip)
  - `src/semianalyst/{ingest,extract}/__init__.py` — exports
  - `tests/test_pipeline_e2e.py` — new E2E + sanitizer tests
  - `docs/ROADMAP.md` — new canonical planning doc; `CLAUDE.md`, `README.md`, `config.toml` — decision record + drift fixes
- **Suite at gate open:** `52 passed, 3 skipped` (the 3 skips are `@live`: golden, injection, new E2E).
- **Trust boundary (context, not a free pass):** this slice is curated-fixture /
  operator-fed. Class A hostile-input trust is DEFERRED per CLAUDE.md; the
  ingest→extract handoff (sidecar + extract-time Document) was a human decision
  recorded in ROADMAP + CLAUDE.md; "report display safety" was pulled forward and
  implemented (`cli._ansi_safe`). Reviewers should judge whether THIS diff stays
  honestly within that boundary — or quietly crosses it.
- **Roles invoked:**
  - injection-attacker
  - schema-purist
  - pragmatist-shipper
  - devils-advocate (after the above)
- **Orchestrator:** main session
