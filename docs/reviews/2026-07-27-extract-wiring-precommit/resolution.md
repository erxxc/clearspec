# Resolution — extract-wiring (precommit)

Merge of the reviewer opinions in this directory, written by the main session.
Rules: agreements highlighted; conflicts named with their cost and **never
averaged**; every named conflict records the human's decision and rationale.

**Base:** working tree @ `def696f`. **Suite at gate open:** 52 passed, 3 skipped.
**Suite after fixes:** **55 passed, 3 skipped** (+3 offline tests; the 3 skips are
the `@live` golden, injection, and E2E). The devils-advocate escalated/reframed
three findings; I treated its sharper readings as authoritative and the human
adjudicated the three genuine forks (Q1–Q3).

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | CONDITIONAL | No new injection/key-leak surface, but 3 gaps bake into the seam WS-2 reuses; `_ansi_safe` misses Unicode spoofing. |
| schema-purist | BLOCK | `doc_id`-only idempotency defeats the `file_sha256` revision-detection guarantee; no per-document fault isolation. |
| pragmatist-shipper | APPROVE | DoD met; `_ansi_safe` regexes redundant with the `_CTRL` catch-all; sidecar atomic-write over-built. |
| devils-advocate | (challenge) | The split reduces to one question; the *agreed* finding is the *weakest*; and all three missed that injection goes live **in this diff**. |

## Agreements (all reviewers concur)
- **Claim-integrity is intact.** `run_extract` does not bypass `build_result`/
  `validate.py`; the grounded `ExtractionResult` is persisted faithfully (grounding,
  relative-never-absolutized, unit normalization, `marketing_only`, `unknown`
  fail-safe all still apply). Verified by schema-purist and by the injection reviewer
  ruling out any sidecar→model path. **No action.**
- **All defects live in the NEW sidecar→Document handoff**, not the reused pieces.
- **Per-document fault isolation is missing** (injection #2 + schema-purist #3 agreed
  the line; see Conflict-adjacent note below on severity).

## Named conflicts (not averaged)

### Conflict 1 — the silent same-`doc_id`/new-`sha256` revision skip
- **Positions:** schema-purist BLOCKs — a re-ingested corrected PDF (same `doc_id`,
  new `sha256`) is bucketed `skipped` purely by `doc_id`, never comparing
  `file_sha256`, so the schema's named "how silent revisions are detected" guarantee
  is dead-on-arrival at the extract layer, and untested. Pragmatist APPROVEs — never
  engages it.
- **Cost of each side (devils, unaveraged):** BLOCK costs holding a *minimal-wiring*
  slice to fix a defect reachable only by a benign operator re-ingest and recoverable
  by hand. APPROVE costs shipping a **provenance tool** that, the first time an
  operator loads a correction, **silently serves stale claims while reporting
  success** — a violation of the one property the product exists to guarantee. The
  "note it and ship" middle was explicitly refused as dishonest.
- **Decision (human, Q1):** **Loud guard + defer.** `run_extract` classifies against
  `store.stored_doc_shas` (doc_id → file_sha256); same `doc_id` + changed bytes →
  `ExtractReport.revised`, surfaced loudly with operator guidance, **never** silently
  skipped; same-`doc_id` supersession is deferred and documented.
- **Rationale:** cheapest honest resolution — converts a silent correctness violation
  into a stated, loud limitation without pulling revision/supersession design into
  the slice.
- **Applied / proof:** `store.stored_doc_shas`, `run_extract` revision branch, CLI
  `REVISION (not extracted)` line; `test_source_revision_is_surfaced_not_silently_skipped`.
- **Accepted by:** erxxc (2026-07-27).

### Conflict 2 — `_ansi_safe`: keep vs delete
- **Positions:** pragmatist — the two ANSI/OSC/CSI regexes are redundant because the
  `_CTRL` catch-all already strips every byte that makes a sequence *live*; delete
  them. injection-attacker — `_ansi_safe` is security-load-bearing and *under*-reaches
  (Unicode bidi/zero-width sail through).
- **Devils reframe (verified):** not a real conflict — orthogonal axes. The security
  load rests entirely on the one `_CTRL` line (the two regexes are security-inert,
  cosmetic); AND Unicode spoofing (RLO/ZWSP/BOM) is genuinely uncovered. Both frames
  are half-right; the diff did the one move neither endorsed — ship the cosmetic half
  and mark the *whole class* RESOLVED.
- **Decision (human, Q2):** **Rescope + defer Unicode.** Reword the Class A note so
  RESOLVED covers ANSI/OSC/control escapes only; add a live Class A line for Unicode
  bidi/zero-width spoofing (OPEN). Keep `_ansi_safe` as-is (cosmetic regexes retained
  — harmless, tested); defer the Unicode code (inert on honest fixtures today).
- **Rationale:** honest scoping without burying the Unicode gap; no premature code for
  a threat no input can reach yet.
- **Applied / proof:** two CLAUDE.md bullets (escapes = RESOLVED; Unicode = OPEN).
- **Accepted by:** erxxc (2026-07-27).

## Devil's-advocate challenge
- **Question raised (§5):** "operator-fed" was doing dishonest double-duty as
  "content-trusted." This diff is the **first real model call on ingested,
  third-party-authored PDFs**, so prompt-injection via the PDF body is **live in
  WS-1**, not deferred to WS-2 — and the manifest's "zero Class A exposure" is false
  for that surface. The injection reviewer cleared it on a narrower question (do
  sidecar fields inject? — they don't).
- **Disposition (human, Q3): addressed.** CLAUDE.md's Class A preamble corrected —
  the injection surface is live *and defended* (`DOC_OPEN`/`DOC_CLOSE` + `validate.py`
  grounding + tests); only byte-FETCH is deferred; cross-document TRUST remains the
  genuine Class A deferral. Added `test_injection_wiring_offline` driving the hostile
  proposal through `ingest_file → run_extract → persist` (proves the wiring, not just
  the extractor).
- **Question raised (§2):** the *agreed* "no fault isolation" finding is the weakest —
  two broken framings (self-DoS; validate.py-isolation regression), overstated
  severity (idempotent re-run self-heals). True residual = bare traceback + sha256-
  order head-of-line blocking; an operability nit.
- **Disposition: fixed anyway.** Per-document `try/except` → `ExtractReport.errors`,
  batch continues; also catches the two-distinct-files-same-`doc_id` `IntegrityError`
  devils traced. Proof: `test_malformed_sidecar_is_isolated_not_a_batch_abort`.

## Residual risks accepted
- **Sidecar inverse identity** — same bytes re-ingested under a *different* `doc_id`
  last-write-wins the sidecar (no merge/signal). Named Class A ("Sidecar identity
  binding"); revisit at the WS-2 trust gate.
- **Blob content-hash not re-verified at read** (`read_raw_docs` trusts the filename)
  — accepted for the single-writer operator MVP; named Class A; revisit at WS-2
  (concurrent/adversarial writers).
- **Unicode bidi/zero-width display spoofing** — named Class A (OPEN); inert today;
  close when live extraction feeds `report`.
- **Same-`doc_id` revision supersession** — deferred; `revised` is surfaced loudly and
  the operator re-ingests under a new `doc_id`; revisit when revision-handling is
  scoped as its own slice.
- **`extraction_model` provenance stamp is lossy/unescaped** (schema-purist risk) —
  accepted; a free-text field, 48-bit hash prefix is fine for grep. Revisit if a
  prompt name ever contains `@`/`+`, or an audit needs to un-concatenate it exactly.
- **Sidecar atomic write "over-built"** (pragmatist #2) — kept for crash-safety
  consistency with `store_raw`; the cosmetic `.meta.meta.partial` tmp-name artifact
  it cited **was fixed** (`with_name(... + ".partial")`).

## Outcome
**Proceed** — Conflict 1 (Q1), Conflict 2 (Q2), and the devils-advocate injection-
scope challenge (Q3) adjudicated and **applied**; fault isolation fixed; residuals
named in CLAUDE.md's Class A list with revisit triggers. Suite **55 passed, 3
skipped**. Ready to commit the WS-1 workstream — code + tests + doc updates + this
gate run directory — as one commit. `@live` proof (`uv run pytest --run-live`)
remains the standing ENFORCE anchor to run before relying on the wiring.
