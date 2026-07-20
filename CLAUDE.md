# CLAUDE.md — architectural rules for semianalyst

Future sessions MUST respect these. They encode decisions that are expensive to
reverse once data and prompts accumulate.

## The data model is the source of truth
The schema defines every structure; pydantic models (`store/models.py`) and the
SQLite DDL (`store/migrations/`) are both derived from it. Change the schema
first; regenerate the models and add a migration — never the other way around.
**`schema/extraction_schema_v2.yaml` is current** (extraction targets v2);
`_v1.yaml` is retained unedited. v2 added per-attribute grounding for entity
attributes (`entity.attribute_citations`) and a fail-safe `unknown` value on
`citation.location_type`.

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

**Cross-document entity reconciliation is an open PREREQUISITE for persistence.**
The inserts use plain `INSERT` (a duplicate primary key **raises**, not silently
overwrites) — because `entity_id`/`claim_id` are model-derived and shared across
documents, so a naive `INSERT OR REPLACE` would let a later (or hostile) document
clobber an entity an earlier document created, destroying corroboration. Do NOT
wire `run_extract` → `insert_*` until the persistence workstream defines how a
second document naming an existing entity is merged/versioned. `validate.py`
enforces a per-DOCUMENT trust boundary only (a claim must reference an entity from
its own proposal); cross-document trust is the store workstream's job.

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
- `store/`   — SQLite persistence; sole DB owner
- `analyze/` — cross-source corroboration + divergence (future work)
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
