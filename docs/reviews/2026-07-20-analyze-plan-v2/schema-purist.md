# schema-purist review — Analytical MVP Slice plan v2 (GATE 1, re-gate)

**Verdict: BLOCK**

Real progress happened: P1 (`marketing_only` cross-vendor-only) is a committed
code fix with a green test, not a plan promise, and I'm crediting it fully. P2
(dangling baseline → `unresolved_baseline`) is in the golden and works. The
prose for all four things I blocked on last round — group-key `is_relative`,
suspect-exclusion-from-count, citation-on-null-fill, the slug tripwire — is
also *better written*: closer to pseudocode than sentiment. But "better
written" is not the bar. The bar is: does the regenerated fixture prove the
algorithm is what ships, or does it still let a plan that changed nothing
pass? I walked all six claims across all three source files against all four
assessments by hand. Verdict: **the golden is insensitive to every one of the
four claimed fixes.** A pre-v2 implementation — old group key (no
`is_relative`), no suspect-exclusion, no attribute-citation propagation, no
tripwire — reproduces `expected_analysis.json` byte-for-byte. That is the
exact defect I blocked v1 for, now wearing better prose.

## Finding 1 — none of the four "fixed" items are load-bearing in the regenerated golden; I can prove it by exhaustion, and this directly contradicts pragmatist-shipper's read

Walk every assessment with a naive (pre-fix) implementation — old key
`(entity_id, metric, baseline_entity)`, no `is_relative` join, no
suspect-exclusion from the `≥2 within tolerance` count:

- **logic_speed** (hotchips tier 1 @1.18, tsmc_pr tier 2 @1.15): both clean,
  no suspect member exists to exclude. Naive and fixed implementations are
  identical here by construction — there's nothing for the fix to change.
  Spread 2.6% < 10% → `corroborated` either way.
- **perf_per_watt** (tsmc_pr tier 2 @1.3 clean, vendorslide tier 3 @1.8
  sparsity): spread = (1.8−1.3)/1.3 = **38.5%**, already outside ±10%
  *before* any suspect-exclusion logic runs. A naive "≥2 within tolerance,
  full stop" check computes spread-beyond-tolerance and lands on
  `contradicted` with zero knowledge of `sparsity`. `favored_tier` = min tier
  present = 2, whether you compute min over *all* members `{2,3}` or min
  over *non-suspect* members `{2}` — **same answer**, because the suspect
  member happens to be the higher (less-trusted) tier, so excluding it never
  changes which tier wins. The exclusion algorithm is invoked and produces a
  result indistinguishable from not running it at all.
- **throughput**: `vendorslide` is the *only* claim on this metric — group
  size 1 with or without a suspect-exclusion rule, since there's no second
  member to exclude down from. `uncorroborated` either way.
- **logic_density**: same — singleton, dangling baseline. Governed entirely
  by P2 (already proven, already credited), not by F1/F2.

Every one of the four assessments is reachable by a pre-v2 implementation. I
raised exactly this failure mode against v1 ("the fixture never exercises
this... nothing forces the implementer to notice") and the plan's response
was to rewrite the prose, not to add a golden case that needs the prose to be
true. Two concrete absences confirm it structurally, not just by outcome:
**zero of the six claims across all three source files have `is_relative:
false`**, and **zero have `baseline_stated: false`** — so the group-key fix
has no absolute claim and no unstated-baseline claim anywhere to even
*attempt* to misgroup. And **zero of the three source documents populate a
single `node`/`chip` attribute** on any entity — so the null-fill +
`attribute_citations` propagation rule (§1, my prior F3) has no non-null
value anywhere in the golden to fill with, let alone a citation to propagate
or drop.

I want to name a direct disagreement rather than let it get averaged: this is a **hard fact
disagreement with pragmatist-shipper**, whose review states "[t]he grouping-key fix
(`is_relative` added, schema-purist F1) and the corroboration-count exclusion
of suspect members (F2) are both directly exercised by the golden — the
perf_per_watt group ... really does need both rules to land on `contradicted`
rather than a false `corroborated`." The arithmetic above shows this is not
so: perf_per_watt lands on `contradicted` from spread alone, and
`favored_tier` is invariant to the exclusion because the suspect member is
already the non-winning tier. I'd ask the orchestrator to re-run the numbers
rather than split the difference — this isn't a judgment call, it's an
arithmetic check either reviewer can redo in thirty seconds.

## Finding 2 — the tightened exclusion rule creates a status the schema's 3-value enum can't express, and the plan never assigns it

`claim.corroboration.status` is a closed enum: `[uncorroborated, corroborated,
contradicted]`. §2's verdict rule reads: `corroborated` = "≥2 non-suspect
within tolerance"; `contradicted` = "spread beyond tolerance"; `uncorroborated`
= "singleton." Construct the case the orchestrator asked me to attack directly:
a 2-member group, one clean (tier 2 @1.30) and one `sparsity=true` (tier 3
@1.35) — 3.8% spread, comfortably inside ±10%, i.e. **not** beyond tolerance.
Non-suspect count = 1, so it fails the `corroborated` bar. Run it against all
three definitions:

- `corroborated`? No — only 1 non-suspect member, needs ≥2.
- `contradicted`? No — spread is *inside* tolerance; the members agree.
- `uncorroborated` (singleton)? No — the group literally has 2 members. It
  is not a singleton by any reading of that word used elsewhere in the same
  plan (throughput and logic_density are the plan's own singleton examples,
  both group-size-1).

None of the three enum values the schema actually has applies under the
definitions as written. This is not a hypothetical edge case dodging the
fixture by bad luck — it's the *exact* scenario the orchestrator flagged as
untested (clean+sparsity agreeing within tolerance), and tightening the
exclusion rule to fix F2 is precisely what manufactured this new hole: v1's
looser "≥2 within tolerance, full stop" rule never had this gap because it
never distinguished suspect from non-suspect membership in the first place.
The plan must state explicitly that "uncorroborated" means "fewer than 2
non-suspect members regardless of raw group size" (widening the definition
away from literal singleton), or invent a fourth bucket the schema doesn't
have room for. Either way this needs to be written down as an algorithm
before GATE 2, not discovered by whoever implements §2 first.

## Finding 3 — two of my v1 "fixed" items are fixed on paper only: `related_claim_ids` symmetry is moot under Decision C, and the tripwire is still not fail-loud

Two residuals from my prior review, both listed by the plan as resolved,
neither actually is:

1. **`related_claim_ids` symmetry (F1 secondary).** §2 states "`related_claim_ids`
   linked symmetrically for every non-singleton group, contradicted included."
   But §2's Write-back bullet, two lines later, states Decision C is
   derive-on-read: `analyze` "does NOT mutate `claim.corroboration` in the
   store this iteration." Those two statements can't both be fully true of
   the *persisted schema field* — if nothing writes back, `claim.
   corroboration.related_claim_ids` stays `[]` for **every** claim,
   corroborated or contradicted alike, this iteration. That's arguably an
   improvement over v1 (symmetric emptiness beats asymmetric emptiness), but
   it is not the fix the plan claims — a downstream reader of a *stored*
   `tsmc_pr_n2:perf_per_watt` row still has zero pointer to
   `vendorslide:perf_per_watt`, exactly the gap I raised in v1. If "symmetric
   linkage" means "only inside the in-memory `AnalysisReport`, never
   persisted," the plan needs to say so plainly instead of listing F1 as
   closed — and the regenerated `expected_analysis.json` doesn't even carry
   a `related_claim_ids` key on any assessment, so there's nothing to check
   this against either way.
2. **The slug tripwire is `warn`, not fail-loud** — my prior top risk. §1
   says "emit a warning." §5 Decision J lists `warn` as the *proposed*
   default, with fail-loud named only as an alternative still open. A
   warning nobody's required to read is operationally the same as silence
   for an offline batch job with no human in the loop — which is precisely
   the failure mode CLAUDE.md's plain-`INSERT`-not-`INSERT OR REPLACE`
   design exists to avoid elsewhere in this codebase. Naming it as an open
   decision is honest, but the plan's own §0 summary claims "v2 ... names
   what's still open," yet §1's body prose states the tripwire as if `warn`
   were the ratified behavior, not the pending question it actually is.
   Also unexercised: no two entities in the fixture share `(entity_type,
   vendor)` with *any* alias-token overlap and different `entity_id`s — the
   collision path has never once executed, correctly or incorrectly, against
   real data.

## Risk others will miss: Decision G (alias-union gating, still open) quietly undermines the one mitigation Decision J is trying to buy back

The new slug-collision tripwire (my own prior remediation) detects collisions
by `(entity_type, vendor)` + "high alias-token overlap." Its entire signal
comes from the `aliases` list. But `aliases: [string]` in the schema is a
**bare list with no `attribute_citations` entry** — the schema's citation-
per-value law (`attribute_citations` keyed by "attribute-path", e.g.
`node.transistor_type`) structurally does not reach aliases at all. Combine
that with Decision G, explicitly still open in §5 ("ungated union ... vs
tier-restricted vs citation-required"), and the fixture already tells you
which way this resolves by default: `vendorslide` (tier 3, the *least*
trusted source) contributes the alias `"2nm-class"` with zero citation, and
it's unconditionally unioned into `entities_reconciled.tsmc_n2.aliases` in
the accepted golden. Nobody voted for ungated union as a ratified decision —
it's just what the regenerated fixture already does, which means by the time
GATE 2 reads "Decision G: open," the behavior is already fossilized in the
accepted DoD. That matters here specifically because an uncited, ungated
alias from the lowest-trust tier is exactly the kind of string the tripwire
leans on for its similarity check: a tier-3 document contributing a
marketing buzzword shared with an *unrelated* entity produces a false-positive
warning (noise that trains people to ignore the tripwire), while a tier-3
document *omitting* a buzzword that would have linked two really-identical
entities lets a true collision slide under the token-overlap threshold with
no warning at all. The plan treats G (alias gating) and J (tripwire
strength) as independent open decisions in §5; they are not independent —
J's reliability is upper-bounded by whatever G resolves to, and right now G
is resolving itself by fixture-fossilization rather than by argument.

## Answering the gate's specific questions

- **Is each fix now an algorithm, not prose?** Mostly yes on the page — §2's
  group key and exclusion rule read as implementable pseudocode now, a real
  improvement over v1's sentences. But Finding 2 shows the exclusion
  algorithm, tightened to close F2, opens an unassigned fourth status the
  3-value enum has no slot for — "algorithm" that doesn't cover its own
  domain isn't done.
- **Does the regenerated fixture exercise them, or does a naive
  implementation still pass?** A naive (pre-v2) implementation still passes
  byte-for-byte — see Finding 1's exhaustive walk of all four assessments.
- **Does the suspect-exclusion rule have a golden case where clean+sparsity
  agree within tolerance and must NOT corroborate?** No. `perf_per_watt` is
  38.5% apart — spread alone already forces `contradicted`, so the exclusion
  logic never has to do any work to get the right answer on this fixture.
  Worse than "untested": per Finding 2, the exact case that *would* test it
  (clean+sparsity agreeing) currently has no defined status to test against.
- **Is `related_claim_ids` symmetric linkage tested?** No — not tested, and
  per Finding 3, not even meaningfully *true* of the persisted schema field
  this iteration given Decision C's write-back deferral.
- **Is the tripwire fail-loud or a warning?** Still a warning; fail-loud is
  listed as an alternative under still-open Decision J, not the proposed
  default. My v1 risk is unresolved, only downgraded to a named open
  question with the weaker option in the driver's seat.
