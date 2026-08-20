# pragmatist-shipper — WS-2a precommit review (2026-08-18)

Target: `docs/reviews/2026-08-18-live-ingest-precommit/workstream.diff`
(`5a8af2c..d6adb94`, branch `feat/ws2a-trust`), against the contract in
`docs/reviews/2026-08-18-live-ingest-plan/resolution.md`.

## Verdict: conditional

Almost none of this diff is speculative — the artifact/refold machinery, the
conflict table, the bounds, H1/G1/G3/S1/S2 all trace directly to a named,
human-adjudicated line in the resolution, and I could not find a feature here
that the resolution didn't ask for. My blocking-ish complaint is narrower and
sharper: the implementation solved "sanitize/normalize untrusted text" five
separate times instead of once, and the test suite re-proves the same pydantic
guarantee twice. Neither breaks the golden harness or `db init`, so this is
conditional-not-block: ship it, but don't let the duplication become six sites
next time a bound changes.

## Finding 1 — five independent control-byte/format-char sanitizers, no shared home

This is the exact question the orchestrator asked to check, and the answer is
yes, it fragmented:

- `src/semianalyst/store/models.py:34` — `_NO_CTRL = r"^[^\x00-\x1f\x7f]*$"` (pydantic pattern)
- `src/semianalyst/store/db.py:317` — `_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")` (used by `_conflict_repr`)
- `src/semianalyst/extract/pipeline.py:45` — `_ERR_CTRL = re.compile(r"[\x00-\x1f\x7f]")` (used by `_err_repr`)
- `src/semianalyst/extract/validate.py:108` — `_CTRL = re.compile(r"[\x00-\x1f\x7f]")` (used by `_safe`)
- `src/semianalyst/cli.py:45` — `_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")` (used by `_ansi_safe`, plus the new Unicode-Cf pass)

Four of these five are *byte-for-byte the same regex* (`[\x00-\x1f\x7f]`),
defined independently in four modules that don't import from each other. This
is not a security gap (each site is arguably right to be self-contained given
"store is the sole SQLite owner" / "extract owns validation" module boundaries),
but it is exactly the kind of "hand-written Python re-checking the same thing"
the DoD doesn't require duplicated five times. A single `_scrub_ctrl(text)`
helper — even just a one-line shared utility each module imports — would cut
four definitions to one and remove the risk of the *next* editor changing one
copy's byte range (cli.py's is already subtly different: `\x7f-\x9f`, not just
`\x7f`) without updating the other three. `store/db.py`'s own docstring at
`_conflict_repr` (db.py:311-316) already argues this exact scrub is
load-bearing precisely because it must match `Text120`'s pattern — an argument
*for* one shared definition, not four independent ones that can drift.

Layered on top: casing-normalization now has **three different idioms** for
the same "fold a hostile string for comparison" job —
`corroborate.py:_norm_key` (whitespace-collapse + strip + casefold),
`store/db.py`'s inline `.casefold()` calls in `reconcile_entity`/
`_foreign_surface_forms` (casefold only, no whitespace collapse — an identity
value with stray whitespace variance would NOT be recognized as the same
field, unlike a metric string), and `extract/validate.py:_grounded_ci`, which
uses `.lower()` (not `.casefold()`) for name/vendor/alias presence-grounding.
None of this is a correctness bug I can point to on today's fixtures, but it's
three near-identical helpers where the resolution's own G1/G3/H1 language
treats "casing/spacing variant is one value" as a single principle — the code
should have one function enforcing it, not three.

**Ask:** before/soon after merge, pull the control-byte scrub into one
function (`store/text_safety.py` or similar) that `models.py`'s pattern,
`db.py`, `pipeline.py`, and `cli.py` all reference, and pick one
normalization idiom (`casefold` + whitespace-collapse) for every
attacker-influenceable comparison, including the identity-field compare in
`reconcile_entity` which currently doesn't collapse whitespace.

## Finding 2 — test_validate.py re-proves what test_hostile.py's `test_field_flood` already proved

`tests/test_hostile.py::test_field_flood` (diff line ~2712) already exercises,
in one test, an oversize metric, a >16-item alias list, a control-character
vendor, and an oversize claim_id — all through `validate_proposal`, plus the
DDL CHECK backstop via a raw sqlite3 INSERT. `tests/test_validate.py` then
adds four *more*, separate, single-purpose tests
(`test_oversize_metric_drops_claim_not_extraction`,
`test_oversize_alias_drops_entity_not_extraction`,
`test_control_character_vendor_drops_entity_not_extraction`,
`test_alias_flood_over_16_drops_entity_not_extraction`) that assert the exact
same fail-soft-per-item behavior at the exact same layer (pydantic
`StringConstraints`/`Field(max_length=...)` raising, caught, and turned into a
`Rejection`). This isn't testing a new code path — it's testing that pydantic
enforces the type annotation it was just given, four times, in a second file.
Not harmful, but it's exactly the "hand-written validation logic duplicating
what the pydantic model already guarantees" pattern from my brief, just
relocated into the *test* layer instead of the implementation layer. I'd cut
these four and keep `test_field_flood`'s combined coverage plus one dedicated
test if a specific bound has non-obvious behavior worth pinning.

## Finding 3 (minor, named per instructions) — `StoreNotInitialized` is scope creep, small and welcome

`store/db.py`'s `StoreNotInitialized`/`_translate_missing_schema`, wired
through `cli.py`'s `extract()`/`report()` (catch → friendly stderr message
instead of a raw `sqlite3.OperationalError` traceback), is not mandated by
any line in the resolution — it's an operator-ergonomics fix unrelated to
trust hardening. I'm naming it because the brief asked what's *not* mandated,
not because it should be cut: it's ~15 lines, makes `db init`'s error path
actually usable, and doesn't interact with the trust surface. Keep it; just
don't let "found a nearby rough edge, fixed it" become the norm for a gate
diff without a note in the PR description (this one has none pointing at it).

## What earns its keep (no complaint)

The artifact + refold architecture (three report dataclasses
`ExtractReport`/`RebuildReport`/`ForgetReport`, the anti-ping-pong
`extraction_artifact_path(...).exists()` check, `_quarantine_dest`'s numbered
siblings) is not gold-plating — it's the resolution's single largest adopted
item (Challenge 1), each dataclass maps to a genuinely distinct CLI command
with distinct fields, and the "never clobber a quarantined file" numbering is
one `while` loop mirroring the never-overwrite principle already established
for entity reconciliation, not a new abstraction. The dual pydantic+DDL bound
layer (Conflict 2) and the persisted conflict table (Conflict 1) were fought
over and explicitly decided by the human at the plan gate — re-litigating
"log-only would have been simpler" here would be re-opening a closed
conflict, not reviewing the diff. The hostile suite's in-test `_mini_pdf`
builder is not duplicate fixture machinery — I grepped the repo and no other
PDF-generation helper exists to duplicate; it's genuinely new, self-contained,
and its docstring gives the right reason (no binary fixture drift for
one-off attacks).

## DoD check

I walked the resolution's "Outcome" list against the diff and the current
working tree:
- Standalone pre-WS-2a fix (sparsity vocab grounding + vendor case-fold) is
  **not in this diff** — confirmed already present in `extract/validate.py`
  (`_SPARSE_VOCAB_V1`, vendor-casefold dedup) and only touched by this diff
  via test source-text tweaks (new name/vendor presence-grounding needs the
  vendor name literally in the fixture text). Matches ROADMAP's claim that
  step 1 shipped separately.
- Artifact + refold, `forget`, `db rebuild`, supersession, anti-ping-pong:
  built, tested (`tests/test_rebuild.py`).
- Conflict table + bounds (migration 0004, schema v4 `bounds` block, `Text*`
  pydantic types): built, DDL CHECKs mirror pydantic lengths as decided.
- H1 (normalized publisher floor), G1/G3, S1/S2, §2.8 Cf-stripping, J
  advisory: built, each with a named hostile-suite test.
- Honest-corpus regression + flag budget: `test_honest_corpus_regression` +
  `test_flag_budget` both present and the budget is verified at **zero** new
  flags on the honest fixture, matching the CLAUDE.md claim.
- H2/B1/controlled-vocabulary/identity-citation-slots deferrals: all present
  in `docs/ROADMAP.md` with the exact triggers named in the resolution.

CLAUDE.md's rewritten Class-A section matches the shipped behavior on every
claim I spot-checked (K/G/H/S/bounds/report-display/I/J). I did not find a
documentation claim unsupported by code.

## One risk others will miss (my angle)

**The duplicated control-byte regexes are a maintenance trap for the NEXT
bound change, not a bug today.** If a future workstream widens a bound (say,
`Text120` → `Text200` for `offered_value`) or changes what counts as a
control byte, there are five places to update and no test that fails if one
is missed — each site's own local tests only check that site. A
schema-purist or injection-attacker would call this a security risk; from my
seat it's a shipping-velocity risk: the fix that "worked in code review" will
quietly stop matching in one of the other four call sites, and nobody will
notice until a hostile string reaches a display path through the one spot
that didn't get updated. Cheap to close now (one shared function); expensive
to close after a second gate adds a sixth site.
