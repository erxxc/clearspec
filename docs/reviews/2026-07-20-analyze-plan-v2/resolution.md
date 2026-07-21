# Resolution — analytical MVP slice (plan, v2 / re-gate)

Merge of the four opinions, written by the main session. The re-gate's headline
is a **reframe**: one acceptance golden was being asked to be both a value
demonstration (honest data) and an adversarial guard-oracle (hostile data), and
it cannot be both. That conflation — not the plan, not the golden — is the defect.

> Process note: reviewers ran as `general-purpose` with injected personas. This is
> the SECOND gate on this slice; the first found the DoD encoded a `validate.py`
> misfire (now fixed). Two gates, and no third is warranted — the picture is settled.

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | CONDITIONAL | v2 guards close only the non-adversarial half; poisoning a REAL resolved entity via `baseline_entity` is still unguarded and unnamed. |
| schema-purist | BLOCK | A naive implementation reproduces the golden **byte-for-byte** — no v2 fix is load-bearing; and the suspect-exclusion rule creates a group state the 3-value enum can't express. |
| pragmatist-shipper | CONDITIONAL | tier-aware null-fill / tripwire / confidence-cap are dead against the fixture; the plan proposing to *manufacture* fixtures to justify them is the test-justifies-code inversion. |
| devils-advocate | (challenge) | **The defect is the conflation.** Split honest-domain correctness (fix now) from hostile-domain guards (name seams, defer). schema-purist wins the perf_per_watt arithmetic — don't average. |

## The reframe (accepted) — two domains, opposite dispositions
A correctly-built guard is a **no-op on honest data** by construction — so a
value-demonstration golden built from honest curated sources *should* be
naive-reproducible for adversarial guards. schema-purist's byte-for-byte finding
is factually airtight but proves the honest golden behaves honestly, not that the
plan is broken. The findings split cleanly:

### Class A — HOSTILE-INPUT guards → NAME the seam, DEFER the code + its fixtures
These require a hostile document reaching the reconciler. **There is no such
pathway in this MVP** (ingest WIP, extract stub, curated post-extraction fixtures;
CLAUDE.md forbids wiring `run_extract → insert_*`). Design the reconciler not to
paint into a corner, but defer enforcement + adversarial fixtures to the
live-ingest workstream, gated on a *named adversarial suite there* — never this
golden. Cut from the MVP now:
- **K (new):** does tier ever override a non-null value, or only race a null one?
  (injection F1 — the sequential per-doc API can't beat a hostile-first write.)
- **G:** alias-union gating (ungated/tier-restricted/citation-required).
- **H:** a **status-level** tier-diversity floor for `corroborated` (not a
  `confidence` adjective — flooding still reaches the persisted `status` otherwise).
- **Resolved-baseline poisoning** (injection Risk, previously unnamed): a hostile
  doc setting `baseline_entity` to a real competitor's *already-resolved* entity_id.
  P2 only covered the *dangling* half. Give it a letter and the honest MVP answer
  ("trust cross-doc baseline strings, no provenance") — *named*, like P2.
- **I:** persisted conflict-tracking. **J:** slug-collision tripwire strength.
- **Cut now:** tier-aware null-fill precedence, the tripwire code, the confidence
  cap. Ship reconciliation as **alias-union + fill-null / never-overwrite-non-null**
  (one `if`, no tier state) and confidence as a status→label lookup.

### Class B — HONEST-INPUT correctness → DECIDE + FIX NOW (bites honest data today)
Not guards against anyone; they bite the honest corpus this MVP runs on:
- **The clean+sparsity-agree enum gap (the killer).** The most common real
  pattern — a foundry's clean number + a vendor deck that *honestly discloses*
  sparsity, agreeing within tolerance — has **no representable status**: not
  `corroborated` (1 non-suspect), not `contradicted` (within tolerance), not
  `uncorroborated`/singleton (2 members). `CorroborationStatus` is a 3-value enum.
  This is a **total-function hole over the honest domain** and a semantics decision
  the human owes (see below).
- **No absolute claim / no unstated baseline** in the fixture — the group-key
  `is_relative` fix has no honest case to demonstrate on. Honest data contains
  absolute claims (e.g. a 65% yield). Enrich the golden with these — honest
  patterns the algorithm claims to handle, **not** manufactured branches.

## Named conflict (NOT averaged) — decided by arithmetic
pragmatist claimed the golden "goes red without" the `is_relative`+suspect-exclusion
rules on `perf_per_watt`. **False, checkable:** spread = (1.8−1.3)/1.3 = **38.5%**,
outside ±10% → `contradicted` from spread alone, zero knowledge of sparsity; and
`favored_tier` = min tier = 2 whether or not the suspect (tier-3) member is
excluded. schema-purist's byte-for-byte finding stands unrebutted.

## Through-line worth recording
`marketing_only` — the flag both gates were about — appears **nowhere** in the v2
fixture: P1 correctly requires both vendors resolved, and `vendorslide` never
declares `tsmc_n3e`, so the branch fires nowhere. The contested guard dodged the
fixture both times (v1 encoded it as a bug; v2 regenerated it out of existence).
Lesson baked into the split: adversarial behavior is not testable on the honest golden.

## The one decision the human owes (before build)
**The enum gap** — what status is a clean+sparsity-agree group?
- **(a) Widen `uncorroborated`** to "fewer than 2 **non-suspect** members regardless
  of raw group size" → clean+sparsity-agree = `uncorroborated` + `sparsity` flag.
  No schema change; schema-faithful (a clean number is NOT corroborated by a sparsity
  number). *(orchestrator recommendation.)*
- **(b) A 4th status** (schema v3, new enum value, migration) — richer but heavier.
- **(c) Let it corroborate, flagged** — the "laundering" schema-purist warns against.

## Outcome
**Proceed to build the MINIMAL slice**, once the enum decision is made:
- Class B fixed; honest golden enriched with an absolute claim + a clean+sparsity-agree
  pair (both must be tested).
- Class A seams named as deferred decisions (K/G/H/I/J + resolved-baseline) in the
  plan/CLAUDE.md; **no enforcement code, no adversarial fixtures** this iteration.
- Reconciliation + confidence scoped to their minimal forms.
No third plan gate — straight to build → GATE 2 (pre-commit) → sign-off → commit.
