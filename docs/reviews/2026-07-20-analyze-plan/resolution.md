# Resolution — analytical MVP slice (plan)

Merge of the four opinions, written by the main session. The headline is not a
plan finding — it's that the **acceptance fixture (the DoD, written first) is
self-contradictory**, so the three plan reviews argued about the wrong target.

> Process note: reviewers ran as `general-purpose` with injected personas.

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | CONDITIONAL | Reconciling upsert is tier-blind/first-write-wins; `≥2 members` has no tier-diversity floor; `baseline_entity`/`process_node_ref` are unvalidated cross-doc FK refs — and the fixture relies on that bypass. |
| schema-purist | BLOCK | The anti-inflation rules ("same baseline required", "marketing can't corroborate") are prose, not tested algorithm; group-by omits `is_relative`; Decision A fails **silently**. |
| pragmatist-shipper | CONDITIONAL | Conflict-flag (F), write-back (C), and tier-weighted confidence (E) are unexercised by the golden — cut to minimal forms. |
| devils-advocate | (challenge) | **The oracle is wrong.** The golden's load-bearing `marketing_only` flag exists only because of an unresolved-baseline quirk in committed `validate.py`; every reviewer's fix either no-ops or reddens the golden. |

## Agreements (verified, kept)
- The workstream split (persist+reconcile / analyze / report) is sound.
- `source_tier` correctly joined from `document`, not duplicated onto `claim`.
- Write-back (if kept) correctly scoped to the schema's `corroboration.{status,related_claim_ids}`.
- Decisions B (flat ±10%) and D (`{doc_id}:{claim_id}` scoping) are appropriately minimal.

## The blocker: the DoD encodes a bug (devils-advocate, traced in code)
`extract/validate.py` sets `marketing_only` when a sparsity claim's baseline is a
**different vendor** — but it builds `vendor_of` from the *current document's*
entities only. `source_vendor.json` declares `tsmc_n2` but not its baseline
`tsmc_n3e`, so:
```
vendor_of["tsmc_n2"] = "TSMC";  vendor_of.get("tsmc_n3e") = None
"TSMC" != None  ->  True  ->  completeness = marketing_only
```
An N2-vs-N3E comparison is **same-vendor** and, by the schema's literal rule
("sparsity=true + **competitor** comparison"), should NOT be `marketing_only`.
The flag is an artifact of the ungrounded baseline. My `expected_analysis.json`
freezes it as "done." **Resolve baselines cross-document (mandatory for the store
workstream) → the flag disappears → the golden fails.** The security fix and the
acceptance test are mutually exclusive.

Two consequences:
1. **A latent bug in committed extraction code** — `validate.py`'s `marketing_only`
   rule treats an unresolved (`None`) baseline vendor as "different vendor" and
   mis-tags. This needs fixing regardless of the design question below.
2. **An unratified design question** the fixture silently answered (below).

## Named conflict (NOT averaged) — and why it's a symptom
pragmatist treats the golden as a **ceiling** ("if it can't see it, delete it");
schema-purist/injection-attacker treat it as a **floor** ("if it can't see it,
the golden is incomplete, add the guard"). These are opposite theories of what a
fixture *is* — un-averageable. But the advocate showed the tie-breaker (the golden)
**cannot arbitrate its own correctness**, because the oracle is broken. So this
conflict is downstream of the DoD problem, not resolvable before it.

## The prior decisions the human owes (before A–F)
- **P1 — Sparsity / `marketing_only` semantics.** Is a same-vendor N2-vs-N3E
  *sparsity* claim suspect, and how?
  - Sparsity-always-suspect: sparsity is "the classic 2x inflation lever" (schema)
    — flag it regardless of vendor. Requires changing `validate.py`'s rule.
  - marketing_only = strictly cross-vendor (schema-literal): the vendor claim is
    NOT `marketing_only`; `analyze` treats `sparsity=true` as its own independent
    suspect signal for divergence. Requires fixing the `None`-misfire + regenerating
    the fixture's flags. *(orchestrator lean: this — separate the two orthogonal
    signals; keep `marketing_only` schema-faithful, let sparsity flag independently.)*
- **P2 — Cross-document `baseline_entity` resolution.** Trust-the-string-and-flag
  `unresolved_baseline`, or resolve-and-reject a dangling baseline? Make it an
  explicit decision; regenerate the golden to whatever it produces (don't freeze
  the bypass output).

Everything the three reviewers raised (tier-aware reconciliation, alias gating,
tier-diversity floor for `corroborated`, `is_relative` in the group key,
attribute_citation propagation, confidence-vs-status collapse, exact-slug silent
failure) is **real and folds into the revised plan** — but only after the DoD is
ratified, so the revised golden tests the guards instead of the coincidences.

## Outcome
**BLOCKED on ratifying the DoD.** No build until P1 + P2 are decided, `validate.py`'s
`marketing_only` misfire is fixed, and `expected_analysis.json` is regenerated to a
target the system can produce honestly. Then either re-run GATE 1 on the corrected
plan/fixture, or fold the (already-surfaced) guards into a revised plan and go
straight to build → GATE 2.
