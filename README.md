# clearspec (package `semianalyst`)

A truth layer, not a scanner. One engine ingests untrusted documents, extracts quote-grounded claims into a canonical schema where the **claim is the atomic unit** — every value cites its source span, relative claims keep their ratio and baseline instead of being converted to absolutes, nothing is ever overwritten, and disagreements are persisted as conflicts — then reports where sources corroborate or diverge.

Two domain packs run on that engine:

- **Advisory corroboration (current wedge, schema v5, `extract_advisory_v1`).** NVD vs GHSA vs vendor vs CISA KEV on a CVE × package/product: affected range, patched-in version, CVSS, exploit status. Version ranges are structured intervals compared as sets, not numeric tolerances. **The conflict is the product** — `conflict-report` is the ship artifact, never a CVE feed, and no tier ever auto-resolves a fight.
- **Semiconductor foundry claims (original pack, schema v4, `extract_foundry_v1`).** Foundry node announcements, conference papers, vendor whitepapers; numeric claims corroborated with a ±10% ruler and source tiers.

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
uv run semianalyst conflict-report [--cve-id CVE-2024-21626]   # per-CVE conflict ship artifact (advisory pack)
uv run semianalyst forget tsmc_n2              # quarantine a poisoned doc's provenance + refold the DB
uv run semianalyst db rebuild                  # refold the DB from retained extraction artifacts
```

`db init` applies the numbered migrations under `src/semianalyst/store/migrations/` and is safe to re-run. `ingest-file` stores a local file content-addressed by sha256 under `data/raw/` (idempotent — same bytes are a no-op) and writes a provenance sidecar; `ingest` fetches each source's configured `documents = [...]` URLs from the `config.toml` watchlist the same way — HTTPS-only at every redirect hop, redirect/size caps, PDF magic check, rate-paced, per-document fault isolation; a doc_id retracted by `forget` is refused loudly, never silently revived. `extract` reads each ingested raw doc, runs the versioned prompt through the real model, validates + grounds the proposal, and persists claims (idempotent by doc_id + file_sha256; a same-doc_id/changed-bytes revision is surfaced, not silently skipped). `report` derives corroboration on read. `data/` is gitignored. Run the tests with `uv run pytest`: the offline suite replays recorded, provenance-stamped model responses (they *skip* until recorded via `--run-live --record`), and `--run-live` (with `ANTHROPIC_API_KEY`) runs the real extractor — the true gate.

GitHub Actions runs the offline suite on pull requests and `main` (`uv run pytest -m "not live"`). That job does not set `ANTHROPIC_API_KEY`, does not pass `--run-live`, and does not fetch NVD/GHSA/CISA. Refresh `tests/fixtures/*/llm_response.json` with `uv run pytest --run-live --record`; a live CI job is deferred.

Advisory sources: `config.toml` carries `[[sources]]` rows for the NVD CVE API, GHSA, and the CISA KEV feed with a `parser_role` (`cpe`/`cna`, `reviewed`/`unreviewed`, `kev`) that ingest records in the sidecar and extract turns into `source_record_kind` — the document can never self-declare its kind. Add explicit `documents = [...]` URLs to fetch; JSON is magic-checked the way PDFs are. Operator-fed advisory JSON goes through `ingest-file --doc-type nvd_record --parser-role cpe ...`.

See `CLAUDE.md` for the architectural rules, `schema/extraction_schema_v5.yaml` (advisory pack) and `schema/extraction_schema_v4.yaml` (foundry pack) for the data model (the source of truth; `_v1`–`_v3` are retained unedited), `docs/gei14-parser-role-mapping.md` for the parser_role → kind table, and `docs/ROADMAP.md` for current status and priority.
