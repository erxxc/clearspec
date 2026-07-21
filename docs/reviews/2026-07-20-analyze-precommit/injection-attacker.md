# injection-attacker — GATE 2 (pre-commit) opinion

**Workstream:** analyze v1 + store.persist_extraction / reconcile_entity (schema v3)
**Scope of this review:** implementation only. The Class-A deferral (K/G/H/I/J +
resolved-baseline poisoning) was ratified at GATE-1 v2 and is NOT re-litigated here —
I looked for (a) whether the deferral was executed cleanly (no half-built guard, no
enforcement code smuggled in) and (b) whether the implementation *itself* opened any
NEW hostile surface beyond what was scoped.

## Verdict: CONDITIONAL

The deferral was executed cleanly — I found no smuggled tier-precedence, alias-gating,
or conflict-storage code, and CLAUDE.md's new section honestly enumerates every cut
guard. But migration 0003's FK drop does more than the plan asked for, and that "more"
is a real, currently-latent hostile surface. One cheap constraint closes it; it
shouldn't block indefinitely, but it shouldn't land silently either.

## Findings (my angle only)

### 1. Dropping the `cmp_baseline_entity` FK removed a *content* guard, not just an *existence* guard — integrity regression beyond the stated intent
`src/semianalyst/store/migrations/0003_weakly_corroborated.sql`, `cmp_baseline_entity TEXT` (line 24)

The stated and ratified intent (P2) was narrow: a baseline may be cross-document or
not-yet-ingested, so it must not be required to *already exist*. But the FK
(`REFERENCES entity(entity_id)`) was doing two jobs at once, and the migration killed
both: it also constrained the *shape* of the value to "a string that is (or will
validly be) an entity_id" by rejecting the INSERT outright on anything else. Post-0003,
`cmp_baseline_entity` is a completely unconstrained TEXT column — any length, any byte
content, accepted and stored silently, forever, with no CHECK, no length bound, no
downstream sanitization anywhere in this diff.

Failure scenario: an extraction proposal (LLM output — CLAUDE.md itself calls this a
"PROPOSAL," not trusted) sets `comparison.baseline_entity` to a multi-kilobyte string,
or one containing control/escape bytes, instead of a plausible entity_id. Pre-0003 this
either got normalized away or raised `sqlite3.IntegrityError` on insert (fail-loud, the
project's own stated posture). Post-0003 it is accepted unconditionally and flows
straight through `get_claims_for_analysis` → `Assessment.baseline_entity` → (finding 3)
a terminal echo. The dangling-baseline use case only required relaxing "must resolve,"
not "must look like an id at all." That's a scope-creep regression introduced by the
*implementation* of a ratified decision, not the decision itself — exactly the kind of
thing this gate exists to catch.

Minimal fix that doesn't reopen the deferral: a `CHECK (cmp_baseline_entity IS NULL OR
length(cmp_baseline_entity) BETWEEN 1 AND 128)` (or equivalent pydantic-level bound on
`Comparison.baseline_entity`). Still a no-op on every honest fixture; costs nothing
against the golden.

### 2. `reconcile_entity` silently drops vendor/name/entity_type disagreements — an identity-confusion seam that isn't on the named list
`src/semianalyst/store/db.py:219-248`

The merge path unions `aliases`, unions `attribute_citations`, and fill-nulls
`node_*`/`chip_*` columns — but `vendor`, `name`, and `entity_type` are never read from
the incoming `ent` on the merge branch at all. The first document to write an
`entity_id` freezes its identity fields permanently; every later document's values for
those three fields are discarded with **zero signal** — no flag, no log, nothing in
`entities_reconciled` output (which only ever reports `aliases`).

This is distinct from the named K/G/H/resolved-baseline seams (which are about *trust*
between tiers) — this is about *silently conflating two different real-world things*
under one `entity_id` with no way to detect it happened, even in the fully honest
domain (a typo'd vendor in an early curated fixture would never surface). Because it
isn't named in CLAUDE.md's new deferred-guards list, a future reader would reasonably
believe the full taxonomy of "things trusted without checking" is enumerated there. It
isn't — this one is invisible by omission, not by explicit deferral.

## The risk others will miss: `cli.py:report()` echoes untrusted, DB-derived strings straight to the terminal with zero output-encoding — and it's outside the entire Class-A seam list

`src/semianalyst/cli.py:68-77`

```python
for entity_id, info in analysis.entities_reconciled.items():
    typer.echo(f"{entity_id}  aliases={info['aliases']}")
...
line = f"  [{a.status}] {a.metric}"
if a.baseline_entity:
    line += f" vs {a.baseline_entity}"
```

`entity_id`, `aliases`, `metric`, and (per finding 1, now unconstrained) `baseline_entity`
are all ultimately LLM-extraction-proposal content — the same content CLAUDE.md calls a
"PROPOSAL" that only `validate.py`'s grounding/enum checks constrain, and those checks
say nothing about byte content of free-text fields like `metric` (no CHECK on that
column, before or after this diff) or, now, `baseline_entity`. None of it is escaped
before `typer.echo`. A crafted `metric` or `baseline_entity` string containing ANSI/OSC
terminal escape sequences (screen-clear, cursor manipulation, OSC-52 clipboard write,
OSC-8 fake hyperlinks) would fire the moment a human runs `semianalyst report` — no
model, no network, just a terminal rendering DB content.

Why this is the one the other reviewers (schema-purist on grouping semantics,
pragmatist-shipper on fixture-justified code) will miss: it isn't part of the
persistence/reconciliation trust taxonomy CLAUDE.md just wrote up at all — `report()`
lives in a different module (`cli.py`), reads through `analyze/`, and every one of
K/G/H/I/J + resolved-baseline is scoped to *storage* trust, not *display* safety. The
"no hostile document can reach `persist_extraction`" argument that justifies deferring
K–J does NOT cover this: `extract/`'s real LLM call is explicitly WIP (module map:
"LLM: WIP/stub"), and the day it goes live, model output reaches `report()`'s terminal
echo with **no code change required on the display side** and no gate in this
workstream watching for it. It will ship silently, wearing the "curated fixtures only"
justification that no longer applies to it.

## What I verified was clean (no complaint)
- No SQL string ever interpolates external data — `reconcile_entity`'s and
  `table_counts`'s f-string-built column lists are built only from static Python dict
  keys / literal tuples defined in source, never from row or model data. All values
  are bound via `?` parameters throughout `db.py` and `persist.py`.
- No tier-precedence, alias-gating, tier-diversity floor, conflict-storage, or
  slug-tripwire code exists anywhere in `reconcile_entity` / `persist_extraction` /
  `corroborate.py` — the deferral is real, not cosmetic.
- CLAUDE.md's new "Hostile-input trust is DEFERRED" section accurately matches the
  shipped code for every item it names (K, G, H, resolved-baseline poisoning, I/J).
- Tests added (`test_reconciliation.py`, `test_analyze.py`) are exclusively
  honest-domain — no adversarial fixtures were manufactured to justify unshipped code,
  matching the resolution's explicit instruction.
