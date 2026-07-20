# schema-purist — GATE 1 (plan) review

**Target:** `docs/reviews/2026-07-17-extraction-plan/plan-under-review.md`
**Grounded against:** `CLAUDE.md`, `schema/extraction_schema_v1.yaml`,
`tests/fixtures/tsmc_n2_2025/{raw.pdf,expected.json}`

## Verdict: BLOCK

Two of the schema's non-negotiable integrity rules — "every extracted value
cites a source span" and the footnote-suspicion signal built into
`citation.location_type` — are, by the plan's own admission, left
code-*unenforced* by design in this pass. The fixture's own history (§0 of
the plan) already proved what happens when grounding is left to model
discipline instead of code: it silently rewarded world-knowledge injection.
I'm not willing to approve a plan that reopens the same class of gap for
entity attributes while calling it "accepted" via an open decision. See
Finding 1.

---

## Finding 1 (blocking): Entity node/chip attributes have zero code-enforced grounding

§6 ("Known gap — open decision C") states plainly: *"the schema has no
per-attribute citation slot for entity node attributes (transistor_type,
hvm_date, ...), so their grounding is enforced by prompt discipline (§4),
not by a code substring check. Claims are code-enforced; entity attributes
are not."*

This is precisely the failure mode §0 describes as having already happened
to this fixture: `expected.json` originally asserted `transistor_type`,
`backside_power`, and `hvm_date_claimed` that weren't in `raw.pdf` at the
time — world-knowledge injection into entity attributes, not claims. The
team's own fix was to enrich the *document*, not to add a grounding check —
which means the underlying enforcement gap that let it happen once is
still open, and the plan proposes to ship without closing it. CLAUDE.md is
unambiguous here: *"you never trust the model to self-enforce"* is the
review persona's mandate for a reason — prompt instructions are not a
control, they're a preference the model can silently drop under context
pressure, distractor tokens, or an injection payload (see §7 — the
`injection_attack` fixture only tests *claim* fabrication, not a poisoned
entity attribute like a fake `hvm_date_claimed`).

Concretely: nothing stops a proposal where `entity.node.hvm_date_claimed =
"2024-06-01"` when the document says December 2025, or where
`transistor_type = "cfet"` when the document never mentions a transistor
type at all. `validate.py` step 1 (shape) would accept it — it's a
schema-valid enum/date value with no companion field to fail a substring
check against.

**What I need to see before this is acceptable:** at minimum, a per-entity
"supporting quote(s)" side-channel (even if it never lands in the schema
proper — e.g. the raw proposal JSON carries an internal
`_attribute_evidence: {field: quote}` map that validate.py substring-checks
and then strips before building `Entity`) so entity attributes get the same
hallucination control claims get. If the team decides the cost isn't worth
it for this phase, that's a legitimate call — but it must be made
explicitly as a **known, accepted risk with a revisit trigger**, not folded
into "prompt discipline handles it."

## Finding 2: `is_relative` grounding trusts the model's self-classification, not the source text

§6.3 enforces "relative-never-absolutized" as: *if `comparison.is_relative`,
require `baseline_entity` set and a ratio unit; reject a relative claim
carrying a converted absolute.*

Read that conditional carefully: the entire rule is gated on the model
having already set `is_relative: true`. Nothing in the validation pipeline
independently derives relativity from the `quote_span` itself (e.g.
detecting "x faster/slower", "times", "%  improvement over", ratio
language) and cross-checking it against what the model emitted. If a model
proposal takes "1.15x logic speed... versus N3E" and emits it as a plain
absolute claim (`value: 1.15`, `unit: "x"`, `is_relative: false`, no
baseline) — or worse, computes and stores some derived absolute number
while quietly omitting the relative flag — step 3 never fires, because it
only inspects claims the model *already labeled* relative. This is
output validation *assuming the extractor already did the classification*,
which is the exact question the persona brief calls out: "does output
validation actually enforce the schema, or does it assume the extractor
already did?" Here, for the single most load-bearing rule in the whole
schema (the golden fixture's own docstring: *"this fixture exists to lock
in that rule"*), the answer is: it assumes.

I'd want the golden test suite to include a *negative* fixture — a replay
response where the model absolutizes the 1.15x claim without setting
`is_relative` — to prove this gap is closed, not just tested on a
compliant proposal.

## Finding 3: `location_type` defaulting to `body` doesn't just lose fidelity — it inverts the schema's trust signal

§5 accepts `pypdf`'s flat-text limitation by defaulting every claim's
`citation.location_type` to `body`. The schema's own comment on this field
is not neutral: *"footnote-sourced claims deserve suspicion"* — footnotes
are explicitly where marketing conditions/caveats (the sparsity lever,
narrow benchmark configs) get buried. Defaulting to `body` doesn't just
lose the `table`/`figure` distinction (arguably fine to defer); it
specifically launders a claim that *should* read as suspicious into one
that reads as equally trustworthy as prose. That's a regression against a
signal the schema was deliberately designed to carry, not a gap in
coverage.

Given `pdfplumber` is already scoped as the fix and simply deferred, at
minimum the plan should default footnote-shaped claims to a
`review_status` that flags them for human eyes (the schema already has
`disputed`/`unreviewed` at the document level) rather than silently
collapsing the distinction to the most-trusted bucket by default. Defaulting
to the *least* trusted assumption (or leaving location_type null/unknown,
if the enum allowed it) would at least fail safe; defaulting to `body`
fails toward false confidence.

---

## Risk others will miss: "one entity per real thing" only holds *within a single document's proposal*, not across the corpus

`validate.py` step 7 dedupes entities by `(vendor, normalized name)` and
merges aliases — but only within one extraction proposal, because
persistence (`store/`) is explicitly out of scope (§10) and `run_extract`
stays stubbed. CLAUDE.md's rule is *"one entity per real thing (resolve
aliases before insert)"* — but there is no insert in this workstream, so
what actually gets validated is closer to "one entity per real thing,
per document." The moment a second document referencing the same N2 node
lands (a Hot Chips paper calling it something slightly different, or TSMC's
own later doc spelling it "N2" vs "TSMC N2"), nothing in this plan
establishes the alias-resolution contract `store/` will need at insert
time — is dedup expected to run *again* against existing DB entities on
insert? Fuzzy-match on name, or exact on a canonical id the extractor
doesn't know how to mint yet? The plan is silent, because it's genuinely
out of scope — but "out of scope" here quietly narrows a whole-repo
invariant to a per-document one without saying so. `injection-attacker` is
watching for hostile input and `pragmatist-shipper` is watching for
scope/DoD creep in the other direction (adding work); neither is
positioned to notice a schema invariant silently shrinking in *meaning*
while its *name* stays the same across a workstream boundary. When `store/`
picks this up, someone needs to re-derive "what does entity dedup mean at
insert time" from scratch unless this plan (or its resolution doc) hands
off an explicit contract now.

---

## Secondary notes (not primary findings, flagging for the record)

- §6.5's `marketing_only` rule is phrased in the plan as firing on a
  "cross-vendor baseline," but the schema/CLAUDE.md text says "competitor
  claim" without defining competitor as strictly cross-vendor. A same-vendor
  generational comparison ("2x throughput vs. our prior gen" with
  `sparsity=true`) is arguably just as marketing-shaped and should probably
  also tag `marketing_only`. Worth confirming the intended scope of
  "competitor" before `validate.py` hard-codes cross-vendor as the trigger.
- The grounding check's substring-match strictness (§6.2) is unspecified —
  exact substring vs. whitespace/ligature-normalized. Given `pypdf` text
  extraction is known to mangle hyphenation and ligatures, an exact match
  will over-reject; a loosely normalized match risks under-rejecting a
  near-paraphrase as "grounded." The plan should pin down the normalization
  applied on both sides of the comparison (extracted PDF text and the
  model's `quote_span`) rather than leaving it implicit.
