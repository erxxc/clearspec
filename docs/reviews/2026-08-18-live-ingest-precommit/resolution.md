# Resolution — live-ingest WS-2a (precommit)

Merge of the reviewer opinions in this directory, written by the main session.
Rules: agreements highlighted; conflicts named with their cost and **never
averaged**; every named conflict records the human's decision and rationale.
`workstream.diff` is the diff AS REVIEWED (@ d6adb94); the fixes this resolution
mandates were applied AFTER the gate in the immediately following commit —
recorded per item below.

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | conditional | The artifact fold is an unauthenticated second write path bypassing grounding/G1/G3/sparsity; casefold-only normalization is one homoglyph away from defeating G3+H1+J at once; verbatim quote_span display is an unpinned open item. |
| schema-purist | conditional | Migration 0004 carry-forward can crash on pre-v4 over-bound rows (undocumented); serialized-JSON CHECKs reject honest escape-inflated data; the 16-alias bound is never enforced at its true accumulation point; three drifting "case-folded" implementations. |
| pragmatist-shipper | conditional | Faithful, non-gold-plated build of the resolution; consolidate the five scrub/strip re-implementations; trim four redundant bound tests. |
| devils-advocate | (challenge) | The fold replays a DIFFERENT ORDER than the incremental path, silently re-deciding every first-writer race; forget can silently fail to retract; the reviewers' asks trade against each other in three places; the honest-corpus guard is structurally blind to every proposed fix. |

## Agreements (all reviewers concur)
- The PDF-injection surface as shipped (grounding, G1/G3, presence-grounding,
  Cf display stripping, bounded conflict values, `test_trojan_display` through
  the real reconcile → report path) is well built and correctly tested.
- The implementation is faithful to the plan-gate resolution — no gold-plating;
  every mechanism traces to a named decision (pragmatist, unchallenged).
- Schema v4 ↔ models ↔ migration parity holds for scalar fields and the
  conflict record, including the late chip-attribute fix (schema-purist).

## Named conflicts (not averaged)

### Conflict 1 — fold trust: authenticate, bind, or re-validate
- **Positions:** injection wanted at minimum a sidecar/doc_id binding check on
  the fold (framed as authentication); the orchestrator had proposed the strong
  form (fold-time re-validation of grounding against retained blobs); the
  advocate killed the strong form (the fold's output would become a function of
  the pypdf version — a library bump silently drops grounded claims on the next
  `forget`; the fold must stay a pure function of retained JSON) and showed the
  binding closes no class against a `data/raw/` writer (who can write blob +
  sidecar and ground anything through the legitimate path).
- **Cost of each side:** re-validation = non-determinism across library
  versions; binding-only = one extra file for the attacker; nothing = the
  documented fold claims more than it holds.
- **Decision (human, 2026-08-18): sidecar binding as a documented CONSISTENCY
  check — never called authentication — plus `data/raw/` write access named as
  the trust boundary in CLAUDE.md (a MAC keyed outside it is WS-2b+ scope), plus
  the advocate's `forget` post-condition (fail loud if the doc_id survives the
  refold — closes silent non-retraction AND artifact resurrection structurally).**
- **Applied:** `sidecar_doc_id` binding in `run_rebuild`; post-condition in
  `forget`; `test_orphaned_artifact_never_folds`,
  `test_forget_postcondition_fails_loud`; CLAUDE.md trust-boundary text.

### Conflict 2 — fold order (the advocate's own finding, adjudicated as a fork)
- **Positions:** ship as-is with a documented caveat vs `(ingest_date, doc_id)`
  canonical (re-decides late-arrival races by design) vs `_extracted_at` (the
  actual incremental chronology).
- **Decision (human): `_extracted_at`.** Makes "rebuild reproduces incremental"
  true by construction; the attacker-writable-timestamp residual is bounded by
  the Conflict-1 trust boundary and named in CLAUDE.md.
- **Applied:** fold key changed; the two false docstrings fixed; adversarial
  determinism test added (`test_fold_order_matches_incremental_history`, sha
  order deliberately opposing ingest_date order).

### Conflict 3 — JSON bounds vs the honest path (schema-purist F2/F3, advocate §5)
- **Positions:** as-shipped CHECKs (reject honest escape-inflated data; the
  alias flood guard converts a hostile flood into an honest-path outage) vs
  resize + enforce the item bound at accumulation.
- **Decision (human): the invariant rule is written down — a serialized-JSON
  CHECK must be ≥ the worst-case serialization of the max ACCUMULATED
  pydantic-legal value; the real invariants live at the model layer and, for
  the cross-document alias union, at reconcile.** CHECKs resized (aliases
  8000, caveats 50000); per-entity 16-alias ceiling enforced at merge as
  **refuse-the-alias-with-conflict (new `alias_overflow` kind), never
  reject-the-document**; folded membership fixes the case-variant inflation.
  Migration 0004 amended IN-BRANCH: it is treated as unreleased until the
  WS-2a PR merges — the never-edit-applied-migrations rule binds from merge
  (dogfood/test stores are disposable and were reset).
- **Applied:** migration + schema v4 + `ConflictKind.alias_overflow` + tests
  (`test_alias_union_ceiling_refuses_alias_not_document`,
  `test_escaped_caveats_persist_on_honest_path`).

### Conflict 4 — consolidation vs security semantics (pragmatist vs injection/advocate)
- **Positions:** pragmatist wanted one shared scrub helper across five sites
  and four bound tests deleted; the advocate showed a shared *function* invites
  collapsing the model layer's REJECT into scrub (a regression in cleanup's
  clothes), that `cli._ansi_safe` must stay display-edge per CLAUDE.md, and
  that deleting per-bound regression tests in the same gate that CHANGES those
  bounds is backwards.
- **Decision (human): share the character-class CONSTANT only
  (`textnorm.CTRL_CLASS`); reject and scrub stay visibly distinct;
  `cli._ansi_safe` untouched with a why-comment; the four bound tests are KEPT
  (pragmatist's deletion rejected — wrong order of operations).**
- **Applied:** `textnorm.py`; all four ingestion-side sites reference the
  constant; cli comment added.

### Conflict 5 — the fold() unification is a behavior change, not a refactor
- **Positions:** schema-purist wanted the three drifting implementations
  unified; the advocate showed there were FOUR idioms, that unification changes
  refusal behavior in both directions, and that the honest-corpus guard is
  structurally blind to it — so it must land WITH the two honest fixtures the
  guard lacks.
- **Decision (human): shared `textnorm.fold` (collapse+strip+casefold)
  everywhere a "same value?" question is asked — validate dedup key,
  `_grounded_ci` casefold, reconcile identity compare and alias sets, analyze
  keys — shipped with the two honest fixtures.**
- **Applied:** `textnorm.fold` wired through all layers;
  `test_honest_shared_surface_form_records_the_cost` (pins G3's acknowledged
  honest-path cost: one conflict, nothing dropped) and
  `test_honest_casing_whitespace_variants_no_spurious_conflict` (pins zero
  conflict noise on PDF whitespace/casing variants).

## Devil's-advocate challenge
- **Question raised:** the shared premise (the fold faithfully reproduces the
  store) was false; surfacing-as-response, grounding-as-trust, and the
  guard's blindness were unexamined by all three reviewers.
- **Disposition:** fold order fixed and adversarially tested (Conflict 2);
  retraction post-condition added (Conflict 1); **grounding-is-fidelity-not-
  trust** clause added to CLAUDE.md's core invariant; the honest-corpus guard's
  blindness addressed with the two new fixtures and by no longer citing the
  flag budget as coverage (it is a fixture regression, recorded as such).

## Residual risks accepted
- **`data/raw/` write access is the trust boundary** — sidecar binding is
  consistency, not authentication; `_extracted_at` in an artifact is
  attacker-writable fold-ordering text. Revisit: WS-2b+ (a MAC keyed outside
  the directory).
- **Homoglyph/confusable folding deferred** (injection F2) — a lookalike swap
  defeats G3/H1/J together. The honest fixtures it needs now exist. Trigger: a
  live corpus shows a homoglyph case; lands inside `textnorm.fold`.
- **`quote_span`/`stated_caveats` stored verbatim, display OPEN** — named in
  CLAUDE.md; any future evidence-display feature must route through
  `_ansi_safe`.
- **Migration 0004 carry-forward fails loud on pre-v4 over-bound rows** —
  deliberate (never truncate stored evidence); triage queries documented in the
  migration header.
- **Shell-publisher collusion passes H1; tampered sidecar `file_sha256` field**
  — carried forward from the plan gate, unchanged.

## Outcome
**proceed-with-conditions — all conditions APPLIED before commit** (the fix
commit immediately follows the reviewed ref d6adb94; suite after fixes: offline
119 passed / 3 skipped, live 122 passed / 0 skipped, including the adversarial
fold-order determinism case). WS-2a ships; WS-2b (fetcher) is next, on the
hardened, retractable, order-coherent store.
