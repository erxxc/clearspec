# schema-purist review — WS-2 live-ingest plan (2026-08-18)

Target: `docs/reviews/2026-08-18-live-ingest-plan/plan-under-review.md`
Grounded in: `schema/extraction_schema_v3.yaml` (+ v2 for the unshown blocks),
`store/models.py`, `store/migrations/0001,0003`, `store/db.py`,
`extract/validate.py`, `analyze/corroborate.py`, `store/persist.py`.

## Verdict: conditional

## Findings

### 1. `unbound_baseline` (B1) is asserted "persisted as a claim-level flag" but no schema/model/migration/db.py change names where it lives — the plan contradicts its own files-touched ledger

§2.4 states the B1 check's "result is persisted as a claim-level flag
`unbound_baseline` when absent." That is a new fact on the `claim` row — it
needs a schema field (`claim.unbound_baseline: boolean`, or similar), a
`Claim` model field, an `INSERT` column in `db.insert_claim`, and a column in
migration `0004`. None of that appears anywhere:

- §2.5's "Schema first" paragraph describes exactly one v4 schema addition —
  the `conflict` record — and says nothing about a claim field.
- Migration `0004_entity_conflicts.sql` is named (and scoped, by its own
  filename) to the conflict table only.
- §4 "Files touched" lists `store/models.py (bounds + Conflict model)` —
  bounds and Conflict, not a new Claim field — and `store/db.py
  (reconcile_entity conflict writes, ClaimView.publisher, conflict queries)`
  — no mention of `insert_claim` gaining a column.
- `extract/validate.py (G1, B1 check, bounds fail-soft)` computes the B1
  check, but validate.py returns an `ExtractionResult` of `models.Claim`
  objects; if `Claim` has no field for it, the check's output has nowhere to
  land and is lost between validate and persist.

This is not a nitpick: the hostile suite in §3 names `baseline_freeride` as a
case that must produce `unbound_baseline flag (B1)` — i.e., something a test
reads back *after* `persist_extraction → analyze → report`. Per CLAUDE.md
("The schema defines every structure... change the schema first"), a field
that a test will assert on must be named in the schema before it's prose in a
design doc. Either this is meant to be a genuine persisted per-row field (then
name it in §2.5/§4 and settle whether it needs a DDL column or is folded into
`Conditions`/`Comparison`), or it's actually meant to be analyze-derived like
every sibling flag (`sparsity`, `marketing_only`, `unresolved_baseline`,
`single_source`, the new `single_publisher`, `vendor_only`) — in which case
"persisted as a claim-level flag" is the wrong description and it belongs on
`Assessment.flags` instead, computed at analyze time from a **stored**
per-claim boolean it still needs to write in the DB in that case (analyze
can't re-derive "is a surface form present in the source text" from
`ClaimView`, since `source_text` isn't retained anywhere post-validate — so a
raw boolean column is unavoidable either way). The plan needs to pick one and
name the column.

### 2. Content bounds (§2.7) are explicitly *not* mirrored into SQLite DDL, breaking the established pydantic/DDL parity the rest of the schema maintains

§2.7: "Enforced at the pydantic layer... no SQLite DDL change needed." But
every prior schema-derived enum in this codebase is enforced at **both**
layers — `store/migrations/0001_initial.sql` has `CHECK (doc_type IN (...))`,
`CHECK (source_tier IN (1,2,3))`, `CHECK (entity_type IN (...))`, `CHECK
(node_transistor_type IN (...))`, `CHECK (completeness IN (...))`, and
`0003_weakly_corroborated.sql` carries the same discipline forward when it
recreates `claim`. CLAUDE.md's data-model rule is explicit: "pydantic models
... and the SQLite DDL ... are both derived from it" — not "pydantic
primarily, DDL for enums only." SQLite `CHECK (length(entity_id) <= 80)` /
`CHECK (length(metric) <= 120)` etc. cost nothing and close exactly the gap
this workstream exists to close: a write path that bypasses pydantic (a
future migration backfill script, a repair tool, a web-UI-era direct writer)
is unbounded at the only layer that's actually durable. Given WS-2a's whole
premise is "don't trust a single enforcement point against a hostile input,"
shipping the one new schema-level constraint of this plan as pydantic-only is
inconsistent with the workstream's own stated posture, not just with
precedent.

### 3. G1 grounds aliases but leaves `entity.name` / `vendor` / `entity_type` — the actual identity fields — permanently ungrounded, and K1 (never-overwrite) now makes that permanent

`validate.py` today grounds only `node.*`/`chip.*` attribute values
(`GROUNDABLE`, `_VALID_PATHS`) and claim `citation.quote_span`. Nothing checks
that `entity.name`, `entity.vendor`, or `entity.entity_type` appear anywhere
in the source text — there is no citation slot for them in the schema at all
(the `entity` block has `attribute_citations` scoped to node/chip fields
only). §2.2's G1 closes the grounding gap for **aliases** only ("the pinned
canonical `name` is exempt — it is the entity's own shape-validated identity
field, not a free-text graft") — but "shape-validated" is not "grounded."
Shape validation confirms `name` is a non-empty string of the right type; it
says nothing about whether the model invented it. Under K1 ("never overwrite
a non-null attribute... a higher-tier doc arriving later with a different
value is a conflict, recorded and surfaced, never an auto-resolution") plus
the existing "identity fields frozen by first writer" behavior, a first
hostile tier-3 document's entirely fabricated `name`/`vendor` for a
freshly-minted `entity_id` becomes the **permanent, ungrounded, cited-nowhere
identity** of that entity — 2.5's identity-conflict detection only fires when
a *later* document disagrees, never on the initial plant. This is precisely
the "every extracted value cites a source span" invariant CLAUDE.md declares
non-negotiable, and this plan — which otherwise closes G/H/I/J/K gaps
exhaustively — leaves the identity fields as the one corner where "citation
per value" still doesn't apply. At minimum this should be named as an
explicit, deliberate scope cut (like the K3/H1/B1 items already are in §5),
not silently absent.

## Risk others will miss

**Vendor-casing asymmetry between the plan's new cross-document alias gate
(G3) and the pre-existing intra-document dedup key.** `validate.py`'s entity
dedup key is `(ent.vendor, ent.name.strip().lower())` — `name` is
case-folded, `vendor` is not. G3 (§2.2) proposes a case-insensitive
cross-entity alias-collision check at *reconcile* time going forward. But the
plan never touches or even names the pre-existing asymmetry one layer
earlier: a single hostile (or just sloppy) document containing `vendor:
"TSMC"` on one entity and `vendor: "Tsmc"` on another, both naming the same
node, produces **two separate entity rows inside one document's own proposal
today** — before cross-document trust ever enters the picture, and before any
of K/G/H/I/J apply. "One entity per real thing" breaks at the most basic
single-document case the plan otherwise treats as fully solved ("Class A"
framing implies the intra-document boundary is closed, per WS-1's grounding
gate). WS-2a's named hostile suite (§3) has no case exercising this — every
named case is inter-document or fetcher-level. Given this plan is explicitly
adding a `possible_slug_collision` flag (J) for *cross-entity* surface-form
overlap, the fact that a *single document* can already silently create two
`entity_id`s for one real thing via vendor-casing is the more basic bug the
new machinery quietly assumes doesn't exist.

## Why conditional, not block

The plan's overall shape is sound and the K/G/H/I/J resolutions are argued
from real precedent (agentlens's Floor reading for K3, repoauditor's
flag-don't-guess for B1, the derive-on-read vs persisted distinction for I is
correctly reasoned — a per-event fact genuinely has no re-derivable source
once reconcile drops the offered value, unlike the per-group corroboration
verdict). But finding #1 is a genuine internal contradiction (prose promises
a persisted field the schema/migration/files-touched sections never create),
and finding #3 is a real, in-scope gap in a workstream whose entire mandate is
closing exactly these grounding holes. Both are fixable by naming things
explicitly before code starts — which is the whole point of a plan gate.
