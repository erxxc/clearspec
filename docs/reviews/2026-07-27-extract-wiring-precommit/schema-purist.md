# schema-purist — WS-1 extract-wiring precommit review

**Verdict: BLOCK**

## Scope note

The claim-integrity guarantee itself is intact: `run_extract` does not bypass
`build_result`/`validate.py`. `AnthropicExtractor.extract()` still calls
`build_result(proposal, source_text)` internally, and `run_extract` persists
exactly `result.entities`/`result.claims` with no intervening transformation —
grounding, relative-never-absolutized, unit normalization, `marketing_only`
tagging, and the `unknown` `location_type` fail-safe all still apply unchanged.
That is not where this diff's schema-fidelity defects live. They live in the
NEW code: the sidecar → `Document` handoff and its idempotency check.

## Findings (my angle only)

**1. `existing_doc_ids` idempotency defeats the schema's own `file_sha256`
revision-detection guarantee — CONFIRMED, most severe.**
`run_extract` (`src/semianalyst/extract/pipeline.py:62-63`) buckets a sidecar
into `pending` vs `skipped` purely by whether `rd.meta["doc_id"]` is already a
row in `document` (`store/db.py:179-183`, `existing_doc_ids`). It never compares
the sidecar's `file_sha256` against the persisted Document's `file_sha256`.
CLAUDE.md is explicit that a changed hash is "how silent revisions of the same
URL are detected" — that guarantee is now dead on arrival at the extract layer.
Concretely: operator ingests `tsmc_n2_2025` v1, extracts it. TSMC quietly
corrects the PDF (new bytes, new sha256, same doc_id — the exact "silent
revision" scenario the schema names). Operator re-runs `ingest-file` with the
same `doc_id` (this is the intended re-ingest workflow — `doc_id` is the stable
handle) and then `extract`. The new sidecar's `doc_id` is already in `already`,
so it is silently classified `skipped` — indistinguishable in the CLI's output
from the honest "already extracted, nothing to do" case. The revision is
dropped on the floor with no error, no flag, no operator signal. The new E2E
test (`tests/test_pipeline_e2e.py::test_extract_e2e_offline`) only proves the
identical-bytes idempotent case; nothing in the added suite exercises
same-doc_id/different-sha256, so this gap ships untested as well as unhandled.

**2. Sidecar identity is keyed by content hash only — the inverse gap, and it
contradicts its own docstring.** `write_sidecar` (`ingest/base.py:74-83`) writes
to `raw_dir/<sha256>.meta.json` — path is a pure function of content, not of
`doc_id`. Its docstring claims overwriting is "a safe no-op-ish" because
"identical bytes always map to the same doc metadata for a given ingest." That
is not an invariant the code enforces or even checks — it's an assumption. Two
`ingest_file` calls over the SAME bytes with two DIFFERENT `doc_id`/`title`/
`source_tier` (a corrected doc_id after a typo; two publishers releasing
byte-identical collateral) silently last-write-wins the sidecar, clobbering the
first ingest's provenance before extraction ever observes it — no merge, no
conflict signal, same silent-clobber failure mode as #1 but on the opposite
axis (content identity vs. document identity). Combined, #1 and #2 mean the
sidecar/doc_id scheme has no invariant tying content identity to document
identity in either direction, despite `file_sha256` being called out in
CLAUDE.md as authoritative.

**3. `_build_document` gives the sidecar → `Document` construction zero
per-document fault isolation, unlike every other schema-enforcement boundary
in this codebase.** `validate.py`'s whole design principle is "a malformed
item is dropped ... never fatal to the whole extraction" (a single bad claim
or entity doesn't sink the document). `_build_document` (`extract/pipeline.py:
34-51`) has no such isolation: a missing sidecar key raises a bare `KeyError`
(not even a structured pydantic error naming the field); an out-of-range
`source_tier` or an unparsed `publish_date` raises `ValidationError`. Either
way it's unhandled inside `run_extract`'s `for rd in pending` loop
(`pipeline.py:74-81`), so ONE malformed sidecar aborts the ENTIRE batch —
every other valid pending doc after it in iteration order is silently never
attempted, with no report distinguishing "nothing pending" from "crashed
partway through." This is a real regression against the isolation norm
CLAUDE.md establishes for schema enforcement elsewhere in the pipeline, at
precisely the boundary (operator/ingest-authored metadata) where a typo is
most likely.

## One risk others will miss

The `extraction_model` provenance stamp — `f"{model_name}+{prompt.name}@
{prompt.sha256[:12]}"` (`extract/pipeline.py:50`) — is a lossy, unparseable
freeform string standing in for what CLAUDE.md calls a load-bearing guarantee:
tying every extraction run to "the exact prompt bytes ... that produced it."
It truncates the hash to 12 hex chars (48 bits — fine for casual grep, weak as
an audit primitive) and naively concatenates with `+`/`@` with no escaping: if
`prompt.name` or `model_name` ever contains either character (nothing in
`PromptVersion.load` forbids it — it's derived from a filename stem), the three
components become unrecoverable from the stored string. `pragmatist-shipper`
will wave this off because the DB column is `TEXT -- model + prompt version,
for re-runs` (a comment, not a schema-enforced shape) — but that's exactly my
blind-spot warning: nothing stops this from silently degrading into an
ambiguous string the day someone names a prompt file with a `@` in it, and
nobody will notice until a provenance audit needs to un-concatenate it.
