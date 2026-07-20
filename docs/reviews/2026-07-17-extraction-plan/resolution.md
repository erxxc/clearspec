# Resolution — extraction-engine (plan)

Merge of the four opinions in this directory, written by the main session
(orchestrator). Rules honored: agreements highlighted; conflicts named with
cost and **not averaged**; the human decides each named conflict; the
false-middle is called out, not adopted.

> **Process note:** the custom agent types (`injection-attacker`, etc.) were
> created this session and aren't yet in the agent registry, so each reviewer
> ran as a `general-purpose` subagent with its committed `.md` persona injected
> verbatim (reviewers pinned to sonnet, advocate to opus). Same bias, same
> output contract. A session started after these files exist will invoke them by
> name.

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | **CONDITIONAL** | Delimiting/secret/claim-grounding sound, but "injection test passes" is satisfiable without the live model, and entity-attr grounding (C) is enforced by nothing but prompt wording. |
| schema-purist | **BLOCK** | Entity node/chip attributes have zero code-enforced grounding — the exact world-knowledge-injection class that already corrupted this fixture. |
| pragmatist-shipper | **CONDITIONAL** | Architecture lean; trim untested normalization/dedup code, cut prompt-caching, and reject a shadow-schema field as the C fix. |
| devils-advocate | (challenge) | The green DoD has **zero real-model coverage**; C is a real fork (v2-schema vs accept-risk); the coarse substring check is a trap; enforce-vs-curate is the upstream question. |

## Agreements (strong signal — proceeding on these)
- **The `ModelClient` seam + replay determinism is the right architecture.** Pragmatist endorses it outright; nobody attacks it. Kept.
- **Scope discipline is correct:** `store/`/`cli.py`/`analyze/`/`config.py` untouched, `pdfplumber` deferred, `run_extract` stays stubbed. Kept.
- **Claim `quote_span` grounding, key-from-env-never-logged, structured-output-as-proposal** — endorsed/unattacked. Kept.
- **Prompt caching (§3) is cut from this phase.** Pragmatist calls it scope creep with no test payoff; nobody defends it; I added it. Removed, noted as a fast-follow.
- **"Accept a gap explicitly with a revisit trigger" is a legitimate mechanism** all three endorse — the dispute is *which* gaps, not the mechanism.

## Q0 — THE UPSTREAM DECISION (devils-advocate; answer first, A and C fall out of it)
**Does `semianalyst` ENFORCE grounding, or CURATE fixtures that look grounded?**

Every verification path in the green DoD terminates in a hand-authored artifact
(`raw.pdf` human-enriched in §0, `llm_response.json` human-recorded,
`expected.json` human-declared grounded, rules human-written). `uv run pytest`
can be green — golden passing, `xfail` removed, "injection test passes" — with
**zero executions of the real Anthropic model**, functional or adversarial. The
golden test is, today, a unit test of `validate.py` in the golden harness's
clothes. Compounding it: the §0 enrich-the-doc choice removed the corpus's only
ungrounded-entity-attribute example, so the golden case *cannot fail on
entity-attribute grounding by construction* — both postures below inherit that,
which is why a dedicated **negative** fixture is required either way.

| Posture | What the DoD then requires | Cost |
|---|---|---|
| **ENFORCE** | Live golden + live injection tests are the **mandatory anchor**, run in CI with a key; replay (real recorded + provenance-stamped) is the fast offline layer beneath. | CI needs `ANTHROPIC_API_KEY`, real $/run, some nondeterminism to manage. |
| **CURATE** | This phase certifies the validation pipeline only; the live model is opt-in (`--run-live`); we say so plainly and stop demanding code checks the corpus can't exercise. | "Green" ≠ "the extractor works"; real-model correctness + injection-resistance unverified in CI. |

*Orchestrator recommendation:* **ENFORCE** — the project's entire thesis (schema design principles #3, CLAUDE.md hallucination-control) is grounding; a green suite that never runs the model contradicts it. But this is the human's call.

## Named conflicts (NOT averaged)

### Conflict 1 (sharpest) — Decision C: entity-attribute grounding
- **schema-purist** blocks without code enforcement; proposed mechanism: an internal `_attribute_evidence: {field: quote}` side-channel in the proposal JSON that `validate.py` substring-checks then strips.
- **pragmatist** blocks *that mechanism* as a **shadow schema** — a binding field living only in code, violating CLAUDE.md's "the data model is the source of truth."
- **Role inversion (advocate):** the purist is willing to abandon schema purity to get enforcement; the pragmatist is defending it. You **cannot** resolve this by "trust the purist on schema."
- **injection-attacker's coarse substring check is the FALSE MIDDLE — rejected, with evidence:** `"2025-12-01"` is not a substring of "December 2025" (over-rejects a correctly grounded date); `"gaa_nanosheet"` is not in "gate-all-around nanosheet" (over-rejects a grounded enum); `"cfet"` grounds on any coincidental 4 letters (under-rejects); booleans can't be substring-grounded at all. It manufactures the *feeling* of enforcement while providing none, and worse, lets everyone mark C "handled." **Do not pick this.**
- **Two coherent resolutions only:**
  - **(a) Real v1→v2 schema bump** — per-attribute citation slot for entity attributes, done the CLAUDE.md way (`_v2.yaml` → regenerate models → new migration). The honest version of what the purist wants. Cost: schema version + migration + prompt emits evidence + larger scope.
  - **(b) Explicit accepted residual risk** + revisit trigger in this doc. Cost: entity-attribute injection uncaught this phase (the class that bit the fixture).
- **Falls out of Q0:** ENFORCE → lean (a) (now, or (b) now + (a) next); CURATE → (b) stated plainly.
- **DECISION NEEDED.**

### Conflict 2 — Decision A: what replay must be / live tests in CI
- **injection-attacker:** hand-written replay proves nothing about the model; wants live-in-CI **or** a recorded *real* adversarial transcript.
- **pragmatist:** replay is right but must be **provenance-stamped** (prompt sha256 + model name, asserted at run time) or it degrades to a tautology.
- **Resolved sub-decisions (both reviewers, apply regardless of Q0):** (i) replay artifacts must be **real recorded** responses, not hand-authored; (ii) stamp `llm_response.json` with prompt sha256 + `config.model.name` and assert the match at test time.
- **Residual = Q0:** whether the live test is a mandatory CI anchor (ENFORCE) or opt-in (CURATE).

### Conflict 3 — validate.py unexercised rules
- **pragmatist:** unit-normalization (§6.4), entity-dedup (§6.7) have zero exercised paths; marketing_only (§6.5) is admitted untested; §12 names no unit-test file. Cut the rules **or** test them.
- **schema-purist:** wants all rules enforced.
- **SYNTHESIS (not an average — both satisfied by adding coverage, not by cutting or by shipping-untested):** add `tests/test_validate.py` covering unit-normalization, dedup-on-collision, marketing_only, **and** a **negative** `is_relative` case (schema-purist F2: a proposal that absolutizes the 1.15x claim without `is_relative` must be rejected). *Recommended; confirm.*

## Blind spots each caught alone (proposed disposition — accept unless you object)
- **Hidden/invisible PDF text (injection-attacker):** `pypdf` extracts white-on-white / zero-size / off-page text identically to visible text; "grounded" collapses to "in extracted text," not "human-visible," and `review_status: human_verified` becomes a false signal. → **add a hidden-text case to the injection fixture**; accept residual (real detection needs a visibility-aware parser) with **revisit at `pdfplumber` adoption.**
- **Cross-corpus entity dedup (schema-purist):** "one entity per real thing" silently narrows to *per-document* because `store/` is out of scope. → **hand off an explicit alias-resolution contract** to the store workstream (does dedup re-run against existing DB entities at insert? exact vs fuzzy? who mints the canonical id?). Recorded here as an open handoff.
- **`location_type` default = `body` (schema-purist F3):** launders a footnote-shaped (suspicious) claim into the most-trusted bucket — inverts the schema's signal. → **DECISION:** fail-safe (flag footnote-shaped claims via `review_status`, or leave location unknown) vs accept-with-limitation + revisit at `pdfplumber`. *Recommendation: fail-safe.*
- **Unmonitored free-text fields (injection-attacker F3):** `stated_caveats`, `workload`, `aliases`, `package_type`, … written verbatim, ungrounded. Lower severity (not corroboration-math inputs). → **accepted-risk line + revisit.**
- **marketing_only "competitor" scope (schema-purist secondary):** cross-vendor only, or same-vendor generational too? → **clarify before `validate.py` hard-codes it.**
- **substring strictness (schema-purist secondary):** `pypdf` mangles hyphenation/ligatures; exact match over-rejects, loose under-rejects. → **specify whitespace-normalized substring on both sides.**

## Decisions (human — 2026-07-18)
- **Q0 = ENFORCE.** Live golden + live injection tests are the **mandatory CI anchor** (`uv run pytest --run-live`, key required); replay (real recorded + provenance-stamped) is the fast offline layer. "Green" in CI means the model was actually exercised.
- **Conflict 1 (Decision C) = v2 schema bump now.** New `schema/extraction_schema_v2.yaml` gives entity attributes a per-attribute citation slot; regenerate `store/models.py`; add migration `0002`; the prompt emits per-attribute evidence; `validate.py` grounds entity attributes the same way it grounds claims. **This intentionally expands scope into `store/`** — authorized by this decision, overriding the earlier "don't touch store" constraint *for the schema bump only*.
- **`location_type` = fail-safe.** Never silently default to `body`; when location can't be determined from flat text, flag via `review_status`. Revisit at `pdfplumber`.
- **Confirmed (orchestrator recommendations, no objection):** add `tests/test_validate.py` + a negative `is_relative` fixture; replay artifacts are **real recorded** responses stamped with prompt sha256 + model name and asserted at run time; a hidden-text case in the injection fixture; a cross-corpus entity-dedup contract handed to the store workstream; whitespace-normalized substring matching; prompt caching cut.

## Representation note (flagged for GATE 2)
The v2 "per-attribute citation slot" is implemented as an `entity.attribute_citations` map (attribute-name → {quote_span, page, location_type}) rather than wrapping every value as `{value, evidence_quote}` — same grounding contract, without doubling every entity column. Subject to GATE 2 (diff) review.

## Outcome
**UNBLOCKED for implementation** per the decisions above. GATE 2 (pre-commit, diff review) follows once `uv run pytest --run-live` is green; commit only after human sign-off.
