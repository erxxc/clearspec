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

_Last updated: 2026-08-18._

---

## Current state — extract E2E is wired (WS-1); network fetch (WS-2) is the one remaining stub

| Stage | State | Notes |
|---|---|---|
| `ingest/` network fetch | **STUB (WS-2)** | `FoundryFetcher.fetch` → `NotImplementedError`; `run_ingest` reports watchlist sources *skipped*. The **operator path** (`ingest_file` + `store_raw` + provenance sidecars) is BUILT + tested. |
| `extract/` extractor | **BUILT + tested** | `AnthropicExtractor`, `validate.py` grounding, versioned prompts, offline golden (recorded `llm_response.json`) + `@live` anchor. |
| `extract/` orchestration (`run_extract`) | **BUILT + tested (WS-1)** | sidecar → Document → extractor → `persist_extraction`; idempotent by (doc_id, file_sha256); same-doc_id/changed-bytes surfaced as a revision; per-doc fault isolation. |
| `store/` persist + reconcile | **BUILT + in prod** | now invoked by `run_extract`; `stored_doc_shas` drives idempotency. |
| `analyze/` corroboration | **BUILT + tested** | Derive-on-read, tolerance grouping, tier-blind `favored_tier`. |

Offline suite (2026-08-18, re-verified on `main`): **55 passed, 3 skipped** (the 3
skips are the `@live` golden, injection, and E2E). WS-1 merged to `main` via PR #2.

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

### WS-2 — Live ingest (network fetch) + Class A trust model — **AFTER WS-1, gated**

Implements `FoundryFetcher.fetch` (HTTPS-only, rate-limited, idempotent via
`store_raw`) and `run_ingest`. **The moment fetch lands, the entire Class A set
goes live simultaneously** — so this workstream MUST open with a *trust-model
design gate* (swarm review) that resolves the deferred decisions as a named set,
not piecemeal. Class A items (authoritatively defined in CLAUDE.md): **K** (tier
precedence / `favored_tier` suspect-exclusion), **G** (alias-union gating), **H**
(tier-diversity floor for `corroborated`), resolved-baseline poisoning,
identity-field conflict, baseline content-bound, **I/J** (persisted conflict
records, slug-collision strength), plus the WS-1-gate additions — **sidecar
identity binding**, **blob content-hash not re-verified at read**, and **Unicode
bidi/zero-width display spoofing**. Adversarial suite must be a *named hostile
suite*, never the honest acceptance golden.

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
