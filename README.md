# semianalyst

A personal CLI pipeline that ingests semiconductor technical releases (foundry node announcements first; conference papers and vendor whitepapers later), extracts their quantitative claims into a canonical schema where the **claim is the atomic unit** — every value cites its source span, relative claims keep their ratio and baseline instead of being converted to absolutes, and each source carries a trust tier — and (later) corroborates or flags divergence across sources.

## Quickstart

```sh
uv sync                                        # install deps into a managed venv
uv run semianalyst db init                     # create the SQLite schema (data/semianalyst.db)
uv run semianalyst ingest-file paper.pdf \     # ingest a local file (operator path; network fetch WIP)
    --doc-id tsmc_n2 --title "TSMC N2" --publisher TSMC \
    --doc-type foundry_announcement --source-tier 2 --url https://pr.tsmc.com/...
uv run semianalyst extract                     # extract grounded claims (needs ANTHROPIC_API_KEY)
uv run semianalyst report                      # cross-source corroboration + divergence
```

`db init` applies the numbered migrations under `src/semianalyst/store/migrations/` and is safe to re-run. `ingest-file` stores a local file content-addressed by sha256 under `data/raw/` (idempotent — same bytes are a no-op) and writes a provenance sidecar; `ingest` will fetch the `config.toml` watchlist the same way once network fetch lands (WIP). `extract` reads each ingested raw doc, runs the versioned prompt through the real model, validates + grounds the proposal, and persists claims (idempotent by doc_id + file_sha256; a same-doc_id/changed-bytes revision is surfaced, not silently skipped). `report` derives corroboration on read. `data/` is gitignored. Run the tests with `uv run pytest`: the offline suite replays recorded, provenance-stamped model responses (they *skip* until recorded via `--run-live --record`), and `--run-live` (with `ANTHROPIC_API_KEY`) runs the real extractor — the true gate.

See `CLAUDE.md` for the architectural rules, `schema/extraction_schema_v3.yaml` for the data model (the source of truth; `_v1`/`_v2` are retained unedited), and `docs/ROADMAP.md` for current status and priority.
