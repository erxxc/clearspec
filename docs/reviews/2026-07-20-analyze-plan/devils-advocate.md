# devils-advocate — GATE 1, attack on the consensus

**Role:** run last; attack what the other three agree on. I am not scoring the
plan. I am scoring the thing all three of them silently trusted.

## Thesis

All three reviewers argue about whether the analyze code is too big
(pragmatist), too small (schema-purist), or too trusting (injection-attacker).
Every one of them treats `expected_analysis.json` as the fixed point they are
measuring against. **The fixed point is wrong.** I can show — in the codebase's
own code, not by rhetoric — that the golden's single most load-bearing flag
(`marketing_only` on the vendor claims) exists *only* because of the exact
trust-boundary bypass injection-attacker flagged and then declined to push on.
The oracle encodes the bug as the right answer. Three verdicts computed against
a broken oracle are three arguments about the wrong target.

---

## 1. The collision they were told to resolve is real — and unresolvable at the code layer

pragmatist says: cut Decision F (conflict-flag), Decision C (write-back),
Decision E (tier-weighted confidence) — *"the golden doesn't touch it, so don't
build it."* schema-purist and injection-attacker say the opposite from the same
fact: the golden *doesn't* exercise the same-baseline loophole, the marketing-
pair loophole, the alias gate, or the cross-doc FK — *"therefore the golden is
incomplete, build the guard."*

Name it plainly: **pragmatist treats the golden as a ceiling ("if it can't see
it, delete it"); schema-purist treats the golden as a floor ("if it can't see
it, that's a hole in the golden, fill it").** Those are not two positions on a
spectrum you can average — they are opposite theories of what a fixture *is*.
An implementer handed both reviews has no spec; they have a coin flip that
decides whether `analyze` is 40 lines or 400.

And here is the part the merge cannot paper over: **every substantive guard the
other two demand is a no-op on the golden.** schema-purist's fix (add
`is_relative` to the group key) changes nothing — all five fixture claims are
`is_relative: true, baseline_stated: true`. injection-attacker's fix (flag an
`unresolved_baseline`) never fires — `tsmc_n3e` *does* exist in the store by the
time vendorslide is analyzed. So both reviewers are demanding branches the
golden cannot execute, while pragmatist's stated bar ("no untested branch")
demands deleting exactly those branches. **The three reviews are not merely in
tension; two of them prescribe additions that the third's own rule forbids, and
the tie-breaker they'd normally defer to — the golden — cannot arbitrate its own
correct size.** That is the tell that the golden is the problem, not the code.

## 2. The shared assumption nobody checked: that the golden's flags are correct

Read what each reviewer did with `marketing_only`:

- **pragmatist**, under "What's NOT overbuilt," blesses it explicitly: *"favored_tier
  ... and flags [are] appropriately narrow ... matching the fixture."* He read
  `models.py`, `db.py`, both migrations — but not the branch in
  `extract/validate.py` that actually *sets* the flag.
- **schema-purist** builds his entire Finding 2 on top of the fixture's
  `perf_per_watt` marketing case, treating its `marketing_only` label as a given
  and complaining only that it's "so far outside tolerance the exclusion rule is
  never invoked." He never asked *why* that claim is `marketing_only`.
- **injection-attacker** found the FK bypass mechanically (his Risk section) but
  stopped at "it skews `spread_pct`/`favored_tier`." He missed that the same
  bypass *manufactures the `marketing_only` flag*.

So all three ratified `marketing_only` as a correct label. Here is why it is not.

## 3. The self-contradiction, traced in code

`validate.py` decides `marketing_only` at extraction time (lines 262-268):

```python
if (claim.conditions.sparsity is True
        and claim.comparison.is_relative
        and claim.comparison.baseline_entity is not None
        and vendor_of.get(claim.entity_id)
        != vendor_of.get(claim.comparison.baseline_entity)):
    claim.completeness = models.Completeness.marketing_only
```

`vendor_of` is built from **this document's own entities only** (line 229). Now
run `source_vendor.json` through it. vendorslide declares exactly one entity:
`tsmc_n2` (vendor `"TSMC"`). It does **not** declare `tsmc_n3e`, yet both its
claims set `baseline_entity: "tsmc_n3e"`. Therefore:

- `vendor_of.get("tsmc_n2")` → `"TSMC"`
- `vendor_of.get("tsmc_n3e")` → **`None`** (not in this document's proposal)
- `"TSMC" != None` → **`True`** → `completeness = marketing_only`

The claim is labeled `marketing_only` **because its baseline is ungrounded.**
The `!= vendor` test — meant to detect a *competitor* comparison — is fooled by
`None` into reading a same-vendor N2-vs-N3E comparison as cross-vendor.

Now resolve the baseline correctly (the thing injection-attacker demands, the
thing CLAUDE.md calls "the store workstream's job"): vendorslide's `tsmc_n3e`
is TSMC's own prior node — same vendor. Had vendorslide declared it, or had the
store resolved the cross-document reference, we'd have `"TSMC" != "TSMC"` →
`False` → **not `marketing_only`.** Per the schema's own definition
(CLAUDE.md: *"a sparsity+competitor claim is `marketing_only`"*; schema line 132:
*"sparsity=true + competitor comparison"*) an N2-vs-N3E claim is **not** a
competitor comparison and should never be `marketing_only` on that rule.

The chain is airtight and load-bearing:

> ungrounded baseline in the fixture → `vendor_of.get(baseline)` returns `None`
> → spurious "cross-vendor" → `completeness = marketing_only` baked into
> `source_vendor.json` → analyze propagates it as the group `flags` →
> `expected_analysis.json` asserts `"flags": ["marketing_only", "sparsity"]`
> (perf_per_watt) and `["marketing_only", "sparsity", "single_source"]`
> (throughput) as the **definition of done.**

The plan's §0 explicitly calls flags "the load-bearing assertions." The most
load-bearing of those flags is contingent on the unresolved-FK condition being
treated as normal. **The fixture that was "written first as the definition of
done" defines done as: reproduce the output of a trust-boundary bypass.**

(Same pattern, second instance: the golden's `aliases` union
`["2nm-class", "N2", "TSMC 2nm"]` bakes an *un-gated tier-3 vendor string*
(`"2nm-class"`, contributed only by vendorslide) into TSMC's canonical identity
as the *correct* answer. injection-attacker's Finding 2 remediation — a
tier-restricted or citation-required alias gate — would drop `"2nm-class"` and
turn the golden red. The fixture encodes the permissive behavior as truth in at
least two places.)

## 4. The scenario where all three are wrong at once

The moment anyone resolves `baseline_entity` across documents — which is not
optional, it is the workstream CLAUDE.md says must exist before persistence
ships — the fixture breaks in three directions simultaneously, and each
reviewer's fix fails to catch it:

1. `marketing_only` flips off on the vendor claims (same-vendor once resolved),
   so `expected_analysis.json`'s perf_per_watt and throughput `flags` no longer
   match. **pragmatist** blessed those flags as correct; he's wrong.
2. schema-purist's proposed group key `(entity_id, metric, is_relative,
   baseline_entity)` **still keys on the raw `baseline_entity` string**, so it
   never checks that the reference *resolves* — it only checks the strings
   match. His own fix is defeated by injection-attacker's risk, and he didn't
   notice they overlap on the same field. **schema-purist** thinks his key
   closes the baseline hole; it doesn't.
3. injection-attacker demanded baseline validation but recommended the *lenient*
   MVP form ("flag `unresolved_baseline` only if the entity is absent from the
   store") — precisely the form that keeps the golden green, because `tsmc_n3e`
   is present. He tuned his own remediation down to the exact strength that
   avoids reddening the oracle, without saying so. **injection-attacker** let
   the fixture cap his threat model.

Each reviewer diagnosed one organ of a single failure and prescribed a local
fix calibrated to the fixture's happy-path coincidences (consistent slugs,
matching baseline strings, one-entity-per-real-thing already true in the hand-
curated input). None asked whether those coincidences survive contact with real
`ingest → extract → store` output — where Decision A's own example (`tsmc_2nm`
vs `tsmc_n2`) guarantees they don't. They are hardening a house whose
foundation is the assumption that the ground is level.

## 5. The one question the group avoided

Nobody ran their own prescription back through the oracle. The question none of
the three asked:

> **If we implement the fix we are each demanding, does `expected_analysis.json`
> still pass — and if it doesn't, is the fixture wrong or is our fix wrong?**

Answered concretely: resolve the baseline (injection-attacker's ask) and the
`marketing_only` flags vanish, reddening the golden. Gate the alias union
(his Finding 2) and the `aliases` list changes, reddening the golden. Add
`is_relative` to the key (schema-purist) and *nothing* changes, so it ships
untested — which pragmatist's bar says to delete. **The security fix and the
acceptance test are mutually exclusive.** That contradiction was sitting in the
fixture the whole time, and the review structure — three angles all pointed at
the plan, none pointed at the oracle — was guaranteed to miss it.

## What GATE 1 must actually decide (before A–F)

The open decisions A–F are premature. They tune a mechanism against a target
that is itself unratified. The human owes an answer to one prior question, in
two parts:

1. **Is `marketing_only` correct for a same-vendor N2-vs-N3E sparsity claim?**
   If yes, then the *rule* is wrong — `marketing_only` must key off document
   tier/type or sparsity-alone, not entity-vendor comparison — and
   `validate.py` (not the analyze plan) is where the fix lands. If no, then the
   fixture is wrong and `expected_analysis.json`'s flags must change. Right now
   the fixture asserts a *third* thing: `marketing_only` produced by an
   accidental `None` vendor, which matches neither the coded rule nor the likely
   intent.
2. **Is the ungrounded cross-document `baseline_entity` load-bearing on
   purpose?** The plan makes it load-bearing (§0) without ever naming it as a
   decision. It must become an explicit decision — trust-the-string-and-flag, or
   resolve-and-reject — *and* the golden must be regenerated to whatever that
   decision produces, not frozen at what the bypass currently emits.

Until the oracle is ratified, the merge should not adjudicate pragmatist vs
schema-purist. Their conflict is not the disease; it is the fever. The disease
is that the definition of done was written before anyone checked whether the
system could produce it honestly — and it can't.

---

*Verdict (advisory): the plan is not the blocker; the acceptance fixture is.
Ratify or regenerate `expected_analysis.json` first — specifically the
`marketing_only` flags and the cross-document baseline it depends on — then
re-run this gate against a target that isn't self-contradictory.*
