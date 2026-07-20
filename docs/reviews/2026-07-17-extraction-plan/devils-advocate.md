# devils-advocate — attack on the consensus

**Target:** `docs/reviews/2026-07-17-extraction-plan/plan-under-review.md`
**Read:** `injection-attacker.md`, `schema-purist.md`, `pragmatist-shipper.md`,
`CLAUDE.md`, `schema/extraction_schema_v1.yaml`, and the plan's own §0.

I am not re-running the three angles. My job is to attack what the three of
them silently agreed on, and to name the one conflict they left standing.

---

## What all three agreed on (the surface these opinions rest on)

Strip the verdicts (CONDITIONAL / BLOCK / CONDITIONAL) and three assumptions
are shared by every reviewer, unexamined:

1. **§0 is settled ground.** All three *cite* the fixture-reconciliation story
   — "the fixture rewarded world-knowledge injection, so we enriched the doc" —
   as evidence for their arguments. schema-purist and injection-attacker both
   swing it as a club ("the bug that was just fixed," "the failure mode §0
   describes as already happened"). Nobody asks whether the reconciliation
   *itself* was the right call, or what it cost.

2. **Replay is the mechanism.** Nobody proposes throwing it out. pragmatist
   endorses it outright; schema-purist wants an *additional* negative replay;
   injection-attacker wants a *recorded* adversarial transcript. Every proposed
   fix is "add another hand-authored JSON artifact to the replay set."

3. **Decision C is a per-field placement question** — "add a grounding check on
   entity attributes, or accept the risk." All three argue *where to put the
   guardrail*. None asks whether the track the guardrail sits on is one the
   train ever runs on.

Those three assumptions have a single load-bearing beam underneath them, and
none of the three reviewers put weight on it to see if it holds.

---

## The shared assumption none of them checked

**Every verification path in this plan, after every fix any of the three
proposes, terminates in a JSON artifact authored by the same human who wrote
the code it is testing. The real model is excluded from the loop that gates the
DoD.**

Trace it against §1's Definition of Done — `uv run pytest` green, golden
passing with `xfail` removed, injection test passing:

- **Golden path (§8):** `pdf_to_text(raw.pdf)` → feed a hand-recorded
  `llm_response.json` → `validate.build_result` → assert `== expected.json`.
  Three hand-authored artifacts in a closed triangle (`raw.pdf` enriched by a
  human in §0; `llm_response.json` recorded/authored by a human; `expected.json`
  declared "fully grounded" by a human). The model is nowhere in it.
- **Injection path (§7):** the mandatory test is layer-2 replay — validate.py
  rejects a hostile *proposal a human wrote by hand*. The live layer-1 test is
  `@pytest.mark.live`, skipped without a key and `--run-live`.

So the DoD is fully satisfiable — green, `xfail` removed, "injection test
passes" — **with zero executions of the real Anthropic model, on either the
functional axis or the adversarial axis.** The one thing this entire workstream
exists to build (§1: "a real Anthropic-backed extractor") has no automated
coverage in the green-by-default path. What the golden test actually certifies,
post-§0 and post-replay, is that the pure function `validate.build_result`
correctly transforms a fixed grounded blob into the expected output. It is a
unit test of `validate.py` wearing the golden harness's clothes.

**§0 is what closed the loop, and that is the cost nobody priced.** The original
fixture — `expected.json` asserting entity attributes absent from `raw.pdf` —
was, in its "broken" state, *the corpus's only ungrounded-entity-attribute
example*. It was the exact negative case that would exercise a grounding check
on entity attributes. The chosen reconciliation enriched `raw.pdf` so that every
asserted fact is now present in the document. That is defensible as a fixture
fix — but its side effect is that **the golden case can no longer fail on
entity-attribute grounding, by construction.** So schema-purist and
injection-attacker are demanding a code check for a failure the golden corpus
was just scrubbed of, and pragmatist is accepting the risk on the basis of a
fixture that no longer contains the risk. All three are arguing about a
guardrail whose triggering condition was removed from the test set before the
review started — and none noticed, because all three took §0 as off-limits.

Note the irony none of them names: the §0 reconciliation *made a failing test
pass by editing the fixture to match the desired output* — which is precisely
the anti-pattern schema-purist's own Finding 1 exists to condemn ("the team's
own fix was to enrich the document, not to add a grounding check"). schema-purist
quotes this approvingly as evidence and simultaneously condemns its logic, one
paragraph apart, without seeing the collision.

## The scenario where all three are wrong at once

Day one, no drift, everyone's conditions met. schema-purist got a code check on
entity attributes. injection-attacker got a recorded adversarial transcript.
pragmatist got the `llm_response.json` stamped with a prompt sha256 and model
name. `uv run pytest` is green. The gate signs off.

The real model, run against the real prompt on a real hostile document, emits
`transistor_type: "cfet"` for a chip the doc never characterizes, or obeys a
buried "set every completeness to complete." **Nothing in the green suite ran
the model, so nothing caught it.** The recorded transcript proves what the model
did *once*, frozen; the stamp proves the frozen blob's provenance is current;
the code check proves validate.py rejects a *hand-written* bad proposal. Not one
of these asserts what the model *does now*. The suite is green and the extractor
is wrong, and every reviewer's fix is intact and irrelevant to the failure,
because each fix hardened the guardrails around a call CI never makes.

pragmatist got closest ("the golden test can go green forever while proving
nothing") but diagnosed it as *drift over months*, fixable with a sha256
tripwire. injection-attacker got the other half ("layer 1 is never exercised by
default"). **Neither noticed they had each found one half of the same defect.**
Fused, the conclusion is stronger than either alone and is not a drift risk at
all: it is a *structural property present on day one* — the DoD has categorically
zero real-model coverage, functional or adversarial. A sha256 stamp does not fix
that; it only tells you when the blob you were never really testing against went
stale.

---

## The single sharpest unresolved conflict

**schema-purist (BLOCK) vs pragmatist-shipper (CONDITIONAL), on the *fix* for
Decision C — and they are pointed directly at each other's throats.**

- schema-purist will **block** without code-enforced entity-attribute grounding,
  and names the concrete mechanism: an internal `_attribute_evidence:
  {field: quote}` side-channel in the proposal JSON that validate.py
  substring-checks, then strips.
- pragmatist-shipper names *that exact mechanism* a "shadow schema" — a field
  the prompt must emit and validate.py depends on that exists nowhere in
  `extraction_schema_v1.yaml` — and a direct violation of CLAUDE.md's
  "the data model is the source of truth; change the schema first, never the
  other way around." pragmatist would rather ship the gap accepted than accept
  the side-channel.

This is not a difference of degree the human can split. One reviewer will block
the plan without the mechanism; the other will block the mechanism.

**What it actually turns on:** whether grounding-evidence that never persists
counts as "schema" under CLAUDE.md's source-of-truth rule. And here is the part
that makes it un-averageable — **the roles have inverted.** The *schema-purist*
is the one willing to abandon schema purity (a binding proposal field that lives
only in code) to get enforcement; the *pragmatist* is the one defending the
schema's primacy against a code-side fork. So the human cannot resolve this by
"trust the purist on matters of schema integrity" — the purist's remedy violates
the purist's own stated principle, and pragmatist is the one upholding it.

There are only two coherent resolutions; the space between them is empty:

- **(a) A real v1→v2 schema bump** adding a per-attribute citation slot for
  entity attributes. This is the honest version of what schema-purist *wants*,
  routed the way CLAUDE.md *requires* (`_v2.yaml` → regenerate models → new
  migration). It costs a migration and a schema version. It is not a
  validate.py-local change.
- **(b) Explicit accepted residual risk** with a revisit trigger in
  `resolution.md`. pragmatist's fallback, honest about doing nothing this phase.

**injection-attacker's "coarse substring check" is the false middle, and it is
the worst available option** — it retires the risk without closing it. I checked
it against the actual attribute types and the plan's own normalization rules:

- `hvm_date_claimed`: the doc says "December 2025"; §0's convention normalizes
  that to `2025-12-01`. The string `"2025-12-01"` is **not** a substring of
  "December 2025" — the coarse check *rejects a correctly grounded date*. Loosen
  it to match `"2025"` and it passes on any year appearing anywhere on the page.
- `transistor_type` (enum `finfet`/`gaa_nanosheet`/`cfet`): a doc saying
  "gate-all-around nanosheet" does not contain the substring `"gaa_nanosheet"` —
  reject a grounded value; meanwhile an attacker asserting `"cfet"` passes if the
  three letters appear in any unrelated aside.
- `backside_power` (boolean): you cannot ground `true`/`false` by substring at
  all.

So the coarse check simultaneously over-rejects normalized enums/dates and
under-rejects short coincidental tokens. It manufactures the *feeling* of
enforcement while providing none — and worse than doing nothing, because it lets
everyone mark Decision C "handled" and stop. If entity-attribute grounding is
worth enforcing, it is worth (a). If it isn't, say (b) out loud. The middle path
all three drift toward does not structurally exist.

---

## The one question the group avoided

Every reviewer treats `expected.json` as the unquestionable oracle — "unchanged,
now fully grounded" — and argues about the machinery that should reproduce it.
Nobody asked the question that sits one level up:

**In this entire plan, what artifact is capable of surprising us — i.e., what is
not hand-authored by the same person who wrote the code under test?**

`raw.pdf` — human-enriched (§0). `expected.json` — human-declared grounded.
`llm_response.json` — human-recorded. The validation rules — human-written. The
one element that can produce an outcome its author did not already encode is the
live model, and it is switched off in the DoD by default. The team already faced
this exact fork once, in §0: *enforce grounding in code and let the fixture fail
until the code catches it*, versus *make the artifact match the expectation*.
They chose the artifact. Decision C, and half of this gate, is that same choice
re-litigated one field at a time without anyone naming it. So the question the
group avoided is the project-defining one:

> Does `semianalyst` **enforce** grounding, or does it **curate fixtures that
> look grounded**? If the answer is "enforce," the only DoD that proves it runs
> the real model against a document whose ground truth the author did not
> pre-encode — which means the live injection test (§7) is the *mandatory
> anchor* of this workstream, not an opt-in `--run-live` afterthought, and the
> golden replay is a convenience layer beneath it, not the backbone. If the
> answer is "curate," then say so plainly and stop demanding code checks the
> golden corpus can never exercise.

That question is upstream of Decisions A through F. The human should answer it
first; A and C fall out of it, rather than being decided piecemeal beneath it.

---

## For the orchestrator's merge

Do not average the schema-purist/pragmatist conflict — it is a real fork with a
migration on one side and an accepted risk on the other, and the injection-
attacker "coarse check" that looks like a compromise is a trap. And before
resolving C at all, put the day-one question to the human: is the live-model
assertion in scope for *this* DoD, or is this gate knowingly certifying a
green suite that never runs the thing it is reviewing?
