# Resolution — fetcher WS-2b precommit gate

- **Date:** 2026-08-20 (opinions 2026-08-19/20; adjudication + conditions applied 2026-08-20)
- **Target:** `workstream.diff` (= `git diff 42a81ff..4d0547e` on `feat/ws2b-fetcher`)
- **Verdicts:** injection-attacker CONDITIONAL · schema-purist CONDITIONAL ·
  pragmatist-shipper CONDITIONAL · devils-advocate CONDITIONAL ("right in
  outcome, wrong in composition")
- **Outcome: PROCEED — all adjudicated conditions applied in-branch before commit.**
- **Adjudicator:** the human operator (four conflicts, each decided explicitly;
  none averaged). The orchestrator independently re-verified the
  devils-advocate's resurrection trace and the purist's collision trace in code
  before adjudication.

## Agreements (all reviewers, unchallenged)

- The per-hop HTTPS gate is airtight as shipped: scheme validated BEFORE every
  transport call including redirect hops; a mid-chain downgrade is refused with
  the downgraded target never requested; the redirect cap is exact; the public
  `fetch_url` has no override path. No API-key or prompt-injection surface
  exists in this diff.
- doc_id derives from the OPERATOR-typed requested URL — a hostile server
  cannot steer identity via redirects.
- Sidecar shape parity is exact, field-for-field, against `ingest_file`'s nine
  keys. Boundary purity holds (no store/sqlite imports; stdlib-only fetch;
  policy never leaks into `foundry.py`; CLI stays display-only).
- Test economy is good: 19 tests, each mapping to one plan-contract behavior,
  no redundancy found.
- Docs drift is real and blocking: README/ROADMAP/CLAUDE.md all still called
  the fetcher a stub.

## The gate's two real discoveries

1. **doc_id collision (schema-purist HIGH, sharpened by devils-advocate).**
   `url_doc_id` slugged host+path only, so two distinct configured URLs
   differing only by query string collapse into one doc_id — and the fold then
   treats them as an honest revision, silently superseding each other's claims.
   Worse, the docstring cited `possible_slug_collision` as the safety net,
   which is FALSE — that advisory guards entity slugs, not doc_ids. The DA
   showed the purist's own in-run preflight remedy cannot catch the realistic
   cross-run case (second URL added to config weeks later), and the
   orchestrator found the DA's own cross-run sidecar-scan remedy also fails as
   specified: the sidecar stores the FINAL URL, so a scan cannot distinguish an
   honest revision from a collision without a sidecar semantics change.
2. **forget-resurrection (devils-advocate — the shared blind spot; missed by
   all three angle reviewers).** `forget` quarantines sidecar+artifact but
   leaves the blob (by design); a routine watchlist re-run then re-creates the
   sidecar with no S1 collision (the original was moved away), reports it as an
   innocuous `unchanged` line, and the next extract restores the document as an
   ordinary unknown doc_id. A retraction that reports success and silently
   un-happens on the next scheduled command — the mirror image of the WS-2a
   gate's fail-loud forget post-condition. Verified line-by-line by the
   orchestrator before adjudication. Zero prior test coverage.

## Conflicts and adjudication

1. **doc_id identity fix** — hash-suffix always vs. cross-run sidecar scan vs.
   docstring-fix-only. **ADJUDICATED: unconditional hash suffix.** `url_doc_id`
   now always appends `_` + sha256(full url)[:8]; identity is the exact
   operator-typed URL string; closes in-run AND cross-run collisions with zero
   new state. Cost accepted: less readable doc_ids; a trivial operator retype
   mints a new identity (operator-controlled and visible, unlike the silent
   collapse). No live data affected (config carried zero `documents` entries).
   The false docstring cross-reference is corrected and its wrongness recorded
   in the new docstring.
2. **forget-resurrection** — refuse implicit revival vs. accept-by-design.
   **ADJUDICATED: refuse implicit revival.** `run_ingest` builds the set of
   quarantined doc_ids once per run and lands any watchlist match in `errors`
   with a loud fixed-text reason. `ingest-file` remains the EXPLICIT revival
   path (already anticipated by `_quarantine_dest`'s numbered-sibling design).
   Named test: `test_forget_then_ingest_refuses_revival`.
3. **slow-loris wall-clock deadline** — fix now vs. named-trigger deferral.
   **ADJUDICATED: defer with named trigger** (per the DA's scope-discipline
   argument: a batch-DoS of the operator's own tool from an operator-curated
   HTTPS watchlist). Recorded in CLAUDE.md deferred list + ROADMAP; trigger: a
   live run demonstrably hangs, or the watchlist grows beyond a handful of
   hosts.
4. **`IngestReport.errors` key semantics** — unify on requested_url vs. typed
   discriminator vs. leave. **ADJUDICATED: unify on requested_url.** S1
   collision errors now report `outcome.requested_url` like every other entry;
   the colliding doc_ids remain in the reason text.

## DA challenges accepted without conflict

- **SSRF-via-redirect (injection #2):** the DA demonstrated the proposed
  resolved-address block would have to live above the transport seam, where it
  breaks the entire local-server test suite (every test targets 127.0.0.1) or
  forces the exact test/prod bypass flag the design forbids. Both reviewers'
  positions converge on written acceptance — now recorded in CLAUDE.md's
  residual-risks list with trigger "any non-operator-supplied URL source."
- **Injection #3 (`Document.url` is now server-controlled):** accepted as a
  documentation-scope condition; `document.url` added to CLAUDE.md's OPEN
  display-safety note alongside `quote_span`/`stated_caveats`.
- **Purist #3 (sidecar `url` semantics diverge by producer):** documented in
  CLAUDE.md's sidecar-handoff section (same shape, documented divergence).

## Conditions applied (all in-branch, before commit)

1. `url_doc_id` unconditional sha256[:8] suffix + honest docstring
   (`ingest/pipeline.py`); tests updated + `test_url_doc_id_distinct_urls_never_collide`.
2. Quarantine revival guard: `_retracted_doc_ids` + refusal in `run_ingest`
   (`ingest/pipeline.py`); `ingest_file` docstring names itself the explicit
   revival path; `test_forget_then_ingest_refuses_revival`.
3. `FetchOutcome.__post_init__` enforces success XOR error (`ingest/base.py`);
   `run_ingest` now trusts the invariant; `test_fetch_outcome_success_xor_error`.
4. `IngestReport.errors` unified on requested-URL keys (`ingest/pipeline.py`);
   collision test updated.
5. `requests_per_minute`/`max_concurrency` moved to pydantic `Field(gt=0)`
   (`config.py`); hand-rolled `rpm <= 0` guard deleted;
   `test_rate_limit_must_be_positive` (pragmatist #2).
6. Docs de-staled: README quickstart + closing pointers (incl. the stale v3
   schema reference), ROADMAP current-state table + WS-2 section, CLAUDE.md
   module map (pragmatist #1).
7. CLAUDE.md: forget's mirror-image revival guard; sidecar `url` semantics;
   `document.url` in the OPEN display note; SSRF-via-redirect residual;
   slow-loris deferral with trigger.

## Deferred at this gate, with named triggers

- **Wall-clock fetch deadline** (slow-loris) — trigger: a live run
  demonstrably hangs, or the watchlist grows beyond a handful of hosts.
- **SSRF-via-redirect resolved-address check** — accepted residual; trigger:
  any non-operator-supplied URL source.
- **Incremental CLI ingest feedback** (pragmatist #3, self-scoped
  non-blocking) — trigger: a real multi-document run feels hung at 60/rpm
  pacing.

## Verification

- Offline suite after conditions: **142 passed, 3 skipped** (was 138/3 at the
  reviewed ref; +4 named gate tests).
- Live suite re-run after conditions (`--run-live`, keychain key): **145
  passed, 0 skipped** — the live anchor is the true gate; a green offline run
  never stands in for it.
