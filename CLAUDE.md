# CLAUDE.md — architectural rules for semianalyst

Future sessions MUST respect these. They encode decisions that are expensive to
reverse once data and prompts accumulate.

## The data model is the source of truth
The schema defines every structure; pydantic models (`store/models.py`) and the
SQLite DDL (`store/migrations/`) are both derived from it. Change the schema
first; regenerate the models and add a migration — never the other way around.
**`schema/extraction_schema_v3.yaml` is current**; `_v1`/`_v2` are retained
unedited. v2 added per-attribute grounding (`entity.attribute_citations`) and a
fail-safe `unknown` `citation.location_type`; v3 added `weakly_corroborated` as a
`corroboration.status` verdict value (a group that agrees within tolerance but has
<2 non-suspect members — a clean number + an honestly-disclosed sparsity number)
and made corroboration **derive-on-read, not persisted** — migration 0003 dropped
the per-row `corr_status`/`corr_related_claim_ids` columns (a per-group verdict has
no honest per-row home) and dropped the `cmp_baseline_entity` FK.

## The claim is the atomic unit — and its integrity rules are non-negotiable
- **Every extracted value cites a source span** — code-enforced, not trusted to
  the model. `extract/validate.py` drops any claim whose `citation.quote_span`
  isn't a (whitespace-normalized) substring of the source, and nulls any entity
  attribute whose `attribute_citations` entry isn't grounded (v2). The LLM output
  is a PROPOSAL; validation is the guarantee. `location_type` fails safe to
  `unknown` under flat-text extraction (never laundered to `body`).
- **Relative claims are never converted to absolutes.** Store the ratio and the
  baseline reference (`comparison.is_relative`, `comparison.baseline_entity`) so
  the distortion stays visible. "2.5x faster" is stored as `2.5` + baseline, not
  a fabricated absolute.
- **source_tier is set at the document level and inherited by claims** (conf=1 >
  foundry=2 > vendor=3). It weights corroboration; do not drop it.
- A sparsity+competitor claim is `completeness=marketing_only` unless the
  competitor number is also sparse. One entity per real thing (resolve aliases
  before insert).

## The CLI is thin — the library is the product
`cli.py` parses arguments and calls library functions. **Zero business logic**
lives there — no loops, queries, or transformations. A web UI will later sit on
the same library, so every capability must be reachable as a library call
(`store.init_db`, `run_ingest`, `store.report_counts`, ...), not buried in a
command handler.

## `store/` is the only module that touches SQLite
Nothing else imports `sqlite3` or writes SQL. `store/db.py` owns the
nested-pydantic ↔ flat-row mapping. All writes are parameterized — no value is
ever interpolated into SQL text. Schema changes ship as new numbered migrations
(`NNNN_*.sql`); **never edit an applied migration in place.** (Raw document blobs
live on the filesystem under `data/raw/`, content-addressed — that is ingest's
concern, not the database's.)

**Persistence + reconciliation (`store.persist_extraction`).** Inserts a document
(plain `INSERT`, fail-loud on a duplicate `doc_id`), reconciles each entity
(`reconcile_entity`: union aliases, fill NULL node/chip attributes, **never**
overwrite a non-null one), and inserts claims under a doc-scoped `claim_id`
(`{doc_id}:{id}`) so two docs' claims coexist. `cmp_baseline_entity` has no FK (a
baseline may be cross-document or dangling; analyze flags `unresolved_baseline`).
There is **no persisted per-row corroboration verdict** — migration 0003 dropped
the `corr_status`/`corr_related_claim_ids` columns. Corroboration is a per-GROUP
fact analyze recomputes *derive-on-read* over the whole store on every `report`;
the `AnalysisReport` is the sole source of truth. The `Claim` model keeps a
`corroboration` field with a neutral default for extraction-output shape stability,
but `insert_claim` never writes it and nothing reads it back. Do not re-add a
persisted per-row verdict without settling the per-group-fact-in-a-per-row-home
question (decision B2, analyze GATE-2 resolution).

**Cross-document TRUST is DEFERRED to the live-ingest workstream (Class A).**
Nuance corrected at the WS-1 gate (2026-07-27): the prompt-injection SURFACE is
already live — `run_extract` calls the real model on operator-ingested,
third-party-authored PDFs (the tool's whole purpose is semi-adversarial vendor
marketing), so a hostile PDF body reaches the model *in production today*. That
surface is DEFENDED, not deferred: the `DOC_OPEN`/`DOC_CLOSE` DATA delimiter, the
`validate.py` per-document grounding (fabricated/exfil claims dropped), and the
injection tests (`test_injection_wiring_offline` through the real wiring +
`test_injection_live` against the real model) are the guarantee. Only the network
FETCH of the bytes is deferred to WS-2. What remains genuinely deferred is
cross-document TRUST — no single curated/operator-fed document can exercise it,
and no hostile document can corrupt *cross-document* reconciliation or the
corroboration verdict yet. When live ingest lands, these decisions must be made
and enforced with a *named adversarial suite* (never the honest acceptance golden):
- **K** — does a strictly-higher-trust document ever override a non-null attribute,
  or only race a null one? (current: first-non-null-wins, tier-blind.) This also
  governs `favored_tier`: it currently ships **tier-blind** (`min` over *all*
  contradiction members, suspects included) — a sparsity flag does NOT override the
  tier ordering. Whether a suspect member should be excluded (letting sparsity
  demote a tier) is part of K, unbuilt.
- **G** — alias-union gating (a tier-3 doc can currently inject any alias string).
- **H** — a **status-level** tier-diversity floor for `corroborated` (stop tier-3
  flooding; the MVP has no floor, one doc per tier).
- **Resolved-baseline poisoning** — a hostile doc setting `baseline_entity` to a
  real, already-stored competitor entity (unvalidated; P2 only flags *dangling*).
- **Identity-field conflict** — on entity merge, `reconcile_entity` unions
  aliases/attribute_citations and fills nulls, but `vendor`/`name`/`entity_type`
  are frozen by the *first* document; a later document's differing values are
  dropped with no signal. A typo'd vendor silently conflates two real things under
  one `entity_id`. No conflict detection built.
- **Sidecar identity binding** (named at the WS-1 gate) — the ingest sidecar has no
  invariant tying content identity to document identity. Same doc_id + CHANGED bytes
  is now surfaced loudly (`run_extract` → `ExtractReport.revised`, never a silent
  skip), but same-doc_id re-extraction/supersession is deferred. The inverse is
  unguarded: the SAME bytes re-ingested under a DIFFERENT doc_id last-write-wins the
  `<sha256>.meta.json` sidecar (`write_sidecar` overwrites), clobbering the first
  ingest's provenance with no merge or signal — a sibling of Identity-field conflict
  at the sidecar layer.
- **Blob content-hash not re-verified at read** — `read_raw_docs` trusts the sidecar
  FILENAME as the sha256 and never recomputes the blob's hash; the only real hash is
  computed at `store_raw` write time. Fine for the single-writer operator MVP;
  matters once WS-2 introduces concurrent/adversarial writers to `data/raw/`.
- **Baseline content-bound** — post-0003 `cmp_baseline_entity` is unconstrained
  TEXT (the FK drop removed the shape guard too, not just the existence guard). No
  length/byte-content bound on it or on free-text `metric`.
- **Report display safety (ANSI/OSC/control escapes)** — RESOLVED 2026-07-27 (WS-1).
  `cli.py:report()` sanitizes every DB-derived display string (`entity_id`,
  `aliases`, `metric`, `baseline_entity`) through `cli._ansi_safe`, which strips
  ANSI/OSC/control-escape sequences (the load rests on the `_CTRL` catch-all; the
  named OSC/CSI patterns only clean inert printable residue). Terminal output
  encoding lives at the CLI edge deliberately (a web UI would HTML-escape instead),
  so it is not a shared library capability. Covered by
  `test_report_display_is_ansi_sanitized`. **Scope is escapes only** — see the next
  item for the Unicode half, which is NOT closed.
- **Report display safety (Unicode spoofing)** — OPEN. `_ansi_safe` does NOT touch
  Unicode bidirectional-override / zero-width codepoints (U+202A–202E, U+2066–2069,
  U+200B, U+FEFF): they sit above `\x9f` and render natively in a terminal, so
  proposal-controlled `metric`/`entity_id`/alias content can still visually reorder
  or hide text a human reads on `report` (Trojan-Source class) with no escape byte.
  Inert on honest fixtures today; close it when live extraction feeds `report`.
- **I/J** — persisted conflict records; slug-collision detection strength.
`validate.py` enforces a per-DOCUMENT boundary only; cross-document trust is Class A.

## Prompts and the schema are versioned artifacts, not edited in place
A prompt change means a NEW file (`extract_foundry_v2.md`), so every extraction
run stays tied to the exact prompt bytes (`PromptVersion.sha256`) and model that
produced it. Same for the schema: `_v2.yaml`, not an edit to `_v1`. Editing a
released version silently invalidates the provenance of prior runs.

## Ingestion is idempotent
Raw docs are keyed by sha256 under `data/raw/`. Re-fetching unchanged bytes is a
no-op; a changed hash is a new file (this is how silent revisions of the same URL
are detected — see the schema's `file_sha256`).

## The ingest→extract handoff is a provenance sidecar (decided 2026-07-27, WS-1)
Each raw blob at `data/raw/<sha256>` has a sidecar `data/raw/<sha256>.meta.json`
carrying exactly the Document-construction metadata ingest knows (`doc_id`,
`title`, `publisher`, `doc_type`, `source_tier`, `url`, `publish_date`,
`ingest_date`, `file_sha256`) — **not** `extraction_model`, which `run_extract`
stamps at extraction time. **Whatever produces the bytes writes the same sidecar
shape** — the operator path `ingest.ingest_file` today, WS-2's network fetcher
later — so `extract` stays fetch-source-agnostic. The `Document` row is created at
**extract** time (`persist_extraction` inserts it, unchanged), not at ingest.
`run_extract` classifies each sidecar against `store.stored_doc_shas` (doc_id →
file_sha256): unknown doc_id → extract; same doc_id + same bytes → idempotent skip;
same doc_id + CHANGED bytes → a source revision, surfaced loudly in
`ExtractReport.revised` (never silently skipped) with supersession deferred. Each
document is fault-isolated — one bad sidecar lands in `ExtractReport.errors` and the
batch continues. Alternatives considered and rejected for the MVP: a `pending_raw`
DB table (needless migration; ingest stays DB-free) and an ingest-time Document with
a status lifecycle (would split the reviewed `persist_extraction` contract). See
`docs/ROADMAP.md`.

## Secrets never land in the repo
The extraction model name lives in `config.toml`; the API key is read from the
environment (`ANTHROPIC_API_KEY`) at call time and is never committed. `data/` is
gitignored in full.

## Module map
- `ingest/`  — fetchers + content-addressed raw storage + provenance sidecars
  (`ingest_file` operator path live; network fetch: WIP/WS-2)
- `extract/` — raw doc → schema records via a versioned prompt; `run_extract` wires
  ingest (sidecar) → extractor → `persist_extraction`
- `store/`   — SQLite persistence + entity reconciliation; sole DB owner
- `analyze/` — cross-source corroboration + divergence (v1: tolerance grouping,
  suspect members excluded from the corroborated count, tier-blind `favored_tier`
  on contradictions; derive-on-read, read-only over `store`)
- `cli.py`   — thin argument layer over the above

## Testing (ENFORCE posture)
`tests/` uses a golden-fixture harness: `tests/fixtures/<doc_id>/raw.pdf` +
`expected.json`, diffed against extractor output. The **real model is the
anchor**: `@live` tests (`test_golden_live`, `test_injection_live`) run the actual
extractor and are the true gate — `uv run pytest --run-live` (with
`ANTHROPIC_API_KEY`) is what proves the extractor works. A plain `uv run pytest`
never fabricates model output: the offline golden replays a real, provenance-
stamped `llm_response.json` (skips until recorded via `--run-live --record`), and
`test_validate.py` covers the validation pipeline deterministically. Never let a
green offline run stand in for live coverage. Store/ingest/prompt have their own
real tests.

## Review gates (swarm)
Significant workstreams pass an adversarial review gate before commit: biased
reviewers in `.claude/agents/` (`injection-attacker`, `schema-purist`,
`pragmatist-shipper`) each attack from one angle, `devils-advocate` attacks their
consensus, and the main session merges the raw opinions into a resolution. The
reviewers are invoked ONLY explicitly as part of a gate, never proactively. Raw
opinions + resolution are committed under `docs/reviews/<date>-<workstream>-<plan|
precommit>/` — see `docs/reviews/README.md` for the procedure and merge rules
(agreements highlighted, conflicts named with cost and never averaged, the human
adjudicates each conflict). The point of the gate is the tension between
reviewers who want different code; don't average it away.
