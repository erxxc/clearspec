# pragmatist-shipper — WS-2 live-ingest plan gate (2026-08-18)

**Verdict: CONDITIONAL**

Grounded in `src/semianalyst/store/{models.py,db.py,migrations/0001_initial.sql}`,
`src/semianalyst/extract/validate.py`, `src/semianalyst/analyze/corroborate.py`,
`src/semianalyst/ingest/{base.py,pipeline.py}`, `src/semianalyst/cli.py`, and
`tests/test_reconciliation.py`.

## Summary

The DoD for WS-2 is: fetch a document from a URL, survive the named hostile
cases, and keep `db init` / the golden harness green. Most of the plan earns its
keep against that bar — but §2.5 (persisted conflict table + schema v4 +
migration 0004) and the double floor in §2.3 (H1 *and* H2) are more machinery
than the stated DoD requires, and the plan's own §5 flags exactly these as
contested. I'd ship a trimmed version of this design, not the whole thing.

## What's right-sized (not attacking these)

- **Scope cut (direct-URL, discovery to WS-3).** This is the correct depth of
  cut. It removes the part of "live ingest" that's pure engineering risk
  (HTML scraping fragility) with zero trust-model payoff, while keeping every
  Class A decision forced (fetching *any* URL is enough to exercise K/G/H/B/S).
  Don't second-guess this one.
- **G1 (alias grounding) and B2/§2.7's `cmp_baseline_entity` bound** are cheap:
  G1 reuses the exact `is_grounded` check `validate.py` already runs for claims
  and attribute citations (`extract/validate.py:190`, `:252`) — it's applying
  existing infrastructure to one more field, not new abstraction. Keep it.
- **S1/S2** are ~20 lines each (a doc_id-mismatch guard in `write_sidecar`, a
  sha256 recompute in `read_raw_docs`) with a named, already-real bug
  (last-write-wins sidecar clobber, unverified hash) behind them. Cheap, keep.

## Findings

**1. §2.5 (schema v4 + migration 0004 + persisted `Conflict` model) is the
single biggest deliverable in the plan and it's disproportionate to what
actually reaches the store.** WS-2b's own scope cut means the "hostile" input
is bounded to whatever URL the *operator* put in `config.toml` — the same
curated-source trust profile `ingest_file` already has today, which the plan
itself says produced "zero Class A exposure" (ROADMAP.md WS-1 row). A
queryable SQL table for conflict records means: a new schema file, model
regen, a migration, `reconcile_entity` write-path changes, new `ClaimView`-
style read queries, and `report` surfacing — for a fact that `validate.py`
already has a working, cheaper pattern for (`Rejection`: kind + sanitized
target + reason, logged via `logger.warning`, asserted on in tests without a
table — see `extract/validate.py:64-68,293-298`). The plan's own §5 admits
this is contested ("derive-on-read precedent argues log-only... settle which
principle governs") and offers the counter-argument that "the offered value
has no other home" — but a structured log line (or a JSON sidecar next to the
entity, if queryability is wanted without a migration) *is* a home. I'd cut
this to log-only for the MVP and revisit the table if an operator actually
needs to query conflict history across runs — that's a real trigger, "we might
want to query it later" is not.

**2. §2.3 ships H1 *and* H2 — two new orthogonal axes (publisher-diversity
floor, tier-diversity confidence cap) on a corroboration engine that has never
seen a live-fetched document.** `analyze/corroborate.py` is 160 lines total
today; this adds a new join column (`publisher` on `ClaimView`), two new flags
(`single_publisher`, `vendor_only`), and new demotion/cap logic — before a
single real watchlist has produced a `corroborated` verdict from fetched data.
Both floors solve a real problem in the abstract (shell publishers, tier-3
flooding), but neither is *forced* by fetching one URL the way K/G/S are — a
watchlist needs ≥2-3 same-tier sources configured before either code path is
even exercised on real data. Ship H1 (publisher is the cheaper, more legible
axis — it's one join column) and defer H2 with a named trigger ("revisit when
the watchlist has ≥2 tier-3 sources for one metric"), per the CLAUDE.md pattern
already used for Analyze decision A. Landing both now is speculative generality
against a threat that direct-URL/single-watchlist WS-2b can't yet produce.

**3. §2.7 content bounds are written as "every model- or network-influenced
string" — that's the tell of a rule reaching for maximum coverage rather than
the fields WS-2b's actual scope forces.** `doc_id` and `url` genuinely change
character with a network fetcher (§1's slug scheme, final-redirect-URL
recording) — bound those. But `metric`, `name`, `vendor`, `aliases`,
`quote_span` are **already** model-output fields today, going through
`ingest_file` → `run_extract` → `validate.py` right now, with zero bounds, and
the plan doesn't argue WS-2b changes their risk profile (the model-facing
injection surface is explicitly out of scope here — "already covered by
`test_injection_*`," per §0). If they need bounds, that's a `test_injection_*`
gap to fix independent of whether a URL fetcher exists, not a WS-2 line item.
Bundling it into WS-2 makes the migration/model-regen diff bigger than the
fetcher itself and muddies why it shipped when it did.

## One risk others will miss (delivery angle)

**Scope-inflation risk to WS-2b itself.** WS-2a as scoped (schema v4, a new
table, two new analyze axes, bounds across every string field, an 11-case
named suite, plus `tests/test_fetch.py`) is easily the largest single slice
since the project started (bigger than WS-1, which merged after real gate
churn). The injection-attacker and schema-purist reviewers will each want more
of this, not less — nobody on this gate is incentivized to say "ship less."
The actual product capability this workstream exists to deliver — a *fetcher
that fetches* — is one bullet in §1 and is entirely gated behind WS-2a landing
first ("no hostile byte should be fetchable before the store can survive it").
If WS-2a scope grows further at review, WS-2b (the thing that makes the tool
live instead of a demo) keeps slipping. I'd put a hard line under §2.5 and
§2.3-H2 specifically because they're the two items that don't gate WS-2b's
safety (S1/S2/G1/K1/K2/H1/2.8 do — they're in the direct causal path of "a
hostile byte reaches the store"; a *persisted* conflict table and a *second*
confidence-cap axis are not).

## Answers to the orchestrator's specific questions

- **WS-2a/WS-2b split: real or ceremony?** Real, but only barely — everything
  in WS-2a is reachable through `ingest_file` + `run_extract` today (no network
  needed to construct a hostile `Entity`/`Claim` and run it through
  `validate → persist_extraction → analyze → report`), so the split is a
  genuine risk-reduction sequencing, not cosmetic. My objection isn't to the
  split, it's to what got loaded into the WS-2a side of it (findings 1-2).
- **Hostile suite duplication:** mostly not duplicative. `null_race` is the
  one case that substantially overlaps existing coverage —
  `tests/test_reconciliation.py::test_fill_null_never_overwrites_non_null`
  already proves first-non-null-wins; the new case only adds the "conflict
  recorded" assertion, which only exists because of finding #1's table. Cut
  the table and `null_race` collapses to an assertion added to the existing
  test. The other ten cases exercise genuinely new code (bounds, Cf-stripping,
  alias grounding/collision, floors, S1/S2) and are not redundant.
- **Schema v4 + migration 0004 justified?** Only for the bounds (§2.7, trimmed
  per finding #3) and the `Conflict` model *if* the human overrules finding #1
  and wants it persisted. On its own, conflict-logging does not need a
  migration.
