# semianalyst

A personal CLI pipeline that ingests semiconductor technical releases (foundry node announcements first; conference papers and vendor whitepapers later), extracts their quantitative claims into a canonical schema where the **claim is the atomic unit** — every value cites its source span, relative claims keep their ratio and baseline instead of being converted to absolutes, and each source carries a trust tier — and (later) corroborates or flags divergence across sources.

## Quickstart

```sh
uv sync                 # install deps into a managed venv
uv run semianalyst db init      # create the SQLite schema (data/semianalyst.db)
uv run semianalyst ingest       # fetch the watchlist in config.toml (network fetch WIP)
uv run semianalyst report       # summarize stored documents / entities / claims
```

`db init` applies the numbered migrations under `src/semianalyst/store/migrations/` and is safe to re-run. `ingest` stores raw docs content-addressed by sha256 under `data/raw/` (idempotent — an unchanged doc is a no-op; a changed one is a new file). `data/` is gitignored. Run the tests with `uv run pytest` (the golden-extraction harness `xfail`s until the LLM extractor lands).

See `CLAUDE.md` for the architectural rules and `schema/extraction_schema_v1.yaml` for the data model (the source of truth).
