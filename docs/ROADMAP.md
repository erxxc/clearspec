# ROADMAP — semianalyst

**This file is the source of truth for _what is built, what is open, and what
order we build it in._** It does not restate architectural rules or decision
history — those live where they are authoritative:

- **Architectural rules + the Class A deferred-decision definitions:** `CLAUDE.md`.
  This file _references_ Class A items (K/G/H/…) by name; it never redefines them.
- **Per-gate decisions and their rationale:** `docs/reviews/<date>-<workstream>-<plan|precommit>/resolution.md`.
- **The data model:** `schema/extraction_schema_v3.yaml` (current).

Keep this file honest on every workstream boundary: when a slice lands, move its
row from *Open* to *Built*; when a Class A item is retired, strike it here and in
CLAUDE.md in the same commit.

_Last updated: 2026-08-20._

---

## Current state — the pipeline is wired end to end (WS-1 + WS-2); direct-URL network fetch is live

| Stage | State | Notes |
|---|---|---|
| `ingest/` network fetch | **BUILT + tested (WS-2b)** | `FoundryFetcher.fetch` over per-source `documents = [...]` URLs; `fetch_url` HTTPS-only at every redirect hop (no override), redirect cap 5, streamed 50MB cap, PDF magic; doc_id = requested-URL slug + unconditional sha256[:8] suffix (exact URL string is identity); sidecar from watchlist fields (final post-redirect URL recorded for audit); rate-paced; quarantined doc_ids refused, never silently revived. Sources without `documents` are skipped (HTML discovery → WS-3). The **operator path** (`ingest_file`) is unchanged. |
| `extract/` extractor | **BUILT + tested** | `AnthropicExtractor`, `validate.py` grounding, versioned prompts, offline golden (recorded `llm_response.json`) + `@live` anchor. |
| `extract/` orchestration (`run_extract`) | **BUILT + tested (WS-1)** | sidecar → Document → extractor → `persist_extraction`; idempotent by (doc_id, file_sha256); same-doc_id/changed-bytes surfaced as a revision; per-doc fault isolation. |
| `store/` persist + reconcile | **BUILT + in prod** | now invoked by `run_extract`; `stored_doc_shas` drives idempotency. |
| `analyze/` corroboration | **BUILT + tested** | Derive-on-read, tolerance grouping, tier-blind `favored_tier`. |

Offline suite (2026-08-18, re-verified on `main`): **57 passed, 3 skipped** (the 3
skips are the `@live` golden, injection, and E2E). WS-1 merged to `main` via PR #2.
**Live anchor re-proven 2026-08-18: full `--run-live` suite 60 passed, 0 skipped.**
The live golden had grown flaky (~4/5 failing): the model includes the entity's
canonical name in `aliases` inconsistently. Fixed by pinning `name` into `aliases`
in `extract/validate.py` (validation is the guarantee, not the prompt); 25+
consecutive clean live runs after the fix.

---

## Prioritized workstreams

### WS-1 — Wire `run_extract` (extract E2E on operator-fed raw docs) — **BUILT & MERGED (PR #2; gate passed 2026-07-27, conditions applied)**

Turns three built components (extractor, persist, analyze) into a working
pipeline with **zero network**. Operator hand-feeds a curated PDF → `extract` →
`report`.

- **Value-per-risk:** highest. Makes the product demoable; exercises
  `persist_extraction` in production for the first time.
- **Class-A-free by construction:** an operator hand-feeding one curated PDF is
  still the curated-fixture trust boundary — no hostile document reaches
  `persist_extraction`, so none of the deferred decisions are forced yet.
- **Forces one directional decision up front:** the ingest→extract Document
  handoff contract (see *Open directional decisions*). Blocked on human input.

**Pull-forward (unconditional, lands in this slice):** *report display safety* —
`cli.py:report()` currently echoes DB-derived strings with no output encoding. It
is the first thing hostile proposal content hits, and unlike the rest of Class A
it is not entangled with a design fork. Sanitize (strip ANSI/OSC) and retire it
from the Class A list here + in CLAUDE.md.

**Definition of done:**
- [x] Decide + document the ingest→extract Document handoff. **Decided
  2026-07-27: sidecar manifest + extract-time Document** (see *Sequencing decision
  log* and CLAUDE.md "The ingest→extract handoff is a provenance sidecar").
- [x] `run_extract` reads pending raw docs (`ingest.read_raw_docs`), runs
  `AnthropicExtractor` with the configured `PromptVersion`, and calls
  `persist_extraction`. Idempotent via `store.stored_doc_shas` (doc_id +
  file_sha256; revision surfaced, not silently skipped). Extractor is injectable so
  the chain runs offline. No business logic in `cli.py`.
- [x] Operator ingest path (`ingest.ingest_file` + thin `ingest-file` command)
  writes blob + sidecar, so the pipeline is usable with zero network.
- [x] `report()` output is encoding-sanitized (`cli._ansi_safe`). Per the gate (Q2),
  Class A "report display safety" is **rescoped**: ANSI/OSC/control escapes RESOLVED;
  a new **Unicode bidi/zero-width spoofing** line stays OPEN in CLAUDE.md.
- [x] New E2E test (`tests/test_pipeline_e2e.py`): `ingest_file` → `run_extract`
  (offline via `ReplayModelClient`) → store counts + `report` assessments, plus an
  idempotent-re-run check and a sanitizer test. `@live` E2E variant behind
  `--run-live`.
- [x] README + `config.toml` drift fixed; `extraction_model` stamp records
  `model + prompt.name@sha256[:12]`.
- [x] Offline suite green (**55 passed, 3 skipped** after the gate fixes; the 3
  skips are the `@live` extraction + injection + E2E). Live extraction remains the anchor.
- [x] **Adversarial precommit gate run** (`docs/reviews/2026-07-27-extract-wiring-precommit/`).
  Verdicts injection-attacker CONDITIONAL / schema-purist BLOCK / pragmatist APPROVE
  → devils-advocate challenge → `resolution.md`. Three forks adjudicated by the human
  (Q1 loud revision guard; Q2 rescope display-safety + defer Unicode; Q3 correct the
  injection-live-in-WS-1 framing + add a wiring injection test) and applied; per-doc
  fault isolation added. Gate outcome: **proceed**.

### WS-2 — Live ingest (network fetch) + Class A trust model — **COMPLETE: WS-2a AND WS-2b BUILT, both precommit gates passed with conditions applied**

Status: step 1 (sparsity grounding + vendor case-fold) shipped as its own PR;
step 2 (WS-2a trust hardening) built on `feat/ws2a-trust`, verified by appsec
review + operator UAT + the named hostile suite (23 cases incl. honest-path
guards), and passed the precommit swarm gate
(`docs/reviews/2026-08-18-live-ingest-precommit/` — 3× conditional + a
devils-advocate challenge that found the fold-order divergence and the silent
non-retraction hole; all adjudicated conditions applied before commit: fold
replays `_extracted_at` chronology, forget post-condition, sidecar binding as
consistency-not-authentication, JSON CHECKs sized to accumulated escaped worst
case + alias_overflow at merge, shared `textnorm.fold`, honest fixtures added).
Suite after WS-2a: offline 119/3, live 122/0.

Step 3 (WS-2b fetcher) BUILT on `feat/ws2b-fetcher` and passed its precommit
swarm gate (`docs/reviews/2026-08-19-fetcher-precommit/` — 3× conditional +
devils-advocate; four conflicts human-adjudicated, all conditions applied
before commit): **unconditional sha256[:8] doc_id suffix** (closes the
cross-run distinct-URL/same-slug collision the in-run preflight could never
catch — the exact operator-typed URL string is identity); **quarantine revival
guard** in `run_ingest` (the DA's blocker all three angle reviewers missed:
`forget` + a routine watchlist re-run silently resurrected the retracted doc;
now refused loudly, `ingest-file` stays the explicit revival path);
`IngestReport.errors` unified on requested-URL keys; `FetchOutcome`
success-XOR-error enforced in `__post_init__`; `requests_per_minute` moved to
a pydantic `Field(gt=0)`; docs de-staled. Deferred at the gate with named
triggers: **wall-clock fetch deadline** (slow-loris; per-read timeout re-arms —
trigger: a live run demonstrably hangs, or the watchlist grows beyond a
handful of hosts); **SSRF-via-redirect to internal hosts** accepted as a
residual (operator-curated watchlist; a resolved-address block would have to
sit above the tested transport seam and break the local-server suite —
trigger: any non-operator-supplied URL source); **incremental CLI ingest
feedback** (trigger: a real multi-document run feels hung at 60/rpm pacing).

Trust-model design gate run at `docs/reviews/2026-08-18-live-ingest-plan/`
(3× conditional + devils-advocate challenge; four forks adjudicated by the
human — see `resolution.md`, which is authoritative). Build order:

1. **Standalone fix on `main` (pre-WS-2a, live bug):** `conditions.sparsity` is
   model-proposed and ungrounded while `corroborate.py`'s suspect-exclusion
   already depends on it — fix via quote-span sparse-vocabulary grounding that
   fails toward suspect, plus the vendor case-fold dedup fix (one doc's
   `"TSMC"`/`"Tsmc"` currently makes two entities).
2. **WS-2a — trust hardening (zero network):** extraction **artifact + refold**
   (per-doc validated extraction persisted beside the raw blob; DB = rebuildable
   fold; ships `forget <doc_id>` + `db rebuild` + revision supersession — this
   also retires WS-1's deferred same-doc_id supersession); hardened persisted
   **conflict table** (schema v4 + migration 0004; values bounded ≤120 and
   display-sanitized; `reconcile_entity` rewritten read-compare-write with
   offender doc_id); full content bounds **with mirrored SQLite CHECKs**; G1
   alias grounding + G3 collision refusal; **H1 publisher-diversity floor**
   (normalized publisher); group-key normalization (`metric`/`unit`/`publisher`)
   + advisory `possible_split_metric`; entity name/vendor presence-grounding;
   S1 sidecar binding + S2 blob-hash re-verify; Unicode Cf display stripping;
   J advisory flag. Acceptance: named hostile suite **plus honest-corpus
   regression** (golden verdicts unchanged except approved diffs) **plus flag
   budget** (≤1 new flag per honest assessment).
3. **WS-2b — fetcher (BUILT, gate passed 2026-08-20):** direct document URLs
   only (HTML discovery → WS-3); HTTPS-only re-validated per redirect hop,
   redirect/size caps, PDF magic bytes, config rate limits; URL-slug+hash
   doc_id (safe now that supersession exists); sidecar from operator watchlist
   fields; local-server tests only.

**Deferred with named triggers** (from the gate): **H2** all-tier-3 confidence
cap — trigger: watchlist carries ≥2 distinct tier-3 publishers for one metric;
**B1** baseline surface-form binding — cut (near-empty true-positive surface);
trigger: a demonstrated misattributed-measurement case; **controlled metric
vocabulary** — trigger: real corpus shows split groups normalization can't
close; **identity citation slots** — trigger: schema v5. Precommit gate to run
on the WS-2a diff.

### Deferred (correctly) — revisit on trigger

- **Analyze decision A — absolute tolerance.** One relative ±10% ruler is applied
  to both ratios and absolute claims. Moot until two absolute claims share a
  group (today the only absolute claim is a singleton). Revisit trigger: a second
  absolute claim groups. (Decision B was resolved — B2 applied; see
  `docs/reviews/2026-07-20-analyze-precommit/resolution.md`.)

---

## Open directional decisions (human-owned)

- **WS-1 / ingest→extract Document handoff contract** — *RESOLVED 2026-07-27:
  sidecar manifest + extract-time Document* (see decision log below). No open
  question remains.
- **Analyze decision A** — deferred with a named trigger (above).

---

## Sequencing decision log

- **2026-08-18 — WS-2 plan gate: four forks adjudicated by human.** (1)
  Retraction/supersession: **artifact + refold** adopted over flag-only (a
  poisoned store must be fixable; URL-slug doc_id otherwise makes revisions
  permanently unextractable). (2) Conflict record: **durable hardened table**
  over log-only (log-only cannot carry the offered value without violating
  validate's never-log-raw-model-text invariant). (3) Trims accepted: defer H2,
  cut B1 (keep the B2 bound), normalization-now/vocabulary-later. (4) Grounding:
  sparsity fix ships as a standalone bug-fix on `main` first; bounds get DDL
  parity. Full record: `docs/reviews/2026-08-18-live-ingest-plan/resolution.md`.
- **2026-07-27 — extract-wiring before live-ingest (confirmed by human).**
  Context: two stubs (ingest fetch, `run_extract`) block the E2E loop; persist +
  analyze already built. Options: (1) wire `run_extract` first, (2) live ingest
  first. Decision: **(1)**. Consequence: product becomes demoable on operator-fed
  input with zero network and zero Class A exposure; live ingest follows as a
  gated workstream once the chain is proven end-to-end on trusted input.
- **2026-07-27 — ingest→extract handoff: sidecar + extract-time Document
  (human).** Context: a bare `data/raw/<sha256>` blob carries no trust metadata,
  so something must record it and tell `extract` what's pending. Options:
  (A) sidecar JSON on disk + Document built at extract time; (B) a `pending_raw` DB
  table; (C) ingest-time Document with a status lifecycle. Decision: **(A)**.
  Consequence: no migration; ingest stays DB-free (matches "raw blobs are ingest's
  concern"); `persist_extraction`'s reviewed insert contract is untouched; the
  sidecar is the fetch-source-agnostic seam WS-2's network fetcher reuses. Cost
  accepted: "what's pending" lives in scattered files, not one queryable table —
  fine at operator scale; revisit if WS-2 needs queryable ingest state.
