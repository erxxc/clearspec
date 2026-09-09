# semianalyst

A personal CLI pipeline that ingests semiconductor technical releases (foundry node announcements first; conference papers and vendor whitepapers later), extracts their quantitative claims into a canonical schema where the **claim is the atomic unit** — every value cites its source span, relative claims keep their ratio and baseline instead of being converted to absolutes, and each source carries a trust tier — and (later) corroborates or flags divergence across sources.

## Quickstart

```sh
uv sync                                        # install deps into a managed venv
uv run semianalyst db init                     # create the SQLite schema (data/semianalyst.db)
uv run semianalyst ingest                      # fetch the config.toml watchlist (https-only, capped, rate-paced)
uv run semianalyst ingest-file paper.pdf \     # ingest a local file (operator path)
    --doc-id tsmc_n2 --title "TSMC N2" --publisher TSMC \
    --doc-type foundry_announcement --source-tier 2 --url https://pr.tsmc.com/...
uv run semianalyst extract                     # extract grounded claims (needs ANTHROPIC_API_KEY only when work is pending)
uv run semianalyst report                      # cross-source corroboration + divergence + conflicts
uv run semianalyst forget tsmc_n2              # quarantine a poisoned doc's provenance + refold the DB
uv run semianalyst db rebuild                  # refold the DB from retained extraction artifacts
```

`db init` applies the numbered migrations under `src/semianalyst/store/migrations/` and is safe to re-run. `ingest-file` stores a local file content-addressed by sha256 under `data/raw/` (idempotent — same bytes are a no-op) and writes a provenance sidecar; `ingest` fetches each source's configured `documents = [...]` URLs from the `config.toml` watchlist the same way — HTTPS-only at every redirect hop, redirect/size caps, PDF magic check, rate-paced, per-document fault isolation; a doc_id retracted by `forget` is refused loudly, never silently revived. `extract` reads each ingested raw doc, runs the versioned prompt through the real model, validates + grounds the proposal, and persists claims (idempotent by doc_id + file_sha256; a same-doc_id/changed-bytes revision is surfaced, not silently skipped). `report` derives corroboration on read. `data/` is gitignored. Run the tests with `uv run pytest`: the offline suite replays recorded, provenance-stamped model responses (they *skip* until recorded via `--run-live --record`), and `--run-live` (with `ANTHROPIC_API_KEY`) runs the real extractor — the true gate.

GitHub Actions runs the offline suite on pull requests and `main` (`uv run pytest -m "not live"`). That job does not set `ANTHROPIC_API_KEY`, does not pass `--run-live`, and does not fetch NVD/GHSA/CISA. Refresh `tests/fixtures/*/llm_response.json` with `uv run pytest --run-live --record`; a live CI job is deferred.

See `CLAUDE.md` for the architectural rules, `schema/extraction_schema_v4.yaml` for the data model (the source of truth; `_v1`–`_v3` are retained unedited), and `docs/ROADMAP.md` for current status and priority.
