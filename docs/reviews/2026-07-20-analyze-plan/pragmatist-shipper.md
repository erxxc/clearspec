# pragmatist-shipper — GATE 1 review of the analyze MVP plan

**Verdict: CONDITIONAL** — approve Workstreams 1-3's shape and Decisions A/B/D
as scoped; block on shipping Decision F's conflict-flag subsystem and Decision
C's write-back as currently framed, and flatten Decision E's "confidence"
algorithm to what the golden actually proves. None of these three cuts turn
the acceptance golden red — I checked the fixtures and the current schema/store
code, and the golden doesn't touch what I'm asking to cut.

## Grounding

Read `plan-under-review.md`, all four `tests/fixtures/analyze/tsmc_n2_corroboration/*.json`,
`schema/extraction_schema_v2.yaml`, `src/semianalyst/store/models.py`, `db.py`,
`store/__init__.py`, both migrations, and `CLAUDE.md`. Confirmed no existing
`update_claim_*` or conflict-tracking code exists anywhere in `store/` today —
`insert_entity`/`insert_claim` are plain `INSERT` only.

## Findings

### 1. Decision F's "reconciling upsert" (fill-null + conflict-flag) is a subsystem the golden never touches — cut it to alias-union only

The DoD text says: "a synthetic attribute conflict is flagged, not clobbered."
Read the actual three fixture entities: `source_foundry.json`,
`source_conf.json`, `source_vendor.json` each declare `tsmc_n2` with only
`entity_id`, `entity_type`, `vendor`, `name`, `aliases` — **none of the three
populate `node`/`chip` attributes at all.** The only thing that differs
across the three copies of `tsmc_n2` is the alias list (`["N2"]`,
`["N2","TSMC 2nm"]`, `["N2","2nm-class"]`). Alias union is sufficient to pass
the golden; there is no null-fill scenario and no conflicting non-null value
anywhere in the acceptance data.

The word "synthetic" in the DoD is the tell: the plan's own author knows the
golden doesn't exercise this and is proposing to invent a *separate* fixture
just to justify writing the code. That's the overbuild pattern inverted —
normally you write code because a test demands it; here the plan proposes
writing a test because the code was decided on first.

It's also not free. I grepped the schema, `models.py`, and both migrations —
**there is no field anywhere for representing "a conflict."** Building this
for real means inventing a new column/table (`entity_attribute_conflict`? a
JSON blob on `entity`?) which, per CLAUDE.md's own rule ("change the schema
first... never the other way around"), should start as a schema edit, not a
`store/db.py` patch. CLAUDE.md's actual reconciliation guidance is one
sentence: "One entity per real thing (resolve aliases before insert)." It
does not ask for attribute-level conflict tracking. That's a real design
decision (worth having eventually) being smuggled into an MVP workstream
under a DoD bullet, with a new persisted concept and a schema change that
Decision F doesn't even acknowledge needs to happen.

**Ask:** scope Workstream 1 to alias union + first-non-null-wins for
node/chip attributes (or even simpler: last-writer overwrites null-only,
never overwrites non-null — one `if`, no new data shape). Log a warning on a
detected conflict if you want defense-in-depth; do not design storage for it.
Revisit conflict-flagging when a fixture actually contains one.

### 2. Decision C's write-back is a second source of truth the golden can't see and the store can't currently do

The acceptance assertion is `run_analysis(config) -> AnalysisReport` equals
`expected_analysis.json` — a comparison against the **returned object**. It
never re-opens the store to check `claim.corr_status`. Workstream 5's
(testing) unit-test list doesn't include a "write-back persisted, re-read
confirms it" test either. So the write-back half of Decision C is, by this
plan's own testing strategy, unverified — pure trust.

It's not zero-cost to add: `store/db.py` today has exactly one write path
per table (`insert_document`/`insert_entity`/`insert_claim`, all plain
`INSERT`). Write-back requires a *new* function — an `UPDATE claim SET
corr_status=?, corr_related_claim_ids=? WHERE claim_id=?` — that doesn't
exist yet, plus a new `store/__init__.py` export, plus (correctly) keeping it
inside `store/` to respect the "store is the sole DB owner" boundary. That's
real surface added to satisfy a decision the golden cannot observe passing or
failing.

**Ask:** ship "derive on read" for MVP (the plan's own listed alternative).
`AnalysisReport` is the product; the store doesn't need a second copy of the
verdict until something concrete reads it directly off a `claim` row instead
of through `analyze`. Add the write-back path as a fast-follow when that
caller exists, not speculatively now.

### 3. Decision E's tier-weighted "confidence" can't be distinguished from a trivial status→label lookup by this golden — ship the lookup

The plan frames confidence as computed "from tier span (multiple/high tiers
agreeing → high)" — i.e., a real function of which tiers are present in a
group. But look at the three assessments in `expected_analysis.json`:
corroborated→`high`, contradicted→`low`, uncorroborated→`none`. Confidence
is in 1:1 lockstep with `status` across all three cases; there is no fixture
case that would force the two apart (e.g., two tier-3 sources agreeing —
corroborated but presumably not `high`; or two tier-1 sources diverging —
contradicted but presumably not `low`). A three-entry `{status: label}` map
passes this golden exactly as well as a tier-weighting algorithm, at a
fraction of the code and with zero branches the golden can't hit.

**Ask:** keep the field (the golden needs it), drop the "tier span" algorithm
behind it for MVP. If a richer confidence model is wanted, it needs a fixture
that actually forces status and confidence apart — that fixture doesn't
exist yet.

## What's NOT overbuilt (said so nobody assumes I missed it)

- Decision A (exact-slug matching, alias-canonicalization deferred) is
  correctly minimal — already the least code that satisfies three fixtures
  that happen to use consistent slugs.
- Decision B (flat ±10%) is fine — the golden's spreads are 2.6% and 38.5%,
  so almost any single threshold in between works; per-metric tolerance is
  correctly deferred, not built.
- Decision D (`{doc_id}:{claim_id}` scoping) is a one-line string join that
  matches the `claim_id` values already baked into the fixtures — not
  overbuilt, don't touch it.
- `favored_tier` only appears on the contradicted assessment (not
  corroborated/uncorroborated) in the fixture, matching a scoped
  `min(tiers)`-on-divergence rule — that's appropriately narrow, unlike
  confidence.

## Risk others will miss

The plan's testing bar ("No untested branch — per the standing pragmatist
bar") is being pointed at code that doesn't exist yet for reasons the golden
demands. That's backwards, and it's a self-reinforcing loop: decide to build
tier-weighted confidence and conflict-flagging → "no untested branch" then
*requires* synthetic fixtures/unit tests to invent branches that hit those
paths → those tests now encode the speculative design as locked-in behavior
→ deleting the complexity later means deleting tests, which reads as
"regression" to the next person touching this file, so it survives by
inertia. A coverage bar is supposed to keep implementers honest about real
branches; here it's being used to *justify* extra branches. Schema-purist
and injection-attacker are unlikely to flag this because it's not a
correctness or security issue — it's a process one, and it's exactly the
kind of thing that turns a 3-fixture MVP into a 400-line "framework" nobody
asked for.
