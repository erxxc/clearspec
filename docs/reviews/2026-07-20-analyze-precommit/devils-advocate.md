# devils-advocate — GATE 2 (pre-commit), analyze MVP slice

I don't re-tally the diff. I attack what the other three AGREE on. All three
returned CONDITIONAL, and — more tellingly — all three converged on the same
*shape* of remedy for every finding: "unexercised → cover-or-cut," "stale column
→ add a NOTE," "zero-div → special-case `lo==0`." Every defect got filed as a
bounded, ten-minute fix. That unanimity is the thing worth distrusting, because
it required all three to share one frame, and the frame has a hole.

## 1. The shared wall, and the honest data it was never load-bearing for

Every reviewer leans on the same load-bearing beam: **"no hostile document can
reach this MVP"** (the Class-A deferral, ratified at GATE-1-v2). injection-attacker
says it outright ("no hostile document can reach `persist_extraction`"); pragmatist
says "curated fixtures only"; schema-purist says "correct on every path the golden
walks." That wall is real — for *input*. Nothing hostile gets in.

The unexamined assumption is that the wall also makes the **honest domain a solved
domain** — that "not adversarial" implies "the golden is representative of what
ships." It does not. The golden is a single point in the honest domain: three
specific documents, no zero-valued claims, no group of two absolute claims, no
case where the suspect member is the *higher*-trust tier, and exactly one write of
each doc. Watch the word "unexercised" travel through all three opinions — it is
always followed by "add a test," never by "this behavior is undefined on the data
we actually ship for."

**The scenario where all three are wrong at once:** a fourth honest, curated,
non-hostile document lands — the literal thing analyze *exists* to handle
(accumulating corroborating sources over time). Nothing in this diff, and nothing
any reviewer drove, characterizes the tool on a store that isn't the 3-doc golden.
Three of the four found bugs (zero-division, relative-ruler-on-absolutes,
`favored_tier` trust-precedence — below) that fire on **legal honest input**, no
adversary required. The Class-A wall quietly licensed a substitution: "we needn't
worry about the *adversarial* domain" became "the domain we *do* worry about is
the golden." The CONDITIONAL-not-BLOCK consensus rests on treating an
*uncharacterized* honest domain as a *covered* one.

And note the standard drift nobody owned: schema-purist **BLOCKED** v1 and v2 for
exactly "a naive implementation reproduces the golden — no fix is load-bearing."
This gate ships three fixes (`is_relative`, `marketing_only`, the absolute path)
that *by purist's own finding* the golden does not exercise — the zero-div branch,
the two-absolute-claim spread path, the isolated `is_relative` case all "reproduce
without being exercised." Same defect class. Yet the verdict softened from BLOCK to
"cheap, mechanical, CONDITIONAL." The bar moved between gates and no one said why.

## 2. The zero-division bug is a symptom: there is no absolute-tolerance model

All three treat `spread = (hi-lo)/lo*100 if lo else 0.0` as a point defect (guard
`hi==lo==0` separately, or floor `value` away from 0). That patches the crash and
misses the disease.

`spread_pct` is a **relative** dispersion measure and `TOLERANCE_PCT = 10.0` is a
**relative** threshold — and analyze applies that one ruler to *both* relative
claims (ratios like 1.15x) and absolute claims (65% yield, 3.5 GHz). The
`is_relative` group key was added precisely to keep the two *separated* — CLAUDE.md
makes "the distortion stays visible" a non-negotiable — and then `_assess` immediately
re-flattens them onto a single relative-percentage scale. "Within 10%" of a 1.15x
ratio and "within 10%" of a 65% yield (≈6.5 points) and "within 10%" of 3.5 GHz are
three different claims about the world, adjudicated by one number. The `lo == 0`
crash is just the one input where that unified ruler visibly detonates; the silent
failure is **every absolute claim quietly judged on a ruler built for ratios**.

The reviewers even had the evidence and stopped short. GATE-1-v2 required the golden
"enriched with an absolute claim … to prove the algorithm handles that domain." What
shipped is `yield_rate = 65.0`, a **singleton** — `len(members)==1` short-circuits
before any spread math runs. The one absolute case was satisfied by the one absolute
input that requires zero new arithmetic. The absolute *spread* path is not merely
untested (purist's point) — it is arguably wrong by construction, and the fixture is
structurally incapable of revealing it. "Special-case `lo==0`" would ship the disease
with the symptom bandaged. The real question — *does an absolute claim need an absolute
tolerance?* — went unasked.

I rate this to BLOCK severity, and the group didn't: a `[0.0, 40.0]` group (both
non-suspect, both honest) returns `status="corroborated", confidence="high"` — a
tool asserting **high-confidence agreement between two numbers that agree on nothing**.
A false positive verdict is the single worst output a corroboration engine can emit,
and it ships on legal honest data today.

## 3. The "two dead branches" are not the same animal — and injection-attacker cleared the dangerous one

Here is the agreement I most want to break. pragmatist and purist both lump
`marketing_only`-in-`_suspect` and the suspect-exclusion-in-`favored_tier` together
as "unexercised branches, resolve each the same way." They are categorically
different, and collapsing them is the shared error.

- **`_suspect()`'s `marketing_only` arm encodes a SCHEMA INVARIANT.**
  `marketing_only` is a first-class `Completeness` value whose CLAUDE.md-defined
  meaning is "too suspect to independently corroborate a clean number." `_suspect`
  honoring it *is* the correct semantics. Deleting it reopens, through the
  `marketing_only` door, the exact hole GATE-1-v2 closed for `sparsity`. This is
  **cover, don't cut** — the extraction-gate pattern, and purist is right.

- **`favored_tier`'s `min(... for c in (non_suspect or members))` is NOT dead
  schema-machinery. It is an unexercised, contestable TIER-PRECEDENCE decision.**
  Construct the honest case the golden omits: a contradicted group of a **tier-1
  conference talk that honestly discloses sparsity** and a **tier-3 vendor deck with
  a clean number**. `non_suspect = [tier-3 clean]`, so `favored_tier = 3`. Drop the
  exclusion and `min(all) = 1`. The exclusion therefore *flips the favored source
  from the tier-1 conference to the tier-3 vendor* — it favors vendor marketing over
  a conference talk **because the conference talk was honest about sparsity**.
  CLAUDE.md is explicit that `source_tier` (conf=1 > foundry=2 > vendor=3) is the
  trust weight. This branch lets a suspicion signal *override tier* — which is
  exactly the flavor of the deferred Class-A question **K** ("does anything ever
  override the tier ordering?"). It is not harmless speculative code; it is a
  latent trust-precedence rule that happens to agree with `min(all)` *only because*
  the golden never makes the suspect member the lower tier. pragmatist proved the
  suite stays green either way and read that as "harmless" — it is the opposite: the
  green suite is *concealing* a decision the gate was told to defer.

  This directly rebuts injection-attacker, who audited for "no enforcement code
  smuggled in" and pronounced the deferral "clean, not cosmetic." `favored_tier`'s
  `non_suspect or members` **is** cross-tier precedence logic — it changes which
  tier is trusted based on a suspicion flag. It slipped the injection audit for the
  same reason it slipped the other two: on the golden, suspect always equals higher
  tier, so the branch never speaks. The deferral is clean on *storage*; it is not
  clean in `favored_tier`.

So the correct disposition is not "cover-or-cut both." It is: **keep and test
`marketing_only`** (schema invariant), and **treat `favored_tier`'s exclusion as
undecided Class-A scope** — either delete the exclusion now (ship `favored_tier =
min(all members)`, tier-blind, matching the rest of the reconciler that was
deliberately made tier-blind) and defer sparsity-vs-tier precedence with a named
seam, or keep it and *name it in CLAUDE.md's deferred list as a live precedence
choice*. What it must not do is ship as anonymous "tie-break" code that silently
answers a deferred question.

## 4. The persisted verdict: derive-on-read didn't drop the column — it half-built write-back

The group's most comfortable agreement: the stale `claim.corr_status` is "ratified
derive-on-read, just document it." purist wants a NOTE in the migration; the others
don't touch it. Every one of them accepts the schema keeps a per-row home for this
fact. Interrogate that.

Migration 0003 pays for a **full table rebuild** — create `claim_v3`, copy, drop,
rename, reindex — expressly to carry `corr_status` / `corr_related_claim_ids`
forward "for schema fidelity + a future write-back path." Then every row is
populated with `'uncorroborated'` — a *positive, specific, wrong verdict* — while
the truth is derived elsewhere and thrown away. That is not clean derive-on-read.
Clean derive-on-read owns **no** persisted verdict column, or leaves it NULL/pending.
What shipped is the storage cost of write-back with none of its correctness, plus
the ephemerality of derive-on-read with none of its honesty. The design didn't
choose between the two models; it built half of each.

Two problems the "add a NOTE" fix not only misses but actively worsens:

- **A per-row column is the wrong shape for a per-group fact.** The verdict is
  computed over a *group* — `(entity, metric, is_relative, baseline, unit)` — a
  relationship *among* claims. `corr_status` is a *claim* attribute. You cannot
  write a group verdict into a per-row column without denormalizing it across every
  member (drift-prone) or picking a representative row (lossy). Of all four
  reviewers, the schema-purist should have caught that the schema's shape — not its
  staleness — is the defect: the verdict is not a property of a claim.

- **`uncorroborated` is overloaded across two opposite epistemic states.** As the
  persisted default it means *"not yet analyzed / unknown."* As a computed verdict
  it means *"analyzed, definitively single-source."* Those are opposites — ignorance
  versus a positive finding of solitude — and the enum cannot tell them apart. v3
  added `weakly_corroborated` but not the value derive-on-read actually forces: a
  distinct *"pending / not computed"* state, needed precisely *because* a default is
  persisted. purist blessed the enum ("all four values, no drift") and brushed the
  overload aside as "indistinguishable from never analyzed" — a documentation note.
  It is a modeling error: if you persist a default, it must mean "not computed," and
  `'uncorroborated'` is the one value that can't, because it is also a real verdict.

purist's proposed NOTE ("…always uncorroborated until a write-back path lands")
makes it worse: it *advertises* write-back as the intended end-state. The moment
someone builds it — `UPDATE claim SET corr_status` after analyze — there are two
computed truths: the persisted one (as of last write-back) and the derive-on-read
one (as of now, over current store contents). They disagree exactly when a new
source arrives between write-back and read — the one event this whole subsystem
exists to handle. The honest MVP move is the reverse of a NOTE: **make the columns
NULLable and leave them NULL** (or drop them from v3), so the schema states plainly
that analyze does not yet own a persisted per-row verdict. Nobody proposed removing
the column; all three proposed keeping and annotating it. Schema fidelity ("v3 == v2
shape + one enum value") was treated as sacred, when the actual v3 semantic — analyze
is derive-on-read — makes the column's *presence*, not its staleness, the defect.

## 5. The sharpest named conflict (cost stated, not averaged)

**schema-purist (keep + prove) vs. pragmatist-shipper (delete-or-earn) on the
unexercised branches.** purist: `marketing_only` is schema-mandated — keep it, add a
test; deleting reopens the sparsity hole through a new door. pragmatist: it's dead on
this suite — delete the OR-clause *or* earn it with a test, indifferent which, "ten
seconds either way."

Do not average this to "add the test and move on." The conflict is real and the two
branches split its resolution:
- On **`marketing_only`**: purist wins outright. It is a schema invariant; the
  cover-don't-cut precedent from the extraction gate binds. Cost of getting it wrong
  (pragmatist's delete): a suspect number silently corroborates a clean one the day
  live extraction sets `marketing_only` — a re-opened GATE-1-v2 hole, invisible on
  the golden. Cost of purist's keep: one unit test, zero runtime cost.
- On **`favored_tier`**: *neither* framing is right (see §3). It is not a schema
  invariant (so purist's "always keep" over-generalizes) and not harmless dead code
  (so pragmatist's "delete freely" is dangerous) — it is deferred Class-A precedence.
  Cost of pragmatist's silent delete: fine *today*, but it also silently answers K;
  cost of purist's silent keep: ships an un-named trust decision. Correct move: name
  it as deferred, and ship the tier-blind `min(all)` unless/until the precedence is
  decided — matching the deliberately tier-blind reconciler beside it.

## 6. The one question the group avoided

Not one reviewer drove `semianalyst report` — **the actual product surface** — on
any store other than the 3-doc golden. injection-attacker read `cli.py`, but only
for terminal-escape encoding of output; the algorithm was verified on six static
assessments; the storage was verified on one insert per doc. **What does this tool
do the first time a store holds anything but the golden?** — which is the first time
anyone uses it for its stated purpose (corroboration accumulates sources over time).

Because the verdict is derived over the *entire* store on every `report` invocation
and never persisted, the tool's behavior across accumulation is defined nowhere: not
in a test, not in a fixture, not in any reviewer's read. The zero-div false positive,
the relative-ruler-on-absolutes, and the `favored_tier` tier-flip are all latent
precisely there — in the multi-document, growing-store regime that is the *point* of
the feature and the *only* regime never looked at. The group verified the engine is
arithmetically correct on the one snapshot it was handed, and mistook that for
verifying the engine. The question they avoided is the only one the product raises:
**what is the corroboration verdict the second document changes it?**

## Bottom line

The consensus is directionally right on scope (this is not a hostile-input gate) and
right that most of the diff is a genuine minimal slice. But the shared "bounded
fixes/cuts/notes" frame under-rates two items to BLOCK severity on *honest* data —
the relative-tolerance model has no absolute mode (a live false-positive
"corroborated/high" on legal input, §2), and the persisted verdict is a schema
modeling error, not a stale column (per-group fact in a per-row home + an overloaded
default, §4) — and mis-classifies a third: `favored_tier`'s suspect-exclusion is
smuggled Class-A tier-precedence that the injection audit cleared and the coverage
debate mislabeled (§3). Keep `marketing_only` (schema invariant, add its test).
Before "ship after three cheap fixes," the human owes two decisions the group never
surfaced: (a) does an absolute claim get an absolute tolerance, and (b) does analyze
own a persisted per-row verdict at all — and if not, why did we rebuild the table to
keep a column we contradict on every row?
