# pragmatist-shipper — GATE 2 (pre-commit) — analyze MVP slice

**Verdict: CONDITIONAL** — ship after deleting two unexercised branches (or adding
the one test that would justify each); everything else is appropriately minimal.

Ran the actual suite (`46 passed, 2 skipped`, matches manifest). Verified the
GATE-1-v2 cuts by grep + reading `db.py`/`persist.py`/`corroborate.py` directly,
not by trusting the docstrings.

## Cuts verified landed (no regressions, no snuck-back scope)
- **Tier-aware null-fill precedence (K):** gone. `reconcile_entity` (`src/semianalyst/store/db.py:219-248`)
  does plain `COALESCE(col, ?)` — tier-blind, first-non-null-wins, exactly as promised. No tier
  parameter reaches `persist_extraction` or `reconcile_entity` at all.
- **Slug tripwire (J):** gone. No slug/collision code anywhere in `store/` or `analyze/`.
- **Confidence cap:** gone. `_CONFIDENCE` (`corroborate.py:33-38`) is a flat 4-entry
  status→label dict, no clamping logic.
- **Write-back:** gone. `get_claims_for_analysis` only reads; nothing in `db.py` does
  `UPDATE claim SET corr_status`. `run_analysis` derives on every call, as documented.

All four Class-A cuts are real, not just relabeled. Good — this is what "ship the
minimal slice" is supposed to look like.

## Finding 1 (confirmed, delete-me) — `completeness == "marketing_only"` half of `_suspect()` is dead on this test suite
`corroborate.py:81` — `_suspect()` ORs `sparsity is True` with `completeness == "marketing_only"`.
No fixture, no unit test, ever sets `completeness="marketing_only"` reaching analyze (grep
confirms zero hits outside `validate.py`/`test_validate.py`, which is a different module).
I removed the marketing_only half of `_suspect` **and** the corresponding
`flags.append("marketing_only")` block (`corroborate.py:96-97`) and reran: **46 passed, 2
skipped, unchanged.**

- **Failure scenario this hides:** if a future document does carry a `marketing_only`
  claim, this branch is untested machinery — nobody knows if it actually does the right
  thing (e.g., does it correctly *exclude* that claim from the corroborated count the way
  sparsity does, or is there an off-by-one in `non_suspect` filtering?) until it fires in
  production, unreviewed.
- **Ship call:** either delete the OR clause now (it's schema-documented as a possible
  future value, not a currently-reachable one — `validate.py`'s marketing_only branch
  requires *both* vendors resolved, and this MVP's fixtures never do that, which is the
  exact same "dodges the fixture" pattern the resolution.md called out for validate.py),
  or add one `_cv(..., completeness="marketing_only")` unit case to `test_analyze.py` to
  earn it. Ten seconds either way — pick one, don't leave it unproven.

## Finding 2 (confirmed, delete-me) — the suspect-exclusion in `favored_tier` never changes the answer
`corroborate.py:114`: `favored_tier = min(c.source_tier for c in (non_suspect or members))`.
This is supposed to demonstrate "favor the non-suspect tier when picking which number to
trust." I changed it to `min(c.source_tier for c in members)` (drop the exclusion and the
all-suspect fallback entirely) and reran: **46 passed, 2 skipped, unchanged** — including
the acceptance golden's `perf_per_watt` case and both unit tests that assert `favored_tier`.

Reason: in every test case and in the golden fixture, the suspect (sparsity) member is
*always* the higher/worse tier number, so `min(all members)` and `min(non_suspect)` agree
by construction. This is the identical arithmetic trap the GATE-1-v2 resolution already
caught pragmatist making about `perf_per_watt`'s status — same shape of bug, now living in
`favored_tier`'s implementation instead of a review claim. The fix is cheap: one test where
the *lower*-tier-numbered member is the suspect one (e.g. a tier-1 doc with `sparsity=True`
disagreeing with a tier-2 clean number) would force the exclusion logic to actually do
something observable — right now it's speculative code with a false sense of coverage.

## Not a finding, but flagged for the record — the 13-column COALESCE reconciler is schema-necessary, not new surface
`_NODE_COLS`/`_CHIP_COLS` (`db.py:200-216`) touch all 5 node + 8 chip columns, but those
columns predate this workstream (they're in `0001_initial.sql`, not new). The acceptance
fixture never populates node/chip attributes, and only 2 of the 13 columns
(`node_transistor_type`, `node_backside_power`) get a fill-null assertion in
`test_reconciliation.py`. I'd normally call an untested 11/13 columns overbuild, but the
mechanism is a single generic COALESCE loop (not 13 bespoke branches) — one bug in the loop
shape would show up in the 2 tested columns too. Not worth blocking on. If this were
hand-written per-column instead of table-driven, I'd escalate it to a real finding.

## Risk others will miss: `reconcile_entity` does a bare `SELECT *` + string-built `UPDATE ... SET {', '.join(set_cols)}`
`db.py:225` and `db.py:453` (`f"UPDATE entity SET {', '.join(set_cols)} WHERE entity_id = ?"`).
Column names are hardcoded dict keys, not user input, so this isn't an injection risk *today*
— but it's the one place in this diff where SQL text is assembled by string join rather than
being a static literal, and CLAUDE.md's own invariant ("no value is ever interpolated into
SQL text") is about *values*, not column identifiers, so nothing here would be caught by
that stated boundary if a future refactor lets a column name become dynamic (e.g., a
generic "merge any entity column" helper). Values themselves are correctly parameterized
(`params` list, `?` placeholders) — I'm not claiming a live vulnerability, just noting this
is the one spot future edits could quietly turn into one, and it's exactly the kind of thing
a shipping-focused pass like mine would wave through because "it works and ships." Security
is not my lane on this review, but I'd rather name it than silently skip it.

## What I did not flag
- The `is_relative`/absolute-claim group-key handling, the `weakly_corroborated` status,
  and the dangling-baseline flag are all exercised by both a unit test and the golden —
  correctly scoped Class B fixes, not overbuild.
- `persist.py`'s `_scope()` claim-id prefixing is a 4-line pure function with direct test
  coverage (`test_claim_id_is_document_scoped`) — no complaint.
- Migration 0003's full-table-rebuild (drop FK, recreate, reindex) is more SQL than a
  single `ALTER TABLE` would be, but SQLite genuinely can't alter a CHECK/FK in place, so
  this isn't gold-plating — it's the floor for what SQLite requires.

## Bottom line
Ship this after resolving the two dead branches (delete or earn with a test — see Findings
1 and 2 above; both are ~10-minute fixes and I already proved via a rerun that deleting
either keeps the suite green). Everything else in this diff matches the resolution's
"minimal slice" mandate better than most MVP diffs I see — the Class A deferrals are real
deferrals, not renamed features.
