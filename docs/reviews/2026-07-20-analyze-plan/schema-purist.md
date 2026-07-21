# schema-purist review — Analytical MVP Slice plan (GATE 1)

**Verdict: BLOCK**

The plan gets the easy parts of schema fidelity right (source_tier is joined from
`document`, never duplicated onto `claim`, matching both the schema and CLAUDE.md;
the write-back in Decision C is correctly scoped to the two fields the schema
actually has — `status` + `related_claim_ids` — and doesn't invent `confidence`/
`flags`/`tiers` as claim-level fields, keeping those report-only). But the two
rules this slice exists to enforce — "same baseline required to compare relative
claims" and "a marketing_only/sparsity claim can never corroborate a group" — are
stated as prose principles, not as algorithms, and the acceptance fixture doesn't
close either gap with a golden case. Per this schema's own doctrine ("the LLM
output is a PROPOSAL; validation is the guarantee" — the same logic applies to the
analysis code, which must not be trusted to self-enforce a rule it was merely told
about in a docstring), that's not shippable as-is.

## Finding 1 — the group-by key can silently compare an absolute against an unstated baseline

Section 3's grouping key is `(entity_id, metric, baseline_entity)`. It omits
`comparison.is_relative` and never addresses `comparison.baseline_stated`. Walk
the schema: `baseline_entity` is `entity_id?` — nullable. It is null for (a) a
non-relative/absolute claim (no baseline applies) and *also* for (b) a relative
claim whose source didn't name a baseline (`is_relative: true`,
`baseline_stated: false`, `baseline_entity: null`). Case (a) and case (b) are
schema-distinct — one is "no comparison exists," the other is "a comparison
exists but we don't know to what" — yet they produce the *same* group key. Under
the stated grouping rule, an absolute claim and an unstated-baseline relative
claim for the same `(entity_id, metric)` land in the same group and get
tolerance-compared, directly violating the plan's own stated law: "never
reconstruct an absolute to compare across baselines." This is precisely the "two
'x' claims with different baselines wrongly corroborating" failure the gate asked
me to attack, except it's worse than a same-baseline mixup — it's an apples-to-
`comparison.is_relative=false` mixup that the current key can't even see. The
fixture never exercises this (all three sources' claims are relative with a
stated, resolved `tsmc_n3e` baseline), so nothing forces the implementer to
notice. Fix: group key must be `(entity_id, metric, is_relative, baseline_entity)`
at minimum, and claims with `is_relative=true, baseline_stated=false` should
either form their own unmergeable singleton group (never comparable to anything,
since "unstated baseline" is not evidence the baselines match) or be excluded
from cross-claim comparison entirely and forced to `uncorroborated` with a
`missing_baseline`-style flag.

Secondary defect in the same section: write-back of `related_claim_ids` is only
described under the **corroborated** bullet ("`related_claim_ids` linked"). The
**contradicted** and **uncorroborated** bullets say nothing about it. If a
contradicted claim's `related_claim_ids` stays `[]`, a consumer reading
`tsmc_pr_n2:perf_per_watt` in isolation later has no stored pointer to
`vendorslide:perf_per_watt` — the very claim it was found to disagree with. The
field is generically named "related," not "corroborating-with," and the schema
gives no reason to leave it empty on disagreement. This should be spelled out as
symmetric linkage for every non-singleton group, corroborated or not.

## Finding 2 — the marketing_only/sparsity anti-inflation rule is a sentence, not an algorithm, and has no golden case that would catch a violation

The plan states the rule correctly in prose: "a `marketing_only` or
`sparsity=true` claim can NEVER by itself make a group `corroborated`." But
"corroborated" is defined two lines earlier as "≥2 members within tolerance" —
a pure count-and-spread test with no mention of `completeness` or
`conditions.sparsity` as inputs. Walk the failure case directly: a tier-2 clean
claim at 1.30x and a tier-3 `marketing_only`+`sparsity` claim at 1.35x (3.8%
spread, comfortably inside ±10%) is a 2-member group within tolerance. Nothing in
section 3 says this group is barred from `corroborated` — the marketing claim
isn't corroborating "by itself" (there are two members), so the stated rule
doesn't obviously fire, yet the *result* is exactly what the schema's
`marketing_only` tag exists to prevent: a sparsity-inflated number laundered into
a "high"-or-"low"-but-still-**corroborated** verdict by riding alongside one
legitimate source. The fixture doesn't test this: its only 2-clean-agree case
(`logic_speed`) has zero marketing participants, and its only marketing-involved
case (`perf_per_watt`, 38.5% spread) is so far outside tolerance the exclusion
rule is never actually invoked to do any work — a naive "≥2 within tolerance,
full stop" implementation would pass the entire acceptance golden while shipping
this exact loophole. Per this schema's own "code-enforced, never trusted to the
model" philosophy for citation grounding, the same standard applies here: the
rule must be implementable as "marketing_only/sparsity members are excluded from
the *count* required to reach corroborated (they may only ride along once ≥2
non-marketing members already agree, and even then `flags` must still surface
`marketing_only`/`sparsity` on the group)" — and GATE 2 needs a fixture case that
actually exercises a clean+marketing pair *agreeing* within tolerance, asserting
it does **not** come out `corroborated`.

Related and smaller: `confidence` is described as derived "from tier span"
(§3) with no mention of spread tightness. A group at 9.9% spread (just inside
tolerance) and a group at 0.5% spread would, under the stated rule, earn the same
tier-derived confidence label. That's a second, subtler way to "launder
disagreement into agreement" — a marginal pass at the tolerance boundary reads to
a report consumer as identically strong evidence as a near-exact match. Worth
folding spread magnitude into the confidence computation, not just tier
membership.

## Finding 3 — the reconciling upsert doesn't say what happens to `attribute_citations` on null-fill or on conflict

v2's headline change is `attribute_citations`: node/chip attributes now get the
same code-enforced grounding claims already had. Section 2's reconciling upsert
describes the *value* semantics correctly (fill null from newcomer, flag —
don't clobber — a non-null conflict), but never mentions the citation that must
travel with a filled value, nor what happens to citations on a flagged conflict.
Two concrete gaps: (1) when a null `node.transistor_type` is filled from a
newcomer document, does the newcomer's `attribute_citations["node.transistor_type"]`
entry get copied into the merged entity's `attribute_citations` map, or does the
attribute end up populated with no grounding on the merged record — silently
regressing the exact hallucination-control gap v2 was written to close? (2) On a
flagged conflict, is the *incoming* (losing) citation preserved anywhere for a
human to adjudicate the conflict, or discarded once the value is rejected? The
schema's `review_status: [unreviewed, human_verified, disputed]` on `document`
implies conflicts are meant to be human-adjudicable; a discarded citation makes
that impossible. This entire gap is invisible to the acceptance golden — none of
the three real fixture sources populate a single `node`/`chip` attribute, so the
DoD's "a synthetic attribute conflict is flagged, not clobbered" claim is only
as strong as an unwritten unit test the plan gestures at in §5 without specifying
whether it checks citation propagation or just the scalar value.

## Risk others will miss: Decision A fails silently, breaking the one integrity posture this codebase is consistent about elsewhere

Every other boundary in this system is fail-loud on purpose — CLAUDE.md is
explicit that plain `INSERT` (not `INSERT OR REPLACE`) was chosen for documents
and claims specifically so a colliding write *raises* instead of silently
corrupting provenance. Decision A quietly breaks that pattern for entities in the
one case that matters most: a source that slugs the same real-world node
differently (the plan's own example: `tsmc_2nm` vs `tsmc_n2`) doesn't raise, and
doesn't get flagged as a conflict either — it produces a second, entirely
valid-looking `entity` row with its own claim set. Nothing in persistence or
analyze has any way to know these two entities are the same real thing. The
downstream effect isn't a crash or a visible flag; it's *quiet
under-corroboration* — a metric that in reality has 3-source agreement silently
reports as 2-source, or a genuinely single-source claim on the phantom entity
reports as `uncorroborated`/`suspect` when a merge would have shown it
corroborated. That is the corroboration engine's core output being wrong with
zero signal that reconciliation failed. Decision A is framed in the plan as an
ordinary MVP scope cut ("alias-based canonical resolution is deferred"), and I
expect pragmatist-shipper to bless it on those terms — but the *mechanism* of
failure here is silent data corruption of the trust signal this whole slice
exists to produce, not merely "a feature we haven't built yet." At minimum this
needs a fail-loud tripwire: if two entities of the same `entity_type` +
`vendor` + overlapping alias-token-similarity exist after a batch load, surface
a warning/conflict record rather than letting them sit indistinguishable from a
correctly-reconciled entity.

## Answering the gate's specific questions

- **Same-baseline rule airtight?** No — see Finding 1. Two relative claims with
  *different, unstated* baselines can share a null `baseline_entity` and wrongly
  group. `is_relative` must join the group key.
- **Is marketing_only/sparsity truly barred from making a group corroborated?**
  Not as specified — see Finding 2. The prose rule and the algorithmic
  `≥2-within-tolerance` test aren't wired together; a clean+marketing pair that
  happens to agree slips through, untested by the golden.
- **Does the reconciling upsert preserve one-entity-per-real-thing without
  silently overwriting a grounded attribute?** The *value* protection is sound
  (fill-null / flag-conflict, never clobber) but citation propagation through
  that merge is unspecified (Finding 3), and the matching step itself
  (Decision A) can silently fail to merge the same real thing at all (Risk).
- **source_tier inheritance?** Correctly modeled as a join from `document`, not
  duplicated onto `claim` — matches schema and CLAUDE.md.
- **Write-back consistency?** Correctly scoped to the schema's actual
  `corroboration.{status,related_claim_ids}` fields, but incomplete for
  non-corroborated groups (Finding 1) and silent about re-run/invalidation
  semantics if `analyze` is ever run twice over a growing store — not exercised
  by this MVP but worth a named assumption ("single load-then-analyze pass, no
  incremental re-analysis") rather than leaving it unstated.
- **Tolerance/confidence defensible?** ±10% is explicitly flagged as an open
  decision (B) and I won't re-litigate the number, but the confidence label
  ignoring spread-within-tolerance (Finding 2, related) is a second, unflagged
  place where "barely passed" and "matched almost exactly" get laundered into
  the same trust label.
