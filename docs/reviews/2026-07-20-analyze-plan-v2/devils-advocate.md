# devils-advocate — GATE 1 v2 (re-gate), attack on the consensus

**Role:** run last; attack what the other three agree on, not the plan. I am not
scoring the plan's size. I am scoring the thing all three of them — and the
orchestrator's framing of this re-gate — silently agree is the defect.

## Thesis

Last round I showed the oracle was *wrong* (the `marketing_only` flag was a
`validate.py` misfire). That got fixed. This round all three reviewers have
independently proven a *different* fact, three ways:

- **injection-attacker:** the hostile orderings that matter are untested "by
  construction"; the fixture has one doc per tier, so no flood/first-write race
  can occur in it.
- **schema-purist:** a naive pre-v2 implementation reproduces
  `expected_analysis.json` **byte-for-byte** — none of the four new fixes are
  load-bearing (I re-ran his arithmetic; he is right, see §2).
- **pragmatist:** the guards are "dead on arrival for this fixture," and the plan
  proposes to *manufacture* fixtures to justify them — the test-justifies-code
  inversion, worse than v1.

They agree on the fact — **the golden still doesn't exercise the guards, two gates
in** — and they've stopped arguing about whether that fact is true. So has the
orchestrator, whose brief treats "STILL doesn't exercise the guards" as the shared
thread. **That agreement is the tell.** Everyone has concluded the golden's
failure to fire the guards is a defect to be closed — by adding cases
(schema-purist), by deleting code (pragmatist), or by naming decisions
(injection). Not one of them asked the prior question: *is a single acceptance
golden built from honest curated sources even the right instrument to test an
adversarial guard — and if it structurally cannot be, whose bug is that?*

It is not the golden's bug. It is the bug of asking one fixture to do two jobs
that pull in opposite directions. That conflation is the actual defect, and it is
load-bearing in the re-gate's own framing.

---

## 1. The sharpest SURFACE conflict — and it is decidable by arithmetic, so do not average it

schema-purist (**BLOCK**) and pragmatist (**CONDITIONAL**) collide head-on over a
checkable fact, and schema-purist called it out by name rather than let it get
split:

- **pragmatist**, "What's NOT overbuilt": *"the perf_per_watt group ... really does
  need both [is_relative + suspect-exclusion] rules to land on `contradicted`
  rather than a false `corroborated`, and the golden would go red without them."*
- **schema-purist**, Finding 1: the exclusion is *invoked and produces a result
  indistinguishable from not running it at all.*

I re-ran the numbers (both reviewers invited it; it takes thirty seconds):

- perf_per_watt spread = (1.8 − 1.3)/1.3 = **38.5%**, far outside ±10% → a naive
  "≥2 within tolerance else contradicted-on-spread" check lands on `contradicted`
  **with zero knowledge of `sparsity`.**
- `favored_tier` = min tier present = **2**, whether computed over all members
  `{2,3}` or over non-suspect members `{2}` — the suspect member is the *higher*
  (less-trusted) tier, so excluding it can never change which tier wins.

**pragmatist's one concrete "the golden needs this" claim is arithmetically false.**
The golden does NOT go red without those two rules on this group. This is not a
judgment call to be averaged into "both have a point"; it is a fact, and
schema-purist has it. The merge must record: *pragmatist loses this exchange on
the numbers, which means schema-purist's byte-for-byte finding stands unrebutted.*

But naming who wins the surface fight is the small prize. The reason pragmatist
could be wrong here while still being *right* that manufacturing a fixture is an
inversion — and schema-purist right that the golden is insensitive while still
*wrong* to prescribe BLOCK-until-the-golden-forces-it — is that **they are fighting
over the wrong fixture.** The real fault line runs the other way.

## 2. The unexamined assumption all three (and the orchestrator) share

Every one of them measures a finding by the same yardstick: *does the golden
exercise it?* schema-purist: no → the fixture is incomplete, add cases. pragmatist:
no → the code is dead, delete it. injection: no → name it as an open decision so
it isn't lost. **All three treat "the acceptance golden should exercise this guard"
as an axiom.** The orchestrator's own shared-thread — "the acceptance fixture STILL
doesn't exercise the guards" — is that same axiom, stated as a grievance.

The axiom is false, and it is the disease.

The acceptance golden has ONE legitimate job: **demonstrate the MVP's value** —
three friendly, curated, honest sources in, a correct corroboration/divergence
report out. That is a happy-path value demonstration. A guard — tier-precedence on
a hostile-first null-fill, baseline-poison rejection, an alias gate, a
tier-diversity floor against flooding — is an **adversarial** artifact. On honest
data, a correctly-built guard is a **no-op by construction**: honest data contains
no hostile-first ordering, no poison baseline, no colluding tier-3 flood, no
unvetted alias, so the guard never fires and the naive and hardened implementations
produce identical output. **That is not a defect. That is what "the data is honest"
means.** Demanding the value-demonstration golden also fire the guards is demanding
the demonstration contain the attack — which corrupts its role as a demonstration
and guarantees exactly the "naive impl reproduces it byte-for-byte" result
schema-purist reports as damning. He has proven that the honest golden behaves like
an honest golden and read it as a scandal.

So schema-purist's byte-for-byte finding, though factually airtight (§1), does not
carry the disposition he attaches to it (BLOCK, add golden cases) **for the guards
that are adversarial.** A happy-path golden SHOULD be naive-reproducible for those.
The fix is not to poison the demonstration; it is to stop using the one golden as
the coverage oracle for adversarial guards at all.

## 3. The reclassification the group avoided: two domains, opposite dispositions

Once you drop the axiom, the findings split cleanly into two classes that the
"untested guard" language has been flattening into one — and the two classes need
**opposite** dispositions. This is the split that dissolves the ceiling/floor war.

**Class A — HOSTILE-INPUT guards (injection-attacker's entire lane).**
Tier-precedence on hostile-first reconciliation (F1); poisoning a *resolved* real
competitor's group via `baseline_entity` (his Risk); tier-3 flooding to
`corroborated` (F2/H); ungated alias injection (G). Every one of these requires a
**hostile document reaching the reconciler.** Check whether it can, in this slice:
the acceptance test feeds `persist_extraction` hand-curated *post-extraction*
`ExtractionResult` fixtures (`source_*.json`'s own `_note`: "Post-extraction
ExtractionResult ... loaded into the store"). CLAUDE.md: ingest network fetch is
**WIP**, extract LLM is **WIP/stub**, and *"Do NOT wire `run_extract` → `insert_*`
until the persistence workstream defines how a second document ... is merged."*
**There is no pathway for a hostile document to arrive in this MVP.** injection is
threat-modeling an attacker who cannot reach the system yet.

He has a fair rebuttal — the reconciliation code being written *now* is precisely
the future trust boundary CLAUDE.md assigns to "the store workstream's job," so it
deserves a threat model even before the hostile source exists. Granted. But there
is a difference the reviews conflate: **designing the reconciler so it CAN hold a
boundary later** (leave the seam; name the decision) versus **building and
fixture-testing the enforcement NOW** (against inputs that can't arrive). The first
is cheap and correct; injection's real, defensible ask is "give the
poison-baseline case a decision letter, the way P2 named the dangling case." The
second is pragmatist's inversion — and it is *worse* than pragmatist frames it: it
is not merely code without a test-justification, it is a lock manufactured for a
door that is not yet installed, plus a synthetic fixture manufactured to prove the
lock turns. Disposition for **all of Class A: name the seam now (decision letters
K, G, H, I), defer the enforcement code AND its fixtures to the workstream that
actually ingests hostile input, and gate THAT workstream on a named adversarial
suite — never this golden.**

**Class B — HONEST-INPUT correctness (schema-purist's actual turf).** These bite
the honest curated corpus this MVP runs on **today**, and they are NOT guards
against anyone:

- **The clean+sparsity-agree status gap (his Finding 2) is the killer, and it is
  mis-dressed.** Two honest sources — a foundry's clean tier-2 number and a vendor
  deck honestly *disclosing* `sparsity` — agreeing within tolerance (I ran it:
  1.30 vs 1.35 = 3.8% spread, inside ±10%, non-suspect count 1). Run the plan's own
  rules: not `corroborated` (only 1 non-suspect), not `contradicted` (spread
  inside), not `uncorroborated`/singleton (2 members). The 3-value
  `CorroborationStatus` enum (`models.py:86-89`, verified) **has no slot for it.**
  This is the single most COMMON real corroboration pattern in this domain — a
  foundry figure plus a vendor deck that discloses its sparsity lever — and the
  algorithm assigns it *no status at all.* It needs **zero hostile input.** It is
  not a "guard the fixture doesn't exercise"; it is a total-function hole in the
  algorithm over the honest domain, and resolving it (a fourth bucket, or widening
  "uncorroborated" to "<2 non-suspect regardless of size") is a **schema/semantics
  decision the human owes** — bigger than "add a golden case." Even schema-purist
  mis-filed it, presenting it as "the case that would test F2," which is why it is
  about to be bucketed with the exotic guards and deferred.
- **The absent absolute claim (his structural point):** zero of six claims are
  `is_relative:false`; the group-key fix has no honest absolute claim to
  demonstrate on. Honest data absolutely contains absolute claims. This is honest
  coverage, not attack coverage.

For Class B, schema-purist's floor instinct is **correct** — and pragmatist's
"don't manufacture fixtures" does NOT apply, because an honest absolute claim, or
an honest clean+sparsity-agree pair, is not *manufactured*: those claim-types exist
in the real curated corpus independent of any code. Enriching the honest golden to
contain the honest patterns the algorithm claims to handle is making the
demonstration *honest and complete*, not building a fixture to justify a branch.
Disposition for **all of Class B: fix now; decide the enum question before build;
enrich the honest golden with an absolute claim and a clean+sparsity-agree pair.**

**The through-line that proves the framing failed twice:** the v2 golden's flags
are `[]`, `["sparsity"]`, `["sparsity","single_source"]`,
`["unresolved_baseline","single_source"]`. **`marketing_only` — the flag the
ENTIRE first gate was about — now appears nowhere.** The P1 fix "resolved" the v1
misfire by making the `marketing_only` branch require both vendors resolved
(`validate.py:270-275`); since `vendorslide` never declares `tsmc_n3e`, the branch
fires *nowhere* in the fixture. So the contested guard was not tested correctly —
it was **removed from the oracle.** Both gates, the same guard dodged the fixture:
v1 by encoding it as a bug, v2 by regenerating it out of existence. The re-gate
validated last round's homework (P1, P2 — the only load-bearing new items) and
tested **none** of this round's four proposals. That is the axiom in §2 producing
the identical outcome a second time, wearing "regenerated" as its disguise.

## 4. The scenario where all three — and the orchestrator's framing — are wrong at once

The human reads three thoughtful opinions and does the reasonable, additive thing:
ratifies decisions G–K, asks the implementer to add a unit test per guard
(satisfying injection's "name it," schema-purist's floor, pragmatist's "no untested
branch"), and keeps the honest golden as-is. Result:

1. The implementer hand-writes synthetic unit tests for tier-precedence,
   baseline-poison, flooding-floor, alias-gate — each using **author-picked**
   synthetic tier/entity values, because no real input produces them. Code and
   test are co-authored to agree (pragmatist's inversion, exactly). They pass
   forever, prove nothing, and defend an attacker with no pathway into the slice
   (ingest/extract stub). Dead weight that survives by inertia — the fate
   pragmatist predicted in v1 and again here.
2. **The clean+sparsity-agree gap gets a unit test too — and that is the
   catastrophe hiding inside the reasonable plan.** Because it was bucketed as
   "just another guard to cover," the test encodes whatever status the implementer
   *picked* to fill the enum hole, with **no ratified semantics**, since nobody
   flagged it as a schema decision the human owed. The honest corpus then silently
   mis-buckets every foundry-number-plus-honest-vendor-deck group — the **most
   common real pattern** — for the entire life of the MVP, with a green test
   blessing it.

All are wrong because the "untested guard" framing flattened a **schema-completeness
decision that bites common honest data** into the same bucket as **hostile-guard
theater that defends an uninstalled door** — and the common, load-bearing case gets
the *least* scrutiny precisely because it wore the same "coverage gap" costume as
the exotic ones. The orchestrator's framing risks the same flattening: it correctly
suspects injection is modeling a source that doesn't exist and schema-purist's gaps
are what bite honest data — but by calling both "guards the fixture doesn't
exercise," it invites the uniform disposition (defer both, or test both) that gets
Class B wrong.

## 5. The one question the group avoided

Last round's avoided question was "did anyone run their fix back through the
oracle?" This round they **did** — the byte-for-byte finding is the answer. So they
climbed one rung. The rung above, which none of the three and neither gate's
framing has stated, is:

> **For each finding, can its threat even OCCUR in the input domain this slice
> actually runs on — honest, hand-curated, post-extraction fixtures with no
> hostile-ingest pathway? And if it cannot, why are we gating it on the same
> fixture as the findings that can?**

Nobody asked whether a finding's *threat* is reachable in the slice. injection
never asked "can a hostile document reach `persist_extraction` in this MVP?"
(no — ingest WIP, extract stub, curated fixtures). schema-purist never asked "does
clean+sparsity-agree require a hostile source, or two honest ones?" (two honest
ones — it is not a guard at all). pragmatist got closest — "dead against this
fixture" — but stopped at "don't build dead code," never separating
*dead-because-premature* (hostile, defer) from *dead-because-the-honest-golden-is-
too-small-to-show-an-honest-case* (Class B, fix and enrich). Answer the question and
the ceiling/floor war ends: it was never one spectrum, it was two domains needing
opposite calls, argued as if they were one because everyone measured against one
fixture.

---

## What GATE 1 v2 must actually decide

The plan is not the blocker and the golden is not (this round) *wrong*; the blocker
is that **one acceptance golden is being asked to be both a value demonstration and
an adversarial guard-oracle, and it cannot be both.** Split the instrument:

1. **Keep the honest golden as a pure value demo.** Its naive-reproducibility for
   the *adversarial* guards is correct and expected — stop treating it as a defect.
2. **Class B (honest-domain correctness) — decide and fix NOW, before build.**
   Ratify the missing status for clean+sparsity-agree (fourth bucket, or a widened
   "uncorroborated = <2 non-suspect regardless of raw size") — this is a schema
   decision the human owes, not a fixture line. Enrich the honest golden with one
   absolute claim and one clean+sparsity-agree pair, because those are honest
   patterns the algorithm claims to handle, not manufactured branches.
3. **Class A (hostile-domain guards) — NAME the seams now, DEFER the enforcement.**
   Give injection's four items decision letters (K: does tier ever override a
   non-null value; G: alias gating; H: status-level tier-diversity floor, not a
   confidence adjective; plus the poison-resolved-baseline case P2 never covered).
   Design the reconciler not to paint into a corner. But defer the enforcement code
   **and** its fixtures to the workstream that ingests hostile input, gated on a
   **named adversarial suite** — never the acceptance golden. Do not manufacture a
   hostile fixture now to justify a lock on a door not yet installed.

Do that and both surface verdicts reconcile without averaging: **schema-purist's
BLOCK is right about Class B and should hold there** (with the enum decision, not
merely "add a case"); **pragmatist's cut is right about Class A** (defer, don't
manufacture); **injection's "name it" is right for Class A seams** and his "test the
hostile ordering" belongs to the deferred adversarial suite, not this gate. The one
thing the merge must NOT do is what the shared "untested guard" thread invites:
treat all of it as a single coverage gap and hand it one uniform disposition.

---

*Verdict (advisory): the defect is the conflation, not the plan. One golden cannot
demonstrate value on honest data AND test guards against a hostile source that has
no pathway into this slice. Separate the honest-domain correctness (decide the enum
gap and fix now) from the hostile-domain guards (name the seams, defer the code and
its fixtures to the workstream that actually ingests hostile input). schema-purist
wins the perf_per_watt arithmetic against pragmatist; do not average that away.*
