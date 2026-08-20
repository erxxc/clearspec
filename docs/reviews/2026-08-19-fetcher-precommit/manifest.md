# Review manifest — fetcher WS-2b (precommit)

- **Date:** 2026-08-19
- **Gate:** precommit
- **Target:** the WS-2b diff (`workstream.diff` = `git diff 42a81ff..4d0547e` on
  `feat/ws2b-fetcher`); contract: the plan-gate resolution's Outcome §1
  (`docs/reviews/2026-08-18-live-ingest-plan/resolution.md`)
- **Git ref:** 4d0547e (feat/ws2b-fetcher, based on main @ 42a81ff)
- **Scope:** `ingest/fetch.py` (new — HTTPS-only per-hop policy engine, manual
  redirect loop, streamed size cap, timeout, PDF magic helper),
  `ingest/foundry.py` (real fetcher), `ingest/pipeline.py` (`run_ingest` wiring:
  URL-slug doc_id, sidecar from watchlist fields, final-URL audit recording,
  rate pacing, per-doc fault isolation), `ingest/base.py` (protocol reshape),
  `config.py`/`config.toml` (per-source `publisher` + `documents`), `cli.py`
  (ingest echo), `tests/test_fetch.py` (19 tests, local HTTP server,
  transport-injection seam below the policy boundary). Suite at ref: offline
  138 passed / 3 skipped, live 141 passed / 0 skipped. Note: a supplementary
  appsec pass was started and stopped by the operator before reporting — the
  injection-attacker brief below absorbs its focus areas.
- **Roles invoked:**
  - injection-attacker
  - schema-purist
  - pragmatist-shipper
  - devils-advocate (after the above)
- **Orchestrator:** main session
