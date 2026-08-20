# pragmatist-shipper — WS-2b fetcher (precommit)

**Verdict: APPROVE WITH CONDITIONS**

Delivery-and-simplicity read of `workstream.diff` (4d0547e) against the plan
gate's Outcome §1 contract. Short version: the code is a tight, on-scope
implementation of exactly what was promised — my usual targets (speculative
abstraction, hand-rolled re-validation of what pydantic/DDL already guarantee)
mostly don't materialize here. The one real gap is that this diff, which the
manifest itself calls "the last stub for the tool as designed," does not touch
a single doc file — and this repo's own ROADMAP.md convention requires status
updates in the *same commit* a slice lands.

## Findings

### 1. [HIGH] Docs drift — README/ROADMAP/CLAUDE.md all still describe the fetcher as a future stub
**Location:** `README.md:10-11,19`, `docs/ROADMAP.md:20,24,91,103-104,129-132`,
`CLAUDE.md` "Module map" (`ingest/` line).
None of these three files appear in `workstream.diff` — this is a code-only
diff shipping the network fetcher, but every doc still says otherwise:
- `README.md:10`: `# ingest a local file (operator path; network fetch WIP)`
- `README.md:19`: `` `ingest` will fetch the `config.toml` watchlist the same
  way once network fetch lands (WIP).``
- `ROADMAP.md:20`: `## Current state — extract E2E is wired (WS-1); network
  fetch (WS-2) is the one remaining stub`
- `ROADMAP.md:24`: table row `| `ingest/` network fetch | **STUB (WS-2)** |
  `FoundryFetcher.fetch` → `NotImplementedError`; ... |` — this is now simply
  false; `FoundryFetcher.fetch` is real and tested.
- `ROADMAP.md:91`: `**WS-2a BUILT ... WS-2b NEXT**` and the build-order list
  (§129-132) still frames WS-2b as unstarted future work, not delivered.
- `CLAUDE.md` module map: `` `ingest_file` operator path live; network fetch:
  WS-2b) `` — reads as still-future.

CLAUDE.md is explicit that this file's own convention ("when a slice lands,
move its row from *Open* to *Built*... in the same commit") is not optional,
and the orchestrator's framing says this gate is the last chance before merge.
This is not a design problem — the fix is a doc-only follow-up commit — but it
is squarely inside the definition of done and it's cheap to close now rather
than after merge.
**Fix:** before merge, flip the three stale sections: README quickstart
comments, the ROADMAP state table + WS-2 header, and the CLAUDE.md module-map
parenthetical. ~10 minutes of editing, no code risk.

### 2. [MED] Hand-rolled `rpm <= 0` guard duplicates work pydantic should do
**Location:** `src/semianalyst/ingest/pipeline.py` (`run_ingest`, the
`if rpm <= 0: raise ValueError(...)` block) vs. `src/semianalyst/config.py`
`RateLimits.requests_per_minute: int = 10` (no constraint).
This isn't the usual "Python re-checks what pydantic already guarantees"
pattern — it's the inverse: pydantic *should* guarantee it and doesn't, so
`run_ingest` grew a runtime branch to compensate. That branch is also
untested (no test in `test_fetch.py` hits it, unlike every other error path
in the diff, which all have a matching test). Moving the constraint into the
model (`requests_per_minute: int = Field(default=10, gt=0)`) makes an invalid
config fail at `load_config()` — construction time, one place, pydantic's
error message — instead of at the first `run_ingest()` call with hand-written
text, and deletes the runtime check and its docstring rationale entirely.
**Fix:** `Field(gt=0)` on `RateLimits.requests_per_minute`; delete the guard
in `pipeline.py`.

### 3. [LOW/INFO] `_fetch`'s injectable `transport` parameter — DI for a single production caller
**Location:** `src/semianalyst/ingest/fetch.py` (`_fetch(..., transport: ...)`,
threaded from `fetch_url` down; only ever bound to `_transport` in prod).
This is real dependency-injection machinery — a parameter that exists
entirely for `tests/test_fetch.py`'s `_local_transport` — kept off the public
surface (`fetch_url` takes no transport arg), which is the right call
security-wise (no `_allow_insecure` flag reachable from prod code). A cheaper
alternative exists (`monkeypatch.setattr(fetchmod, "_OPENER", fake_opener)` in
tests, keeping `_fetch`'s signature caller-count-of-one and untouched by test
concerns) but it trades an explicit parameter for global mutable state across
19 tests using a shared `ThreadingHTTPServer` fixture — not obviously cheaper
once you count teardown correctness. Not blocking; noting only because the
brief asks for the cheaper alternative when complexity is flagged.

## What earns its keep (no complaint)
- The direct-URL cut is honored exactly — no HTML discovery, no scraping, no
  auto-crawl of the index `url` field. `documents = []` sources are cleanly
  skipped with a note naming the WS-3 deferral, not silently ignored.
- Size/redirect caps and the magic-byte check are hardcoded constants, not
  pushed into `config.toml` as new knobs nobody asked for — correctly resisted
  the urge to make everything configurable.
- 19 tests, no redundancy I could find: each transport behavior (scheme gate,
  mid-chain downgrade, redirect cap, relative-redirect resolution, streamed
  vs. declared size cap), each `run_ingest` behavior (skip, fault isolation ×2
  shapes, idempotent re-fetch, pacing, sidecar field shape, S1 collision), and
  one real E2E revision/supersession test — each maps to one behavior in the
  plan contract. The "empty documents skip" and "pacer called per request"
  cases named in my brief are both covered.
- `url_doc_id`'s truncate+hash-suffix logic isn't gold-plating — it's what
  keeps a long slug from later fail-louding against `DocId120` at extract
  time; it earns its place by avoiding a worse failure downstream.

## Risk others will miss (my angle)
**Silent long-running CLI with zero incremental feedback.** `run_ingest`
returns one `IngestReport` only after every configured document across every
source has been fetched, sequentially, with a `60/rpm`-second sleep between
each — at the default `rpm=10` a 30-document watchlist takes ~3 minutes with
literally nothing printed to the terminal until the final summary in
`cli.py:ingest()`. That's not a correctness bug and no reviewer on the
security or schema axis will flag it, but it's a real "is this shipped"
question: an operator staring at a hung-looking terminal for minutes is a
paper cut that shows up on first real use, not in any test. Cheapest fix if
it's judged worth doing at all: a per-document `typer.echo` inside the
`fetcher.fetch` loop in `cli.py` (or a callback param on `run_ingest`, thin
enough not to violate "CLI is thin") — not a blocker for this gate, but worth
a ROADMAP line if deferred.
