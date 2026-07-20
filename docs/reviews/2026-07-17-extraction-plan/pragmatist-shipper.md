# pragmatist-shipper — GATE 1 (plan) review

**Target:** `docs/reviews/2026-07-17-extraction-plan/plan-under-review.md`
**Grounded against:** `CLAUDE.md`, `schema/extraction_schema_v1.yaml`,
`tests/fixtures/tsmc_n2_2025/{raw.pdf,expected.json}`, `extract/base.py`,
`extract/pipeline.py`, `store/models.py`, `tests/test_golden.py`.

## Verdict: CONDITIONAL

The bones are right: replay-based determinism for the golden test (§8) is the
correct call over a live-API golden test, `store/`/`cli.py`/`analyze/` staying
untouched (§10) is correctly enforced scope discipline, and `pdfplumber` is
correctly deferred (§9) rather than added speculatively. The `ModelClient`
seam (§2) — which the plan explicitly dares me to attack — is not where the
fat is; it's the minimum abstraction needed to get an offline-deterministic
test, and I have no cheaper way to get that. I'd approve outright except that
§6 quietly bundles a meaningful amount of code that nothing in the DoD ever
exercises, and §3 smuggles in a production optimization with the same
problem. Trim those and this ships clean.

## Findings (shipping/overengineering angle only)

**1. Half of `validate.py`'s seven rules are unexercised by anything in the
DoD — write only what the fixture needs, or name the tests that are missing.**
I pulled the actual fixture text (`raw.pdf` has exactly one quantitative
sentence: *"TSMC N2 delivers 1.15x logic speed at iso-power versus N3E"* —
unit `"x"`, a pure ratio) and cross-checked it against `expected.json`. That
means:
- §6.4 (unit normalization to GB/s, W, MTr/mm²) has **zero** exercised code
  paths — there is no absolute-unit claim anywhere in the golden fixture.
- §6.7 (entity dedup / alias merge) has **zero** exercised code paths — there
  are exactly two entities, one per vendor+name, no aliases to collide.
- §6.5 (marketing_only tagging) is explicitly admitted as untested by the
  golden case ("exercised by a unit test, not the golden case") — but §12's
  "Files touched" list names `test_golden.py`, `test_injection.py`, and two
  fixture dirs, and **no unit-test file**. The rule this sentence promises
  coverage for has nowhere to live.
Concretely: you could delete or no-op the unit-normalization and
entity-dedup logic today and `uv run pytest` plus `db init` would not notice
— that's the literal test I was asked to apply. Either (a) add
`tests/test_validate.py` to §12 and name what it covers (marketing_only,
unit conversion, dedup-on-collision), or (b) cut the unexercised rules to a
stub/TODO this phase and land them with their own fixture when a document
actually needs them. Shipping untested normalization code because "the
schema lists it" inverts the project's own QA philosophy (CLAUDE.md: the
golden harness is the backbone) — a rule with no assertion behind it is a
liability, not a deliverable.

**2. Prompt caching (§3) is production cost-tuning with no return against this
DoD — cut it, defer it with `pdfplumber`.**
`cache_control` breakpoints and a stable-prefix/volatile-suffix split add
real code surface (deciding what's "stable," getting the cache-key boundary
right, a class of bugs — silently stale cached system prompt — that no test
in this plan can catch) for a code path that is **never exercised**: the
golden test replays a recorded response (§8) and the injection test's live
path is skipped by default (§7). This is solving a cost problem that doesn't
exist yet (there's no production traffic) inside a workstream whose DoD is
"passes offline." §9 already shows the discipline to defer `pdfplumber` for
exactly this reason ("real, just not on the critical path now") — apply the
same discipline here. One line to note it as a fast-follow is fine; wiring
it now is not.

**3. Pushback, preemptively, on the likely fix for open decision C — don't
let "cheap-looking" code invent a shadow schema.**
I read `schema-purist`'s review in this same directory: their ask is an
internal `_attribute_evidence: {field: quote}` side-channel in the proposal
JSON that `validate.py` substring-checks and then strips before building
`Entity`. That's not a validate.py-local fix — it's a new piece of binding
structure that exists nowhere in `schema/extraction_schema_v1.yaml`, which
CLAUDE.md names as the **only** source of truth ("change the schema first;
regenerate the models... never the other way around"). A field that the
prompt must emit, that validate.py depends on, that never appears in the
schema or in `store/models.py`, is a parallel schema living in code —
exactly the kind of drift the "source of truth" rule exists to prevent, and
it will outlive its "temporary, this phase" justification the way these
always do. If entity-attribute grounding needs code enforcement, that's a
`_v2.yaml` schema change with a real citation slot, done properly, not a
quick add to the JSON contract this workstream invents ad hoc. I'd rather
ship §6 exactly as scoped (Known Gap C, explicitly accepted with a revisit
trigger in `resolution.md`) than accept a shadow field that's cheaper today
and expensive forever.

## Risk the other reviewers will miss

**The golden test can go green forever while proving nothing, because
nothing ties `llm_response.json` to the model/prompt pairing it was recorded
against.** §8 makes replay the permanent verification mechanism for
whether the Anthropic call + prompt actually produce a schema-conforming,
grounded extraction. But `config.model.name` lives in `config.toml` (mutable,
per CLAUDE.md) and prompts version forward (`extract_foundry_v2.md`, per
CLAUDE.md) — and nothing in this plan re-validates or invalidates
`llm_response.json` when either changes. Bump the model in config, or cut a
v2 prompt, and `test_golden.py` keeps passing against a hand-authored replay
recorded under the *old* model+prompt — the one test this whole workstream
is designed around (§8 is literally called "KEY DECISION") silently
degrades into a tautology: "does my code correctly parse a fixed JSON blob I
wrote by hand," not "does the extractor work." `uv run pytest` staying green
is precisely the DoD's success signal (§1) — this is the scenario where that
signal becomes meaningless without anyone noticing, because the fixture
never fails, it just stops testing anything real. injection-attacker and
schema-purist are both reasoning about the system as specified now; this
risk only shows up over the following months of prompt/model churn, which is
the lens the other two personas aren't built to apply. Minimal mitigation:
stamp `llm_response.json` (or a sibling manifest) with the prompt sha256 and
model name it was recorded against, and have the golden test assert that
still matches `PromptVersion.load(...).sha256` / `config.model.name` at run
time — a cheap tripwire, not a rebuild of the replay strategy.

## Conditions for approval
- §12 either names the unit-test file covering unit normalization, entity
  dedup, and marketing_only tagging, or those rules are explicitly cut to
  minimal/stub form this phase with a tracked follow-up.
- Prompt caching (§3) dropped from this workstream's scope; deferred
  alongside `pdfplumber` in §9.
- Open decision C resolved without adding proposal-JSON fields that don't
  exist in `schema/extraction_schema_v1.yaml` — either accept the gap
  explicitly (my preference) or route the fix through a schema version bump,
  not a validate.py-local side-channel.
