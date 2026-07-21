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

**Hostile-input trust is DEFERRED to the live-ingest workstream (Class A).** The
current slice runs on curated fixtures — no hostile document can reach
`persist_extraction`. When live ingest lands, these decisions must be made and
enforced with a *named adversarial suite* (never the honest acceptance golden):
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
- **Baseline content-bound** — post-0003 `cmp_baseline_entity` is unconstrained
  TEXT (the FK drop removed the shape guard too, not just the existence guard). No
  length/byte-content bound on it or on free-text `metric`.
- **Report display safety** — `cli.py:report()` echoes DB-derived strings
  (`entity_id`, `aliases`, `metric`, `baseline_entity`) to the terminal with **no
  output encoding**. Honest fixtures are inert, but once live extraction feeds
  proposal content here, ANSI/OSC escape sequences render on `semianalyst report`
  with no code change on the display side. Sanitize output before this ships live.
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

## Secrets never land in the repo
The extraction model name lives in `config.toml`; the API key is read from the
environment (`ANTHROPIC_API_KEY`) at call time and is never committed. `data/` is
gitignored in full.

## Module map
- `ingest/`  — fetchers + content-addressed raw storage (network fetch: WIP)
- `extract/` — raw doc → schema records via a versioned prompt (LLM: WIP/stub)
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
