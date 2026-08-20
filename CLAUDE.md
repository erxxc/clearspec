# CLAUDE.md — architectural rules for semianalyst

Future sessions MUST respect these. They encode decisions that are expensive to
reverse once data and prompts accumulate.

## The data model is the source of truth
The schema defines every structure; pydantic models (`store/models.py`) and the
SQLite DDL (`store/migrations/`) are both derived from it. Change the schema
first; regenerate the models and add a migration — never the other way around.
**`schema/extraction_schema_v4.yaml` is current**; `_v1`/`_v2`/`_v3` are retained
unedited. v2 added per-attribute grounding (`entity.attribute_citations`) and a
fail-safe `unknown` `citation.location_type`; v3 added `weakly_corroborated` as a
`corroboration.status` verdict value (a group that agrees within tolerance but has
<2 non-suspect members — a clean number + an honestly-disclosed sparsity number)
and made corroboration **derive-on-read, not persisted** — migration 0003 dropped
the per-row `corr_status`/`corr_related_claim_ids` columns (a per-group verdict has
no honest per-row home) and dropped the `cmp_baseline_entity` FK. v4 (WS-2a,
2026-08-18 gate) added the persisted `conflict` record and two-layer content
bounds (pydantic length+charset; DDL length CHECKs — migration 0004), and
documented the extraction-artifact fold.

## The claim is the atomic unit — and its integrity rules are non-negotiable
- **Every extracted value cites a source span** — code-enforced, not trusted to
  the model. `extract/validate.py` drops any claim whose `citation.quote_span`
  isn't a (whitespace-normalized) substring of the source, and nulls any entity
  attribute whose `attribute_citations` entry isn't grounded (v2). The LLM output
  is a PROPOSAL; validation is the guarantee. `location_type` fails safe to
  `unknown` under flat-text extraction (never laundered to `body`). **Grounding
  is a FIDELITY boundary, not a trust boundary** (2026-08-18 precommit gate): it
  proves the model didn't fabricate *relative to the document* — and the
  document is adversary-authored, so a hostile PDF can ground anything it
  chooses to print. Trust comes from the cross-document layer: provenance,
  conflict records, H1, tiers — never from grounding alone.
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
(`reconcile_entity(conn, ent, doc_id)`: read-compare-write since WS-2a — union
grounded aliases, fill NULL node/chip attributes with their citations as a pair,
**never** overwrite a non-null one, and persist an `entity_conflict` record for
every refusal: `identity_field` (frozen vendor/name/entity_type differ,
case-folded compare), `attribute` (K2: differing non-null), `alias_collision`
(G3: incoming alias equals another entity's surface form — not unioned)), and
inserts claims under a doc-scoped `claim_id` (`{doc_id}:{id}`) so two docs'
claims coexist. Conflict values are adversary-authored, bounded ≤120 at model +
DDL layers, and displayed ONLY through `cli._ansi_safe`. Conflicts are per-EVENT
facts persisted because the offered value has no other home (2026-08-18 gate,
Conflict 1 — the derive-on-read precedent B2 does not transfer); they regenerate
deterministically on refold and vanish with forgotten/superseded docs. `cmp_baseline_entity` has no FK (a
baseline may be cross-document or dangling; analyze flags `unresolved_baseline`).
There is **no persisted per-row corroboration verdict** — migration 0003 dropped
the `corr_status`/`corr_related_claim_ids` columns. Corroboration is a per-GROUP
fact analyze recomputes *derive-on-read* over the whole store on every `report`;
the `AnalysisReport` is the sole source of truth. The `Claim` model keeps a
`corroboration` field with a neutral default for extraction-output shape stability,
but `insert_claim` never writes it and nothing reads it back. Do not re-add a
persisted per-row verdict without settling the per-group-fact-in-a-per-row-home
question (decision B2, analyze GATE-2 resolution).

**The DB is derived state — the artifact fold (WS-2a, 2026-08-18 gate Challenge
1).** `run_extract` persists each document's validated extraction as
`data/raw/<file_sha256>.extraction.json` beside the raw blob (atomic write,
provenance-stamped with `_extracted_at` + model/prompt sha). The SQLite DB is a
deterministic FOLD over retained artifacts: `run_rebuild` replays
`persist_extraction` for the latest artifact per doc_id (`_extracted_at` desc,
sha tie-break) in `(ingest_date, doc_id)` order into a temp file, then atomically
replaces the DB. **The fold replays `_extracted_at` order — the actual
incremental chronology** — because reconciliation is first-writer-wins in every
dimension (identity freeze, null-fill, alias ownership, conflict attribution);
any other key silently re-decides every race on every rebuild (2026-08-18
precommit gate, devils-advocate). An artifact folds only when a sidecar at the
same sha256 binds the same doc_id — a CONSISTENCY check against the ingest
record, NOT authentication: **write access to `data/raw/` is the trust
boundary** (sidecar, blob, and artifact live in the same directory; a MAC keyed
outside it is WS-2b+ scope). `forget <doc_id>` moves sidecar+artifact to
`data/quarantine/` (never deletes — blobs stay, content-addressed), refolds,
and FAILS LOUD if the doc_id survives the refold — the retraction primitive
every flag-terminated defense resolves into, and it must never report success
while retracting nothing. A revision (same doc_id, CHANGED bytes) is EXTRACTED
and supersedes via refold (WS-1's deferred supersession: retired); an
already-superseded byte-state re-offered is skipped (anti-ping-pong).
Incremental state and rebuilt state must stay equal — tested, including with
sha order deliberately opposing ingest_date order.

**Cross-document TRUST (Class A) — RESOLVED at the WS-2 gate (2026-08-18) and
enforced in WS-2a.** The gate record
(`docs/reviews/2026-08-18-live-ingest-plan/resolution.md`) is authoritative for
every decision; the *named hostile suite* (`tests/test_hostile.py`) plus the
honest-corpus regression + flag budget are the enforcement. The prompt-injection
surface remains defended as before (`DOC_OPEN`/`DOC_CLOSE` delimiter, per-document
grounding, `test_injection_*`). Resolved and BUILT:
- **K** — never-overwrite is UNIVERSAL: no tier ever overrides a non-null
  attribute; a later differing value (any tier) writes an `attribute` conflict.
  Null-fill stays first-non-null, tier-blind — the race a hostile early doc can
  win becomes a *visible conflict* when the honest value arrives, never a silent
  loss. `favored_tier` stays **tier-blind** (K3, ratified): suspect-ness is
  self-declared by the claim's own document, so excluding suspects would punish
  honest disclosure and reward concealment.
- **G** — aliases are grounded (G1: must appear in the contributing document's
  source text, case-insensitive; ungrounded → dropped at validate) and
  collision-gated (G3: an incoming alias equal to another stored entity's
  name/alias is not unioned — `alias_collision` conflict). Entity `name`/`vendor`
  get presence-grounding at validate (fail-soft drop) — the first-writer identity
  plant needs its identity to at least exist in its own document.
- **H1** — `corroborated` requires the agreeing non-suspect members to span ≥2
  distinct NORMALIZED publishers; single-publisher agreement demotes to
  `weakly_corroborated` + `single_publisher`. Honestly an OPERATOR-diversity
  floor (publishers come from watchlist config in WS-2b's direct-URL scope).
- **Group-key hardening** — `metric`/`unit` are normalized (casefold+ws) in the
  analyze group key; near-identical metric strings get the advisory
  `possible_split_metric` flag.
- **Sidecar identity binding** — `write_sidecar` refuses a doc_id-differing
  overwrite (`SidecarCollision`); same-doc_id metadata refresh stays allowed.
  Same-doc_id supersession: retired via the artifact fold (revisions extract and
  supersede).
- **Blob content-hash** — `read_raw_docs` recomputes each blob's sha256;
  mismatches surface in `ExtractReport.errors`, never extracted.
- **Content bounds** — every model/network-influenced string is bounded in
  pydantic (length + charset) AND mirrored as SQLite length CHECKs (migration
  0004; schema v4 `bounds` block). `cmp_baseline_entity` has a slug shape bound
  (the FK stays dropped — dangling baselines remain legal and flagged).
- **Report display safety** — `cli._ansi_safe` strips ANSI/OSC/control escapes
  AND all Unicode category-Cf codepoints (bidi/zero-width/BOM — Trojan-Source
  class, closed by category test, not enumeration). Every DB-derived display
  string, including conflict `offered_value`/`stored_value`, routes through it.
- **I** — conflict records are persisted (`entity_conflict`, migration 0004) —
  see the persistence section above for the shape and the derive-on-read
  distinction. **J** — slug collisions are an advisory analyze flag
  (`possible_slug_collision`), deliberately never fail-loud (a fail-loud check
  would let a hostile alias DoS honest ingestion).

**Still DEFERRED, with named triggers (see docs/ROADMAP.md):** **H2** (all-tier-3
confidence cap — trigger: watchlist carries ≥2 distinct tier-3 publishers for one
metric); **B1** (baseline surface-form binding — CUT at the gate: near-empty
true-positive surface; trigger: a demonstrated misattributed-measurement case);
**controlled metric vocabulary** (trigger: real corpus shows split groups
normalization can't close); **identity citation slots** for `name`/`vendor`/
`entity_type` (trigger: schema v5); **Unicode confusables/homoglyph folding**
(a Latin/Cyrillic/Greek lookalike swap defeats fold-based comparison in G3, H1,
and J simultaneously — precommit gate, injection F2; trigger: the honest
fixtures now exist, land it when a live corpus shows a homoglyph case, inside
`textnorm.fold`); **display of `quote_span`/`stated_caveats` — OPEN** (stored
VERBATIM by design, length-bounded only: raw escapes and Trojan-Source
codepoints persist in DB and artifacts; `report` doesn't display them today,
but any future evidence-display feature MUST route them through `_ansi_safe` —
the "every DB-derived display string" guarantee covers currently-displayed
fields only). Residual risks accepted at the gate: shell-publisher collusion
passes H1; a tampered sidecar `file_sha256` FIELD (S2 verifies the blob against
the filename hash only); an `_extracted_at` inside an artifact is
attacker-writable text ordering the fold — bounded by the `data/raw/` trust
boundary above.
`validate.py` enforces a per-DOCUMENT boundary; cross-document trust lives in
store reconciliation + analyze floors, tested by the hostile suite.

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
same doc_id + CHANGED bytes → a source revision — EXTRACTED and superseded via the
artifact fold (WS-2a; reported in `ExtractReport.revised`), with an anti-ping-pong
guard (an already-retained byte-state re-offered is an honest skip). Each
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
- `ingest/`  — fetchers + content-addressed raw storage + provenance sidecars +
  extraction-artifact layout + `forget` quarantine (`ingest_file` operator path
  live; network fetch: WS-2b)
- `extract/` — raw doc → schema records via a versioned prompt; `run_extract`
  wires ingest (sidecar) → extractor → `persist_extraction` + artifact;
  `run_rebuild` refolds the DB from artifacts
- `store/`   — SQLite persistence + conflict-recording entity reconciliation;
  sole DB owner
- `analyze/` — cross-source corroboration + divergence (tolerance grouping over
  normalized keys, suspect members excluded from the corroborated count, H1
  publisher floor, tier-blind `favored_tier` on contradictions, advisory flags,
  conflict surfacing; derive-on-read, read-only over `store`)
- `cli.py`   — thin argument layer over the above (`db init|rebuild`, `ingest`,
  `ingest-file`, `extract`, `report`, `forget`)

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
real tests. **WS-2a adds the named hostile suite** (`tests/test_hostile.py` +
`tests/fixtures/hostile/`): constructed hostile documents through the REAL
validate→persist→analyze→report chain — one named test per attack, never reusing
the honest acceptance golden — paired with the **honest-corpus regression** (the
analyze golden's verdicts/flags must not change except by written, approved
diffs) and the **flag budget** (≤1 new flag per honest assessment per
workstream; WS-2a shipped at zero).

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
