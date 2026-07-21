# schema-purist review — analyze v1 + persist_extraction (GATE 2, precommit)

**Verdict: CONDITIONAL**

I was asked to verify that the four ratified Class-B fixes (`weakly_corroborated`
in schema v3; group key includes `is_relative`; suspect members excluded from the
corroborated count; an absolute claim handled) are each a real algorithm, correct,
and **exercised by the golden** — not just present in the diff. I re-did the
arithmetic on all six assessments by hand (values, tiers, spreads) and confirm the
shipped algorithm is correct on every path the golden actually walks: `logic_speed`
2.6%→corroborated, `perf_per_watt` 38.5%→contradicted (favored_tier=2 from spread
alone), `sram_density` 4.2%→weakly_corroborated (1 non-suspect), the singletons
uncorroborated. Schema v3 (`extraction_schema_v3.yaml`), `models.CorroborationStatus`,
and migration `0003`'s CHECK constraint are in lockstep — same four values, same
order, no drift. That part earns approval outright.

But "correct on the paths walked" is not the same as "the fix is what makes the
golden pass," and that gap — the exact thing I blocked v1/v2 for — still exists in
three places, one of them in the very item I was told to attack hardest
(`is_relative`). I'm conditioning on those three, not blocking outright, because
unlike v1/v2 these are now cheap, mechanical, test-only fixes to an algorithm that
is otherwise sound — not a redesign.

## Finding 1 — the `is_relative` group-key fix has a test, but the test can't tell if the fix is there

`src/semianalyst/analyze/corroborate.py:128-129` (group key: `(entity_id, metric,
is_relative, baseline_entity, unit)`) vs. its supposed proof,
`tests/test_analyze.py:79-87` (`test_absolute_and_relative_same_metric_do_not_group`):

```python
_cv("rel", "speed", 1.15, 2, is_relative=True, baseline="b"),
_cv("abs", "speed", 3.5, 2, is_relative=False, baseline=None, unit="GHz"),
```

Delete `is_relative` from the group-key tuple entirely and re-run this exact test:
it still passes. `baseline_entity` ("b" vs `None`) and `unit` ("x" vs "GHz") already
differ between the two claims, so the tuple separates them with or without
`is_relative` doing any work. The one test written specifically to prove GATE-1-v2's
demanded fix is present cannot detect its absence — this is precisely "trust code to
self-enforce a rule it was merely told about," now living in the test suite instead
of the implementation. The failure scenario `is_relative` is actually needed for —
two claims sharing the same `baseline_entity` and `unit` where one is a genuine
ratio and the other is an absolute value that happens to carry a leftover/mis-set
baseline reference (nothing in `Comparison` enforces `baseline_entity is None` when
`is_relative is False`) — has zero coverage anywhere in this diff. **Fix:** one more
`_cv` pair with identical `baseline` and `unit`, differing only in `is_relative`,
asserting they land in separate assessments. Five minutes; blocking because the
gate's own charge was to verify this exact thing is exercised, and it isn't.

## Finding 2 — `_suspect()`'s `marketing_only` arm is schema-mandated, not decorative, and it is completely dead code today

`corroborate.py:80-81`:
```python
def _suspect(claim: ClaimView) -> bool:
    return claim.sparsity is True or claim.completeness == "marketing_only"
```
I confirm pragmatist-shipper's grep: no fixture, no unit test, ever produces a
`ClaimView` with `completeness == "marketing_only"` reaching `analyze_claims`. I
disagree with pragmatist's proposed remedy of *either* deleting this arm *or*
adding a test — from the schema side those are not equally acceptable options.
CLAUDE.md is explicit: *"A sparsity+competitor claim is `completeness=marketing_only`
... One entity per real thing."* `marketing_only` is not a hypothetical future value;
it is a first-class `Completeness` enum member whose entire reason to exist is to
mark a claim too suspect to independently corroborate a clean one — exactly the
guarantee `_suspect()` exists to enforce. Deleting the OR-clause because it's
currently unreachable reopens the identical hole GATE-1-v2 fixed for `sparsity`
(a suspect number silently validating a clean one), just through the `marketing_only`
door instead. This is also the second time in two gates this exact flag has "dodged
the fixture" (GATE-1-v2's resolution: *"`marketing_only` ... appears nowhere in the
v2 fixture ... the contested guard dodged the fixture both times"*) — a pattern, not
a coincidence, and reason enough to insist it be proven, not removed. **Fix:** add
one `_cv(..., completeness="marketing_only")` case to `test_analyze.py` mirroring
`test_clean_plus_sparsity_agree_is_weakly_corroborated`. Keep the branch.

## Finding 3 — the zero-division guard silently converts a real divergence into a false agreement, and it's live in exactly the domain (absolute claims) this gate was told to enrich

`corroborate.py:88`: `spread = round((hi - lo) / lo * 100, 1) if lo else 0.0`.

`Claim.value` (`store/models.py:184`) is a bare `float` — no `gt=0`/`ge=0` constraint
in the model, no CHECK on the `value` column in any migration, and the schema
(`value: number`) states no floor. A value of exactly `0.0` is legal domain data
(a "0 known defects" claim, a 0% claim of some kind). If the lowest value in a group
is `0.0`, the `if lo else 0.0` guard fires and reports `spread_pct: 0.0` **regardless
of the other member's value** — a group of `[0.0, 40.0]` reports zero spread, i.e.
perfect agreement, and if both members are non-suspect it reports `status:
"corroborated"`, `confidence: "high"` on two numbers that disagree completely. This
is not a hypothetical: it's the direct consequence of guarding division-by-zero with
a value that means "no spread" instead of a value that means "spread is undefined /
maximal." GATE-1-v2 specifically asked for the golden to be "enriched with an
absolute claim" to prove the algorithm "handles" that domain (§ resolution, Class B) —
what shipped proves it handles a *lone* absolute claim (a singleton, which needs no
spread math at all since `len(members)==1` short-circuits first). No test anywhere
constructs two absolute claims in the same group, so this branch — the one place
"handling an absolute claim" actually requires new arithmetic — is unexercised.
**Fix:** guard on `hi == lo == 0` (true agreement at zero) separately from
`lo == 0, hi != 0` (should be `contradicted`, not `0.0` spread) — or floor `value`
away from exactly 0 in `validate.py` if 0 is never legitimate domain data, and say so.

## Risk others will miss: the persisted `claim.corr_status` / `corr_related_claim_ids` columns are now permanently, silently false — and that's a schema-fidelity problem, not just a scoping one

Migration `0003` carries `corr_status` and `corr_related_claim_ids` forward
(default `'uncorroborated'` / `'[]'`), every fixture claim is inserted with
`corroboration.status="uncorroborated"`, and — confirmed by pragmatist-shipper's
independent grep — nothing anywhere issues `UPDATE claim SET corr_status`.
`get_claims_for_analysis` (`db.py:259-266`) doesn't even `SELECT` the column back.
The resolution ratified this as "derive-on-read, no write-back," and I'm not
relitigating that design call. What I'm naming is the *consequence* nobody stated
plainly: for every claim in a `corroborated`, `weakly_corroborated`, or
`contradicted` group, the stored row's own `corroboration.status` field —
the schema's chosen home for this fact — reads `'uncorroborated'` forever, and
is indistinguishable at the row level from "never analyzed." A claim genuinely
corroborated by two other sources (`hotchips_n2:logic_speed`,
`tsmc_pr_n2:logic_speed`) sits in the `claim` table today reporting the *opposite*
of its true state, with no column, comment, or test anywhere flagging that the
column is decorative. CLAUDE.md names the module-level behavior ("derive-on-read,
read-only over `store`") but that's a design note for someone reading `analyze/`;
it's invisible to someone who runs `SELECT * FROM claim` directly, writes a report
query against `claim.corr_status`, or builds "the future write-back path" the
migration's own comment gestures at — they inherit a column that looks
authoritative and is uniformly wrong. One line in the migration itself (a
`-- NOTE: corr_status is NOT kept in sync by analyze v1; always uncorroborated
regardless of true state until a write-back path lands`) would cost nothing and
close exactly the kind of "trust the schema, not the code's promise" gap I exist
to catch.

## What I verified clean
- `CorroborationStatus` enum order/values: schema v3 ↔ `models.py` ↔ migration
  `0003` CHECK — all four values, same order, no drift.
- Migration `0003`'s column list is a faithful 21-column carry-forward of `0002`'s
  `claim` shape (verified positionally against `0001`/`0002`) — `INSERT INTO
  claim_v3 SELECT * FROM claim` is safe.
- The `weakly_corroborated` / suspect-exclusion arithmetic itself (not its test
  coverage) is correct on `sram_density`, `perf_per_watt`, `logic_speed`.
- `unresolved_baseline` (P2) correctly checks against `get_entities_index`'s live
  entity set, not a static/self-referential list — the dangling `intel_18a`
  baseline in `vendorslide` is caught for the right reason.
- The tolerance boundary (`spread > TOLERANCE_PCT`) compares the same rounded
  value it displays — no hidden fuzz between what's shown and what's decided;
  `test_tolerance_boundary` exercises exactly 10.0% vs 12% correctly.

## Bottom line
Ship after: (1) a group-key test that isolates `is_relative` from `baseline_entity`/
`unit`, (2) a `marketing_only`-suspect test added (not the branch deleted), (3) a
decision + test for the zero-value spread case. All three are test-only or
one-line fixes to an algorithm I've now verified is arithmetically sound — this is
not v1/v2's "the golden reproduces without any of the fixes" defect recurring, it's
narrower: three of the fixes are real but under-proven, and one runtime edge case
(zero-valued absolute claims) was never considered. Name the `corr_status`
staleness in the migration file itself; that one I'm flagging as a residual risk to
record, not a blocker, since the design call was already ratified.
