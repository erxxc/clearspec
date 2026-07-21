# pragmatist-shipper — GATE 1 v2 (re-gate) review of the analyze MVP plan

**Verdict: CONDITIONAL** — the two cuts that matter most landed clean
(write-back → derive-on-read; conflict → log-only, no schema). Approve those
and Workstreams 2-3 as scoped. Block on three things that grew back in the
gaps: the "tier-aware" null-fill precedence in §1 is *more* code than v1's
cut asked for and is still 100% unexercised (worse than v1 — see below); the
new slug-collision tripwire (§1) has no positive trigger anywhere in the
golden; and Decision H's confidence cap repeats the exact
test-justifies-code inversion I flagged last round, just with better
bookkeeping about it. None of the three sinks the acceptance golden if cut —
verified against all four regenerated fixtures.

## Verify: did the v1 cuts land?

Checked each of my three v1 asks against the v2 text and the current
`store/models.py` / `db.py`:

1. **Conflict-flag storage → cut. Confirmed clean.** §1: "A non-null
   conflict is **logged, not stored** — no new conflict schema this MVP...
   Persisted conflict-tracking → deferred (Decision I)." `models.py`/`db.py`
   still have no conflict field or table. This is exactly what I asked for.
2. **Write-back → cut to derive-on-read. Confirmed clean.** §2: "`analyze`
   returns an `AnalysisReport`; it does NOT mutate `claim.corroboration` in
   the store this iteration." `db.py` still has only `insert_*`, no
   `update_claim_*`. Exactly what I asked for.
3. **Tier-weighted confidence → cut to status-derived. Landed, but with a
   rider.** §2 Decision H: "MVP status-derived, **but with a tier-diversity
   cap**." The lookup I asked for shipped; a new conditional branch rode in
   on top of it. See Finding 3.

Two out of three cuts are real and I'm crediting them. The third is where
this review earns its keep.

## Findings

### 1. §1's "tier-aware" null-fill is *more* than v1 asked for, and it's not just unexercised — it's dead on arrival for this fixture

I grepped all four fixture files for `"node"` / `"chip"` keys: zero matches.
Every entity record in `source_foundry.json`, `source_conf.json`, and
`source_vendor.json` carries only `entity_id`, `entity_type`, `vendor`,
`name`, `aliases` — **no fixture, across all three loads, ever populates a
single node/chip attribute.** That's stronger than what I found in v1 (where
I could only say "no *conflicting* value exists"); now I can say the null-fill
mechanism has no non-null value to fill *with*, ever, in this golden. Not
"first-non-null-wins is untested," but "there is no non-null to win."

Against that backdrop, §1 proposes: "Fill is **tier-aware / order-independent**:
the higher-trust (lower `source_tier`) document's value wins a null-fill
race." That's strictly more machinery than what I asked v1 to cut down to
("last-writer overwrites null-only... one `if`, no new data shape"). Tracking
which document supplied which attribute — enough to compare tiers at fill
time — is new state the schema doesn't currently carry (no `attribute_citations`
entry maps back to a document's `source_tier` today without a join). This is
injection-attacker's F1 concern (v1) folding back in via the resolution's
"real, folds into the revised plan" language — legitimate as a design point,
illegitimate as MVP scope, because **nothing here will tell you if it's wrong.**
A tier-comparison bug in this code would pass every test in the plan's own
suite, because §4's unit test for it necessarily uses synthetic tier values
the author picks, not the golden.

**Ask:** implement the version I asked for last round — alias union (real,
exercised) + "never overwrite a non-null value; fill a null one" (no tier
comparison, no ordering logic). Defer tier-aware precedence to when a
fixture actually contains two documents disagreeing on the same non-null
node/chip attribute. Right now that fixture doesn't exist and the plan isn't
proposing to add one for this — it's proposing to add a *unit test* for it,
which is the cart pulling the horse again (see Risk, below).

### 2. The slug-collision tripwire (§1, Decision J) is brand-new code with no positive case in the golden

This wasn't in v1's plan or my v1 review — it's new, added to answer
schema-purist's "Decision A fails silently" v1 finding. The rule: "if two
entities share `(entity_type, vendor)` with high alias-token overlap, emit a
warning." Check it against the fixture: `tsmc_n2` and `tsmc_n3e` *do* share
`(entity_type=process_node, vendor=TSMC)` — but their alias sets
(`["N2","TSMC 2nm","2nm-class"]` vs `["N3E"]`) share zero tokens, so the
warning correctly never fires. That's the only `(entity_type, vendor)`
collision anywhere in the golden. There is no case in any of the four
fixtures where two *different* `entity_id`s are actually the same real thing
under different slugs — the exact scenario this tripwire exists to catch.
So the branch that matters (the warning actually firing) has zero coverage
from the acceptance data, and the plan knows it — it's honestly listed as
open **Decision J** in §5 rather than presented as settled. Good that it's
surfaced; still, my vote on J is "cut for MVP, or reduce to the one-line
version with no similarity threshold to tune (that threshold is unverifiable
without a fixture that needs it)."

### 3. Decision H's tier-diversity cap is the same inversion I flagged in v1, now with a self-aware admission built in

The plan states its own gap: "A fixture case forcing confidence≠status will
be added **iff this is ratified**... (answers pragmatist E's 'no fixture
forces them apart')." Check the actual four assessments: `high`/`low`/`none`/`none`
map 1:1 onto `corroborated`/`contradicted`/`uncorroborated`/`uncorroborated`
— identical lockstep to v1, because the one `corroborated` group has tiers
`[1,2]`, never all-tier-3. The cap cannot be exercised by anything currently
in the golden. Naming the gap doesn't close it — it just moves the
overbuild from "ship the algorithm" (v1) to "ratify the algorithm, then
synthesize a fixture to justify it" (v2), which is worse: now the fixture
gets built *because* the code was proposed, not the other way around. My
ask stands from v1 — ship the three/four-line status→label lookup, drop the
cap. If tier-diversity floors matter (and injection-attacker is right that
they might, for real corroboration-laundering reasons), that's a fast-follow
gated on a real multi-tier-3 case showing up in actual data, not a fixture
manufactured to make Decision H's diff look tested.

## What's NOT overbuilt (carried forward from v1, still true)

Decisions B (flat ±10%) and D (`{doc_id}:{claim_id}` scoping) remain
appropriately minimal. The grouping-key fix (`is_relative` added, schema-purist
F1) and the corroboration-count exclusion of suspect members (F2) are both
directly exercised by the golden — the perf_per_watt group (tier 2 vs tier 3,
`sparsity`) really does need both rules to land on `contradicted` rather than
a false `corroborated`, and the golden would go red without them. That's the
bar the rest of §1/§2 should be held to and mostly isn't.

## Risk others will miss

This is the same risk I named in v1, and it's still live, just better
disguised: §4's testing list commits unit tests for **all three** unexercised
branches above (null-fill tier-precedence, slug-collision tripwire,
tier-diversity cap) using the "no untested branch" bar as the justification.
Schema-purist and injection-attacker will like this — it looks like rigor.
But a coverage bar applied to code that exists because the bar demands
coverage, not because a real scenario demands the code, is circular: the
bar is supposed to catch branches you forgot to test, not manufacture
branches to have something to test. §5 marks H and J as open decisions,
which is honest, but if either gets ratified on the strength of "we'll add a
fixture for it," that fixture will be hand-built to match whatever the
implementer already wrote — it proves the code does what the code does, not
that the code was needed. The next person to delete this stuff won't have a
real regression to point to, just a green synthetic test, and it'll survive
by inertia exactly as I described in v1. (Security implications of the
tier-precedence/tripwire choices are injection-attacker's lane, not mine —
I'm flagging the process failure mode, not auditing the threat model.)
