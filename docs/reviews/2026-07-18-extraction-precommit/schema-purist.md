# schema-purist — GATE 2 (pre-commit / diff) review

**Scope:** `docs/reviews/2026-07-18-extraction-precommit/workstream.diff`, cross-checked
against `schema/extraction_schema_v2.yaml`, `src/semianalyst/store/models.py`,
`src/semianalyst/store/migrations/0002_entity_grounding_and_unknown_location.sql`,
`src/semianalyst/extract/validate.py`, `tests/fixtures/tsmc_n2_2025/expected.json`,
`tests/test_validate.py`, and `docs/reviews/2026-07-17-extraction-plan/resolution.md`.

## Verdict: **BLOCK**

The thing I blocked GATE 1 over — entity-attribute grounding — is now genuinely
code-enforced: `Entity.attribute_citations: dict[str, Citation]` is a real v2 schema
field (not a shadow side-channel), `models.py` and migration `0002` derive from
`extraction_schema_v2.yaml` correctly, and `validate.py`'s `GROUNDABLE` table matches
the schema's node/chip fields exactly (including the `hvm_date_actual` /
`process_node_ref` exemptions). That decision is honored. I am not blocking on
Conflict 1 again.

I am blocking on a **new, ship-blocking correctness bug in the normalization layer**
(F1 below) that silently destroys correctly-grounded, correctly-classified data for
an entire schema-enumerated `claim_class`, with zero test coverage on the failure
axis — exactly the kind of unexercised normalization rule this diff was supposed to
close out (Conflict 3), not introduce.

## Findings

### F1 (blocking) — the "undeclared relativity" rule conflates `%`-the-unit with `%`-means-comparison, and silently kills valid absolute claims

`validate.py`:
```python
if claim.unit in RATIO_UNITS and not claim.comparison.is_relative:
    rejections.append(Rejection("claim", claim.claim_id,
                                "ratio unit but is_relative not set (undeclared relativity)"))
    continue
```
`RATIO_UNITS = {"x", "X", "×", "%"}`. `x`/`×` are unambiguous — nothing is ever
absolutely measured "in x". But `%` is **not** always a comparison: the schema's own
`claim_class` enum includes `yield`, and yield is reported as an absolute rate
("N2 yield is 65%"), not a ratio against a baseline. Same problem for a bare
sparsity percentage, a revenue-share figure, or any other absolute rate a foundry
document states in `%`.

**Failure scenario:** a claim `{metric: "yield_rate", value: 65, unit: "%",
comparison.is_relative: false, citation.quote_span: "<verbatim, grounded>"}` —
perfectly grounded, perfectly shaped, correctly *not* relative — is dropped with
reason `"ratio unit but is_relative not set"`. The pipeline doesn't just fail to
catch bad data here; it destroys good, grounded data. That is a strictly worse
failure mode for a schema whose design principle #3 is "every extracted value
cites its source span" — the citation existed and was thrown away anyway.

Worse, the prompt (`extract_foundry_v1.md`, rule 2) tells the model "Store the
ratio/percentage as `value` with `unit` … `%`, set `comparison.is_relative` true" —
wording that doesn't distinguish "this % is a comparison" from "this % is an
absolute rate," so the model is as likely to be pushed toward mislabeling an
absolute yield figure as `is_relative: true` with no baseline (corrupting
`comparison` semantics) as it is to leave `is_relative: false` and get the claim
dropped outright. Either way, `%`-valued absolute claims are not represented
correctly by this schema+prompt+validator triad as shipped.

**Unexercised:** `tests/test_validate.py` only exercises `x`→ratio and
`TB/s`→`GB/s` unit paths. There is no test with `unit="%"` and
`is_relative=False`. This is precisely the class of untested normalization rule
Conflict 3 was supposed to close — instead it shipped a *wrong* rule with no test
to catch the regression or the original bug.

### F2 — entity dedup merges citations but not the attribute values they cite, producing orphaned or lost grounding

In `validate_proposal`'s merge branch:
```python
for path, cite in ent.attribute_citations.items():
    base.attribute_citations.setdefault(path, cite)
```
Only `aliases` and `attribute_citations` are merged into `base`; `base.node` /
`base.chip` themselves are never touched. Concretely: if the first-seen entity for
`(vendor, name)` has `node.transistor_type = None`, and a later duplicate in the
same proposal has `node.transistor_type = "finfet"` with a grounded citation, the
merge copies `"node.transistor_type"` into `base.attribute_citations` while
`base.node.transistor_type` stays `None` — an **orphaned citation**: a grounding
record for a field that, on the merged entity, doesn't hold the value it purports
to ground. The inverse also happens: a genuinely grounded attribute value on the
discarded duplicate is dropped entirely because only `base`'s node/chip survive.
Either direction breaks "every non-null attribute has a citation for **that**
value" — the schema's own invariant, restated in `models.py`'s docstring.

`tests/test_validate.py::test_entity_dedup_merges_by_vendor_and_name` only exercises
two entities with `node=None`/`chip=None` — the merge-with-real-attributes path
(where this bug lives) is completely untested.

### F3 — a rejection path with no `Rejection` logged, breaking the file's own audit contract

`validate.py`'s module docstring promises "Rejections are logged (kind + target +
reason only...)" for everything dropped. But:
```python
for path in list(ent.attribute_citations):
    if path not in _VALID_PATHS:
        ent.attribute_citations.pop(path)   # stray citation for a null/unknown field
    else:
        _force_unknown(ent.attribute_citations[path])
```
A citation keyed by a path that doesn't match a known `node.*`/`chip.*` field (a
model typo, a stale key after a schema rename, or an adversarial probe of which
paths the validator checks) is silently discarded — no `Rejection`, no log line,
nothing. Every *other* drop in this file (ungrounded claim, ungrounded attribute,
shape-invalid item, entity merge) is logged; this one isn't. Given the persona this
project has adopted toward the model ("PROPOSAL, not truth" — never trust it to
self-enforce), a silently-dropped citation is exactly the kind of leniency that
should never ship unlogged: it removes the one signal (`rejections`) an operator
would use to notice the model is emitting malformed attribute paths at all.

## Risk others will miss

**The `location_type=unknown` fail-safe is not wired to the mechanism the human
actually approved.** `resolution.md`'s decision line reads: *"`location_type` =
fail-safe. Never silently default to `body`; when location can't be determined
from flat text, **flag via `review_status`**."* The diff implements half of
that sentence: `validate.py::_force_unknown` unconditionally sets
`citation.location_type = LocationType.unknown` for every claim and every
surviving attribute citation. But `review_status` lives only on `Document`
(`models.py:117`), is set once at ingest (`ReviewStatus.unreviewed` by default),
and is never read or written anywhere in `validate.py` — grep confirms the only
writer is `db.insert_document`. So the "flag" half of the approved fail-safe
doesn't exist: an `unknown`-location claim is stored and treated identically to a
`body`-location claim by every downstream consumer, and there is no queryable
signal that would ever route a document to human review *because* its claims'
locations were undeterminable. This will read as "done" to a reviewer checking
"does `location_type` avoid defaulting to `body`?" (yes) without checking whether
the review-routing half of the decision was actually implemented (it wasn't). It's
the kind of thing that only surfaces by diffing the code against the exact wording
of the resolution doc, not by reading the code or the schema changelog in
isolation — both of which describe `unknown` as if it were the complete fail-safe.

## What would move this to CONDITIONAL/APPROVE
Fix F1 (either scope `RATIO_UNITS`'s reverse-check to claim classes/metrics that
are inherently comparative, or drop the "undeclared relativity" auto-reject for
`%` and rely on `comparison.baseline_entity is None` + `completeness=missing_baseline`
instead — schema already has that vocabulary), add the missing % / yield test case,
fix the merge to reconcile node/chip values (not just citations) or reject silently
inconsistent merges outright, log the stray-attribute-citation drop as a
`Rejection`, and either wire `review_status` per the resolution's wording or update
`resolution.md`/`CLAUDE.md` to reflect that `location_type=unknown` alone *is* the
agreed fail-safe (a real decision, not a silent narrowing).
