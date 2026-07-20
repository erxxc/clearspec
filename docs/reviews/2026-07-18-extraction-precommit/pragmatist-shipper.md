# pragmatist-shipper — GATE 2 (pre-commit diff review)

**Verdict: CONDITIONAL** — approve once the untested normalization/dedup-adjacent
branches below are either deleted or covered by a one-line test, and the
always-discarded `location_type` prompt instruction is either cut or actually
wired through. None of this touches architecture; it's all mechanical, <30
minutes of work, and the suite stays green either way.

## Context I checked first
The DoD is met on paper: offline `uv run pytest` is 21 passed/2 skipped, and
`--run-live` is claimed at 23 passed. Scope discipline held — `store/` was only
touched for the authorized v2 bump (schema/models/migration/db.py), `ingest/`,
`cli.py`, `analyze/`, `config.py` are untouched. Two of my own GATE-1
conditions landed clean: prompt caching is gone (no trace in `base.py` or
`pyproject.toml`), and Decision C shipped as a real schema field
(`entity.attribute_citations` in `schema/extraction_schema_v2.yaml` →
`store/models.py` → migration `0002`), not the shadow-schema side-channel I
blocked at GATE-1. Good — that's the outcome I asked for.

My third GATE-1 condition — "no untested normalization rules" — only landed
**partially**. That's finding 1.

## Findings (my angle only — shipping cost, not security)

### 1. Untested normalization/pruning branches survive despite my own GATE-1 condition
`src/semianalyst/extract/validate.py`:
- `RATIO_UNITS = {"x", "X", "×", "%"}` (line 59) — the prompt only ever asks
  the model for `"x"` or `"%"` (`prompts/extract_foundry_v1.md`, `unit` field
  description: `"<x | % | GB/s | W | MTr/mm2 | mm2 | ...>"`). `"X"` and `"×"`
  are speculative extra tokens nothing produces and nothing in
  `tests/test_validate.py` exercises.
- `_UNIT_CONV` (lines 62-65) — only `TB/s → GB/s` is exercised
  (`test_unit_normalization_to_canonical`). `kW→W`, `mW→W`, and `MB/s→GB/s`
  are untested normalization rules — exactly what Conflict 3's resolution
  ("add coverage, don't cut or ship untested") committed to closing.
- The stray-citation pruning branch, `if path not in _VALID_PATHS: pop()`
  (line 176) — no test constructs a proposal whose `attribute_citations` map
  contains a path outside `_VALID_PATHS` (e.g. a citation attached to the
  exempt `node.hvm_date_actual`, or a typo'd path). It's live code with zero
  coverage.

Fix is cheap either direction: delete the untested table entries/tokens (the
golden + injection fixtures don't need them), or add one assertion per branch
to `test_validate.py`. Either way the suite stays green — this is exactly the
"what could be deleted and keep the suite green" question in scope for this
gate.

### 2. Two branches in the DoD-mandatory offline half are dead code
`src/semianalyst/extract/base.py`:
- `_parse_proposal`'s fenced/prose JSON fallback (lines 88-93, the
  `text.find("{")`/`text.rfind("}")` rescue path).
- `AnthropicModelClient.complete`'s refusal guard, `if stop_reason ==
  "refusal"` (lines 62-63).

Both are reachable only through a real Anthropic response, i.e. only under
`--run-live`. Nothing in the plain `uv run pytest` run — the half of the DoD
that must pass with no network and no key — touches either branch. `ModelClient`
is a `Protocol` built precisely so a fake client can be substituted offline
(`ReplayModelClient` already does this for `complete()`'s return value), but no
test ever constructs a fake `client` object with `stop_reason="refusal"` or
feeds `_parse_proposal` a fenced string directly. This is defensive code for a
failure mode nobody has observed the model actually produce yet. Either write
the two trivial offline tests the `Protocol` seam was built to support, or cut
the speculative-generality branches until the live gate proves the model needs
them.

### 3. The model is paying to produce a value that is unconditionally thrown away
`prompts/extract_foundry_v1.md` instructs the model to emit `location_type`
(`body|table|figure|footnote`) for **every** claim citation and **every**
entity `attribute_citations` entry ("`location_type` is your best guess; the
caller may override it"). But `validate.py::_force_unknown` is called
unconditionally on every surviving citation (claim path: line 220; entity path:
line 179) — there is no code path, today, where the model's guess survives
into the result. That's real per-call cost (extra output tokens on every
citation, on every `--run-live` invocation, forever) buying literally nothing,
plus it leaves `body/table/figure/footnote` as currently-unreachable members
of `LocationType`/the `cite_location_type` CHECK constraint. This is fine as a
*documented, temporary* state (the v2 schema comment says so — "real locations
assigned once layout-aware extraction lands") but the prompt should say so too,
or better: stop asking the model to spend tokens guessing something we know in
advance we're discarding. Five-minute prompt edit, zero test impact.

## Risk another reviewer's lens won't catch
The two tests the whole ENFORCE posture leans on — `test_golden_live` and
`test_injection_live_model_does_not_leak_or_obey` — call
`self.client.messages.create(model=..., max_tokens=8000, system=..., messages=...)`
with **no `temperature` parameter** (`base.py`, `AnthropicModelClient.complete`).
The Messages API defaults to `temperature=1`. `test_golden_live` does an exact
`model_dump(mode="json") == expected.json` comparison against free-running
model output. That's not a correctness or security gap — it's a shipping-cost
gap: the mandatory CI anchor (`uv run pytest --run-live`) can flake on wording
alone even when the code under test is perfectly correct, and every flake/retry
in CI is a real Anthropic API charge, not just red-CI noise. Nobody else is
positioned to flag this because it's not a grounding or auth issue — it's the
operational bill for the posture Q0 chose. Pin `temperature=0` (or as close to
deterministic as the API allows) on the live client before this becomes a
CI cost/flake problem instead of a design conversation.

## What I am NOT blocking on
The `ModelClient` seam, replay-with-provenance-stamp, per-item shape
validation (one bad field drops one claim, not the whole doc), and the v2
schema-bump-not-shadow-field resolution are all sound and outside my angle to
relitigate — GATE-1 settled those, and this diff implements them faithfully.
