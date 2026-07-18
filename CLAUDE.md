# CLAUDE.md — architectural rules for semianalyst

Future sessions MUST respect these. They encode decisions that are expensive to
reverse once data and prompts accumulate.

## The data model is the source of truth
`schema/extraction_schema_v1.yaml` defines every structure. Pydantic models
(`store/models.py`) and the SQLite DDL (`store/migrations/`) are both derived
from it. Change the schema first; regenerate the models and add a migration —
never the other way around.

## The claim is the atomic unit — and its integrity rules are non-negotiable
- **Every extracted value cites a source span** (`claim.citation.quote_span`).
  A value with no citation is not a claim.
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

## Testing
`tests/` uses a golden-fixture harness: `tests/fixtures/<doc_id>/raw.pdf` +
`expected.json`, diffed against extractor output. It is the QA backbone — keep it
green (the extraction case `xfail`s strictly until the extractor lands, then the
marker is removed). Store/ingest/prompt behavior is covered by real
(non-`xfail`) tests.

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
