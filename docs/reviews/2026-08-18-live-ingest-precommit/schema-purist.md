# schema-purist — WS-2a precommit review

Target: `docs/reviews/2026-08-18-live-ingest-precommit/workstream.diff` (5a8af2c..d6adb94),
reviewed against the working tree on `feat/ws2a-trust`. Contract:
`docs/reviews/2026-08-18-live-ingest-plan/resolution.md` (not re-litigated).

Angle: three-way parity (schema v4 ↔ `store/models.py` ↔ migration 0004), conflict-record
shape/honesty, artifact/sidecar provenance fidelity, migration carry-forward soundness,
CLAUDE.md accuracy, and normalization-key consistency across validate/reconcile/analyze.

## Verdict: conditional

## Findings

### 1. Migration 0004's carry-forward has no safety net for pre-existing rows that violate the new bounds — undocumented, untested crash risk (orchestrator's named concern, confirmed real)

`0004_conflicts_and_bounds.sql` recreates `document`/`entity`/`claim` with CHECK constraints
already active on the new table, then does a bare `INSERT INTO <table>_v4 SELECT ... FROM
<table>` (lines 41-43, 74-80, 111-116). SQLite evaluates the CHECK on every row of that
`INSERT..SELECT`. Any pre-existing row that exceeds a v4 bound —
`cite_quote_span` > 2000 chars (a plausible pre-v4 verbatim quote; nothing in v1-v3 bounded
it), `url` > 2000, `aliases` JSON > 1500, `cond_stated_caveats` JSON > 8500, `metric` > 120,
etc. — raises an uncaught `sqlite3.IntegrityError` that propagates straight out of
`db.init_db` (no `except` around `conn.executescript` for this class of error; the runner
only wraps the migration in `with conn:` for transactional rollback, not for translation to
a friendly message). There is no test exercising "upgrade an existing pre-0004 store," no
documented recovery path (no companion trim/truncate script, no operator guidance), and
CLAUDE.md's new v4 section is silent on it. This is exactly the "leniency nobody
double-checked" failure mode: the schema-fidelity story (pydantic ↔ DDL ↔ migration) is
airtight for *new* writes but was never proven against the *existing* store this repo has
been dogfooding since WS-1 (`main` already has real extraction runs; anyone who ran `extract`
against `main` before this branch has a `data/store.db` that migration 0004 will attempt to
carry forward blind). Ship with either a documented "back up your store, this may fail on
pre-v4 data" caveat plus a triage query operators can run first, or a `db migrate --check`
dry-run that reports which rows would violate the new bounds before committing to the
in-place `db init` run.

### 2. The "mirrored bounds" parity claim is false for JSON-serialized fields under legal (non-adversarial) content — a false-*positive* rejection risk on the honest path

Schema v4's header and CLAUDE.md both assert the DDL CHECKs "mirror" the pydantic length
bounds (schema/extraction_schema_v4.yaml:18-24, CLAUDE.md v4 changelog line). That's true for
scalar TEXT columns, but `entity.aliases` and `claim.cond_stated_caveats` are stored as
`json.dumps(...)` output (`store/db.py:138,144,169`), and the DDL CHECK measures the
*serialized* string length, not the raw value pydantic validated. `Caveat500`
(`store/models.py:46`) is explicitly **length-only, no charset restriction** — the schema
comment says so on purpose ("verbatim source text ... may legitimately contain newlines the
no-control-chars pattern would reject"). `json.dumps` escapes `"`, `\`, and any control byte
outside `\n\r\t` as `\uXXXX` (6 chars for 1). A single pydantic-valid `Claim` with 16
footnotes of 500 chars each that happen to contain ordinary quotation marks (not an
adversarial payload — footnotes routinely quote condition names, e.g. `"iso-power"`) can push
the serialized `cond_stated_caveats` well past the 8500-char CHECK the migration computed
assuming *zero* escaping (16×502+17 = 8049, leaving only 451 chars of headroom — about 45
quote characters spread across all 16 footnotes exhausts it). `entity.aliases` has a smaller
but non-zero version of the same gap (Text80 bans control chars but not `"`/`\`). The failure
mode is the opposite of the fail-safe posture CLAUDE.md insists on elsewhere (`location_type`
fails to `unknown`, sparsity fails to suspect): here a **legitimately-extracted, honestly
grounded claim** can be silently dropped as a persist "error" because two validation layers
that are supposed to agree don't, for reasons that have nothing to do with the value's
legitimacy. `test_hostile.py::test_field_flood`'s DDL backstop check only exercises plain
`'m'*121`/`'x'*121` (no escaping) — it doesn't cover this gap.

### 3. `entity.aliases` `max_items: 16` (schema v4 bounds block) is enforced only at the single-document pydantic boundary — never at the true point of accumulation

`models.Entity.aliases` bounds `max_length=16`, but that check runs once, on the incoming
proposal's `Entity` object, inside `validate_proposal`. `reconcile_entity`
(`store/db.py:434-449`) then **unions** the incoming (already-bounded-to-≤16) aliases into
the *stored*, already-merged list from every prior document that touched this entity —
`aliases = json.loads(existing["aliases"]); ... aliases.append(alias)` — with no re-check
against the schema's `max_items: 16` invariant. The only backstop is the DDL's
`length(aliases) <= 1500` CHECK on the table, which bounds *serialized byte length*, not item
count — 16 short aliases (~10 chars) sit nowhere near 1500, and well over 16 items can still
fit comfortably under it. Across enough honest documents (three, four, ten releases about the
same process node, each contributing a couple of new grounded product-name aliases), the
stored list can silently exceed the schema's own declared per-entity bound with zero
signal — no rejection, no conflict record, no test. `test_hostile.py::test_field_flood`'s
">16 aliases" case only exercises the single-proposal shape-validation path (one document
proposing 17 aliases at once), never the cross-document merge path this workstream's whole
point was to harden. This is a genuine schema-fidelity gap: a `bounds` entry that reads as a
per-entity invariant in the schema file is actually a per-document-contribution invariant in
the code, and nothing documents that narrowing.

## Risk others will miss: three incompatible "case-folded" normalizations across validate → reconcile → analyze

CLAUDE.md and the gate resolution both describe a single policy — "case-folded compare," "a
casing/spacing variant is one value" — but the diff ships **three different
implementations** of it, and they don't agree with each other:

- `extract/validate.py:261` (per-document entity dedup key): `ent.vendor.strip().lower()`,
  `ent.name.strip().lower()` — Python `.lower()`, **not** `.casefold()`. The gate resolution's
  Challenge 2 disposition specifically says the vendor-dedup fix is "case-folded vendor in the
  dedup key" — the shipped code strips but does not casefold. `.lower()` and `.casefold()`
  diverge on real inputs (ß/ss, Kelvin sign, other Unicode caseless-matching edge cases); low
  probability on ASCII vendor names today, but it's a documented promise the code doesn't
  literally keep.
- `store/db.py:404` (`reconcile_entity`'s identity-field conflict check): `.casefold()` with
  **no `.strip()`**. PDF text-layer extraction is a well-known source of stray leading/trailing
  whitespace. A vendor string of `"TSMC"` from one document and `"TSMC "` (trailing space) from
  another — entirely plausible PDF-extraction noise, not an attack — will **not** compare equal
  under bare `.casefold()`, so `reconcile_entity` will record a spurious `identity_field`
  conflict for two documents describing the identical real vendor. That conflict is exactly the
  human-facing, adversary-text-flavored record Conflict 1 fought to ship, and it will fire on
  honest data. It directly threatens the gate's own **flag/conflict-noise budget** (Challenge 4)
  from an angle the honest-corpus regression likely won't catch unless a fixture happens to carry
  that whitespace artifact.
- `analyze/corroborate.py:73-77` (`_norm_key`, used for the group key and H1's publisher floor):
  whitespace-collapse **+** strip **+** casefold — the most complete of the three, and the only
  one that would actually catch the trailing-space case above.

None of these three call into a shared helper; each was written independently for this
workstream's needs. The result is that "same identity, different casing/spacing" is honored
inconsistently depending on which code path touches the string first — the entity dedup key
(weakest), the conflict-recording identity compare (medium, whitespace-fragile), and the
analyze group key (strongest). A single shared `_fold(s: str) -> str` helper in a location all
three can import would remove the drift and is a small change relative to migration 0004's
footprint; as shipped, this is a latent source of both false-negative dedup (validate) and
false-positive conflict noise (reconcile) that neither the hostile suite nor the honest-corpus
regression is positioned to catch, because it isn't an attack — it's an internal-consistency
bug in exactly the normalization logic CLAUDE.md claims is uniform.

## What I checked and found sound
- Schema v4 `conflict` record ↔ `models.Conflict` ↔ `entity_conflict` DDL: field-for-field
  parity holds (`kind`/`entity_id`/`doc_id`/`field`/`stored_value`/`offered_value`/`created_at`,
  bounds ≤80/≤120/≤120 match in both layers).
- The late chip-attribute bounds fix (`package_type`/`memory_type`/`process_node_ref`) is
  consistent in both `models.ChipAttributes` and migration 0004's `entity_v4` CHECKs.
- `reconcile_entity`'s read-compare-write rewrite correctly threads `doc_id` through to every
  conflict record, and G3 alias-collision gating is applied on both the insert path and the
  merge path (verified in `store/db.py:377-399` and `434-446`).
- `_conflict_repr` (db.py:306-317) scrubbing control bytes before a value re-enters `Conflict`'s
  `Text120` pattern is a real, load-bearing fix — a legacy/poisoned stored value would otherwise
  raise *from inside* `reconcile_entity`, aborting the whole document instead of recording the
  refusal it exists to record.
- Artifact payload (`_artifact_payload`) and sidecar both carry the provenance stamps CLAUDE.md
  claims (`_extracted_at`, `_extracted_against` with model/prompt/sha).
- CLAUDE.md's rewritten Class-A section is accurate against the code for everything I checked
  except the `.lower()` vs "case-folded" wording noted above.
