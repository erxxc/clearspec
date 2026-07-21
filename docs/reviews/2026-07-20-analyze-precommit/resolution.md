# Resolution — GATE 2 (pre-commit), analyze MVP slice

**Orchestrator:** main session. **Reviewers:** injection-attacker, schema-purist,
pragmatist-shipper (all CONDITIONAL), devils-advocate (attacks the consensus).
**Base:** extraction commit `4c8c1b6` → working tree. **Suite after fixes:** `uv run
pytest` → **49 passed, 2 skipped** (the 2 live-extraction tests; +3 net tests vs the
46 at gate open).

No reviewer returned BLOCK. The devils-advocate escalated two findings to
BLOCK-*severity on honest data* and re-classified a third. I treated the advocate's
escalations as the sharper reading and acted on them. Below: what I fixed and
proved this gate, the one named conflict and how it split, and the two decisions I
am **not** taking unilaterally and am handing to you.

---

## 1. Fixed and tested this gate (applied)

| # | Finding (source) | Fix | Proof |
|---|---|---|---|
| F3 / §2 | **Zero-value → false "corroborated/high".** `spread = (hi-lo)/lo*100 if lo else 0.0` reported spread `0.0` for any group whose min was `0.0` — a `[0.0, 40.0]` group of two honest, non-suspect numbers asserted high-confidence agreement. (schema-purist F3; advocate §2, rated BLOCK-severity) | Denominator is now `max(abs(lo),abs(hi))`, not `lo`. `[0.0,40.0]` → 100% spread → **contradicted**; `[0.0,0.0]` → 0% → corroborated (genuine agreement at zero). Finite for any non-`[0,0]` group. Model-agnostic: correct under *either* tolerance model (see decision A). | `test_zero_valued_group_is_not_false_corroborated`. Golden `spread_pct` displays shift (relative to larger endpoint now): logic_speed 2.6→**2.5**, perf_per_watt 38.5→**27.8**, sram_density 4.2→**4.0**. **No status or `favored_tier` changed.** |
| F1 / §1 | **`is_relative` group-key test couldn't detect the fix's absence** — the two claims differed in `baseline` *and* `unit`, so the key separated them with or without `is_relative`. | Rewrote to two claims identical in (entity, metric, baseline, unit) and value, differing **only** in `is_relative`. Without `is_relative` in the key → 1 corroborated group; with it → 2 uncorroborated singletons. | `test_is_relative_is_load_bearing_in_group_key`. Delete `is_relative` from the key → this test now fails (it didn't before). |
| F2 / §3 | **`marketing_only` arm of `_suspect()` was dead** — no fixture/test ever set it. Schema invariant, must be *covered*, not cut (advocate §3 + purist F2 agree; see conflict §2). | Branch **kept**; added a unit test through the `marketing_only` door. | `test_clean_plus_marketing_only_agree_is_weakly_corroborated`. |
| §3 | **`favored_tier`'s suspect-exclusion was smuggled Class-A tier-precedence.** `min(... for c in (non_suspect or members))` let a sparsity flag demote a tier — the exact flavor of deferred question K, cleared by the injection audit only because on the golden the suspect is always the higher tier. (advocate §3, re-classified) | **Dropped the exclusion.** `favored_tier = min(tier over ALL members)` — tier-blind, matching the deliberately tier-blind reconciler beside it. Whether sparsity *should* override tier is now named under K in CLAUDE.md, unbuilt. | `test_favored_tier_is_tier_blind_sparsity_does_not_override_tier` (tier-1 suspect + tier-3 clean → favored **1**; the excluding variant would have returned 3). |

**Named-deferred (Class A), added to CLAUDE.md's list — not built, by design:**
- **Identity-field conflict** (injection F2) — `reconcile_entity` freezes
  `vendor`/`name`/`entity_type` from the first doc and silently drops later
  disagreements. Was invisible-by-omission; now explicitly listed.
- **Baseline content-bound** (injection F1) — the 0003 FK drop also removed the
  *shape* guard; `cmp_baseline_entity` is now unconstrained TEXT. Listed.
- **Report display safety** (injection risk) — `cli.py:report()` echoes DB strings
  with no output encoding; inert on curated fixtures, an ANSI/OSC vector the day
  extraction goes live. Listed with a "sanitize before live" instruction.
- **`corr_status` staleness** (schema-purist residual risk) — NOTE added in
  migration 0003 *and* CLAUDE.md: the column is derive-on-read, always
  `uncorroborated`, never `SELECT` it. (The deeper modeling question is decision B.)

I did **not** build the display sanitizer or the baseline length-CHECK this gate.
Rationale: every one is a guard that is a no-op on honest data by construction —
the Class-A test. Building one opportunistically breaks the clean, uniform deferral
the injection audit explicitly praised. They are named loudly instead, so the
live-ingest workstream must address them as a set.

---

## 2. The one named conflict (stated, not averaged)

**schema-purist "keep + prove" vs pragmatist-shipper "delete-or-earn"** on the two
unexercised branches. The advocate's key contribution (§3): these are **not the
same animal**, and averaging both to "add a test" is the shared error. They split:

- **`marketing_only` in `_suspect()`** — **purist wins outright.** It encodes a
  schema invariant (`marketing_only` = "too suspect to independently corroborate a
  clean number"). Deleting it reopens, through a new door, the exact hole GATE-1-v2
  closed for `sparsity`. Cost of pragmatist's delete: a suspect number silently
  corroborates a clean one the day live extraction sets the flag — invisible on the
  golden. Cost of keep: one unit test. → **Kept + tested.**
- **`favored_tier`'s exclusion** — **neither framing is right.** Not a schema
  invariant (purist over-generalizes) and not harmless dead code (pragmatist's
  "delete freely" is dangerous) — it is a *live, deferred tier-precedence decision*
  (K). The green suite was *concealing* a decision the gate was told to defer. →
  **Shipped tier-blind `min(all)`** (the consistent MVP move, matching the
  reconciler), decision **named** under K. Not silently kept, not silently deleted.

---

## 3. Two decisions handed to the human — ADJUDICATED (advocate §2, §4)

The human's calls (2026-07-20): **A1** (ship relative-only, name the gap) and **B2**
(make the schema honest — drop the persisted per-row verdict). Both were the
recommendation. What shipped for each:

- **A1 — applied.** The zero-div fix (§1, table row F3) already made the single
  relative ruler *safe*. `TOLERANCE_PCT` stays a flat relative ±10% for all claim
  types; the absolute-tolerance question is *named* (CLAUDE.md + a code comment in
  `_assess`) as revisit-when-a-second-absolute-claim-groups. No absolute-mode
  config built — we do not design for input we don't yet have.
- **B2 — applied, surgically.** The defect the advocate named was a *persisted
  per-row column* that was uniformly wrong and pre-advertised write-back. I removed
  exactly that: migration 0003 (which already recreates the `claim` table for the FK
  drop, and is **uncommitted** — the append-only rule protects *released*
  migrations, and no real data exists) now also **drops `corr_status` /
  `corr_related_claim_ids`**; `insert_claim` no longer writes them; the final `claim`
  table is 19 columns, verified by `PRAGMA table_info`. The `Corroboration` model
  field is **kept** (neutral default) so extraction output keeps a stable shape and
  the committed extraction golden (`model_dump == expected.json`) is untouched — but
  the schema (`extraction_schema_v3.yaml`) and the model now mark it **derived, not
  persisted**, and nothing writes or reads it back. This threads B2's intent (schema
  states analyze owns no per-row verdict) without a v3-adds-then-v4-removes churn or
  editing the extraction commit's fixtures. Full removal from the model was rejected
  as scope creep into the committed extraction workstream (it would force edits to
  `expected.json`, `llm_response.json`, the prompt, and the test helpers for zero
  additional honesty — the persisted column, the actual defect, is already gone).
  Suite after B2: **49 passed, 2 skipped**.

### (historical) The two decisions as originally surfaced

The advocate's central point survives the fixes: the consensus treated an
*uncharacterized* honest domain (one 3-doc snapshot) as a *covered* one. Two
questions are real design forks, not mechanical fixes. I fixed the acute symptom of
each so nothing ships broken, but the modeling call is yours.

### A. Does an absolute claim get an *absolute* tolerance?
`spread_pct` is a **relative** dispersion measure and `TOLERANCE_PCT = 10.0` is a
**relative** threshold — yet `_assess` applies that one ruler to both ratios
(1.15x) and absolute claims (65% yield, 3.5 GHz). "Within 10%" of a ratio and
"within 10%" of a 65% yield (≈6.5 points) are different claims about the world. The
`is_relative` group key keeps the two *separated*; `_assess` then re-flattens them
onto one relative scale. **Today this is moot** — the only absolute claim in the
golden is `yield_rate` (a *singleton*, short-circuits before any spread math). The
zero-div fix makes the relative ruler *safe*, not *right for absolutes*. The moment
two absolute claims share a group, this fires untested.
- **Option A1 (ship as-is):** one relative tolerance for all; revisit when a
  second absolute claim actually lands. Cheapest; leaves a latent modeling gap.
- **Option A2 (absolute mode now):** per-metric or per-`is_relative` tolerance (an
  absolute-points band for absolutes). Correct, but designs for input we don't yet
  have and adds a config surface.

### B. Does analyze own a persisted per-row verdict at all?
Migration 0003 pays for a full table rebuild partly to carry `corr_status` forward
"for a future write-back path," then writes `'uncorroborated'` to every row while
the truth is derived elsewhere and discarded. The advocate's sharper reading: this
is a **schema modeling error**, not a stale column — (i) a per-*group* verdict has
no honest per-*row* home, and (ii) `'uncorroborated'` is overloaded across two
opposite states ("not yet computed" vs the real verdict "definitively
single-source"). A NOTE (what I added) *documents* the tension but, taken as
"write-back is the intended end-state," would create two disagreeing truths the
moment a new source arrives between write-back and read — the one event this
subsystem exists to handle.
- **Option B1 (NOTE only — current):** keep the column, derive-on-read is
  authoritative, NOTE warns readers off it. Zero migration churn. Column stays a
  decorative, uniformly-wrong field.
- **Option B2 (make it honest):** drop `corr_status`/`corr_related_claim_ids` from
  v3 (or make them NULLable, default NULL = "not computed") so the schema states
  plainly that analyze owns no persisted per-row verdict. A v4 migration. Removes
  the "half-built write-back" shape the advocate flags.
- **Option B3 (commit to write-back):** design a per-group verdict table (verdict
  is a property of a group, not a claim) and populate it. Largest; out of MVP scope.

My recommendation: **A1 + B2.** A1 keeps scope honest (don't design for absent
input) now that the false-positive is dead; B2 removes a genuinely misleading
schema shape cheaply and is the honest expression of "analyze is derive-on-read."
But both are yours to call — flagging, not deciding.

---

## 4. Verified clean (no action)
- Class-A cuts are real deferrals, not renamed features (pragmatist: K/G/H/J/write-back
  all confirmed absent by grep + read; injection: no smuggled tier-precedence/
  alias-gating/conflict-storage).
- All SQL values parameterized (`?`); the only string-built SQL is column *identifiers*
  from static dict keys (pragmatist risk-note: not a vuln today; watch if a future
  refactor lets a column name become dynamic).
- Enum ↔ model ↔ migration CHECK in lockstep (schema-purist); `unresolved_baseline`
  checks the live entity set; migration 0003 is a faithful 21-column carry-forward.

---

## Recommendation → status
Fixes 1–4 applied and green. Class-A items named. Decisions **A1 + B2 adjudicated and
applied** (§3). Suite: **49 passed, 2 skipped**. Ready to commit the analyze
workstream — code + fixtures + all three analyze gate run dirs — as a single commit
separate from the extraction commit (`4c8c1b6`).
