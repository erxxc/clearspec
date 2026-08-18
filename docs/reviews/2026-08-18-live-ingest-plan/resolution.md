# Resolution — live-ingest (plan)

Merge of the reviewer opinions in this directory, written by the main session.
Rules: agreements highlighted; conflicts named with their cost and **never
averaged**; every named conflict records the human's decision and rationale.

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | conditional | H1/H2/K3 lean on ungrounded `sparsity` self-declaration; B1's true-positive surface is nearly empty; `conflict.offered_value` is the highest-incentive unguarded display target the plan itself introduces. |
| schema-purist | conditional | B1 promises a persisted flag no schema/migration/files-touched entry creates; §2.7 bounds break pydantic+DDL parity; identity fields (`name`/`vendor`/`entity_type`) stay permanently ungrounded while G1 grounds aliases. |
| pragmatist-shipper | conditional | Direct-URL cut and G1/S1/S2 earn their keep; §2.5's table + schema v4 and the H1+H2 double floor are more machinery than the DoD requires — cut conflicts to log-only, defer H2. |
| devils-advocate | (challenge) | All three certified a machine whose only response to detection is a flag on an append-only store with no retraction path; the URL-slug doc_id kills the documented re-ingest remedy (the watchlist cannot watch); log-only conflicts cannot carry `offered_value` without violating validate.py's own never-log-raw-model-text invariant; the corroboration group key (`metric`) is attacker-controlled free text; nobody defended the reader against flag noise. |

## Agreements (all reviewers concur)
- **Overall posture is right**: never-overwrite, conflict-not-auto-resolution,
  hostile suite through the real `validate → persist → analyze → report` chain.
- **Direct-URL scope cut is correct**; HTML discovery → WS-3 ("don't second-guess
  this one" — pragmatist; unchallenged by the others).
- **WS-2a-before-WS-2b sequencing is real**, not ceremony (with the advocate's
  correction that the hostile surface is live *today*, which sharpens rather than
  weakens the ordering).
- **G1 (alias grounding), G3 (collision refusal), S1/S2 (sidecar binding, hash
  re-verify), §2.8 (Cf-stripping), §2.9 (J advisory)** — right-sized, no
  objections from any angle. Locked in as proposed.
- **K1/K2's never-overwrite shape** is endorsed by all three (the conflict-record
  fork below governs what K2 *records*, not whether it overwrites).

## Named conflicts (not averaged)

### Conflict 1 — persisted conflict table vs log-only
- **Positions:** pragmatist wants log-only (`Rejection`-style, no migration);
  injection-attacker wants the table's `offered_value`/`stored_value` bounded and
  display-sanitized; schema-purist endorses the persisted-table reasoning. The
  advocate proved the positions do not compose: `validate.py`'s logging invariant
  ("never raw model text values") means log-only either drops the offered value
  (gutting K2's visible-conflict defense) or logs attacker text through a
  sanitizer weaker than the one §2.8 fixes.
- **Cost of each side:** table = migration 0004 (marginally one `CREATE TABLE`),
  a read-compare-write rewrite of `reconcile_entity` (it currently null-fills via
  a single blind `COALESCE` UPDATE and cannot tell what it discarded), a
  `doc_id` parameter added to its signature, and a net-new display surface that
  must be hardened. Log-only = K1/K2 become a silent-discard policy with an id
  trail; report cannot surface conflicts.
- **Decision (human): durable hardened table.** `offered_value`/`stored_value`
  bounded ≤120 per kind, routed through the hardened sanitizer (ANSI + Unicode
  Cf) at every display site, with a hostile-suite case planting a Trojan-Source
  payload specifically in `offered_value`. The `reconcile_entity` rewrite is
  accepted — it is warranted for exactly that function.
- **Rationale:** the offered value is the only honest record of what a hostile
  document tried to write; a defense that discards it is paperwork, not defense.
- **Accepted by:** operator (erxxc), 2026-08-18.

### Conflict 2 — content bounds: DDL parity vs trim
- **Positions:** schema-purist wants every bound mirrored as SQLite `CHECK`
  constraints (repo parity rule; DDL is the durable layer); pragmatist wants
  bounds trimmed to `doc_id`/`url`/`title` (the fields the fetcher changes).
  The advocate showed applying both yields the parity principle in the two
  places it matters least.
- **Cost of each side:** full+DDL = larger migration and model regen; trim =
  the durable layer stays unbounded on every adversary-written string, under
  exposure that is live today (advocate §2: the hostile PDF already arrives
  through `ingest_file`).
- **Decision (human): full §2.7 bounds WITH mirrored CHECK constraints in
  migration 0004, including `conflict.offered_value`/`stored_value`.**
- **Rationale:** the pragmatist's "independent gap, fix later" framing fails
  once the exposure is acknowledged as current; 0004 ships anyway (Conflict 1),
  so the marginal cost is small.
- **Accepted by:** operator (erxxc), 2026-08-18.

### Conflict 3 — H2 (all-tier-3 confidence cap) now vs deferred
- **Positions:** plan proposed H2 now; pragmatist wants it deferred with a named
  trigger; the advocate's flag-noise finding (§7) weighs on pragmatist's side.
- **Cost of each side:** now = a second confidence axis no realistic watchlist
  exercises yet, plus one more flag against the reader; defer = an all-tier-3
  two-publisher agreement reads `corroborated/high` until the trigger fires.
- **Decision (human): defer H2.** Trigger (ROADMAP): *the watchlist carries ≥2
  distinct tier-3 publishers for one metric.*
- **Rationale:** H1 already demotes the single-publisher case; the residual
  window is narrow and the reader-noise budget is the scarcer resource.
- **Accepted by:** operator (erxxc), 2026-08-18.

### Conflict 4 — B1 (unbound-baseline check): cut vs strengthen
- **Positions:** the plan proposed flag-not-drop; injection-attacker showed the
  check almost never fires on the realistic attack (competitors are *named* in
  hostile comparisons — that is the point of them) and at best defends against
  dangling naming; schema-purist showed the promised persisted flag has no
  schema home and would force a claim-row column either way.
- **Cost of each side:** strengthen (proximity window + column) = heuristic
  false positives, a schema column, and the realistic misattributed-measurement
  attack still passes; cut = no baseline-binding check at all.
- **Decision (human): cut B1; keep B2** (content bound on `cmp_baseline_entity`).
- **Rationale:** a check that cannot catch its named attack buys false coverage
  at schema cost. Baseline poisoning is instead answered by provenance (per-doc
  claims), H1, conflict records, and — decisively — the retraction primitive
  below. Recorded as an accepted residual risk with a trigger.
- **Accepted by:** operator (erxxc), 2026-08-18.

## Devil's-advocate challenge

### Challenge 1 — no retraction path; URL-slug doc_id makes revisions permanently unextractable
- **Disposition: adopted — the largest outcome of this gate.** WS-2a gains the
  **extraction-artifact + refold** architecture: `run_extract` persists each
  document's validated extraction result as a content-addressed artifact beside
  its raw blob; the SQLite DB becomes a deterministic, rebuildable fold over
  retained artifacts (replaying the existing `persist_extraction`, unchanged).
  `forget <doc_id>` (quarantine artifact + sidecar, refold) delivers retraction;
  revision supersession (latest artifact per doc_id wins on refold) makes the
  watchlist able to watch — both offline, no model calls. This retires the
  WS-1-deferred "same-doc_id supersession" item as a side effect.
- **Decision (human):** artifact + refold. **Accepted by:** operator (erxxc),
  2026-08-18.

### Challenge 2 — the exposure is live today, not post-fetch
- **Disposition: adopted.** The sparsity-grounding hole (injection F1) is
  treated as a **bug on `main`, fixed in a standalone commit before WS-2a**: a
  versioned sparse-vocabulary check over the claim's own `quote_span`
  force-sets `sparsity=true` (ungrounded evidence never resolves toward the
  non-suspect direction — the same fail-safe direction as `location_type`).
  The vendor-casing dedup asymmetry (schema-purist's risk: one document's
  `"TSMC"`/`"Tsmc"` yields two entities today) is fixed in the same commit
  (case-folded vendor in the dedup key) with tests. Plan text for K3/H1 is
  scope-limited honestly: defenses against sloppy or lazy-hostile vendors;
  full extractor-steering resistance rests on the injection suite plus the
  vocabulary check, not on self-declaration.

### Challenge 3 — the corroboration group key is attacker-controlled free text; H1's publisher is unnormalized
- **Disposition: partially adopted.** Ships now: case/whitespace normalization
  of `metric`, `unit`, and `publisher` for grouping and for H1's floor, plus an
  advisory `possible_split_metric` flag when two singleton groups on one entity
  carry near-identical metric strings (mirrors J). H1 is re-documented honestly
  as a **publisher/operator-diversity floor**, not a hostile-input defense.
  Deferred with trigger: a controlled metric vocabulary / fuzzy join — trigger:
  *first real corpus shows split groups that normalization does not close.*

### Challenge 4 — nobody defended the reader
- **Disposition: adopted as acceptance criteria.** WS-2a's definition of done
  gains (a) an **honest-corpus regression**: the acceptance golden's six
  verdicts and flag lists must not change except by deliberate, written-in
  diffs; (b) a **flag budget**: no honest assessment gains more than one new
  flag from this workstream. If a floor cannot meet the budget, it lands behind
  config rather than as an unconditional default.

## Residual risks accepted
- **Misattributed-measurement baseline poisoning** (B1 cut) — a hostile doc
  attaching a fabricated number to a genuinely-named competitor is not detected
  at validate; accepted because provenance + H1 + conflict records + `forget`
  bound the damage. Revisit: a hostile-suite case or live corpus demonstrates it.
- **Shell-publisher collusion passes H1** — H1 is operator-diversity; accepted
  because publishers come from operator config in WS-2b's direct-URL scope.
  Revisit: WS-3 discovery (publisher no longer operator-typed) or the H2 trigger.
- **Deliberate metric-string evasion beyond normalization** — advisory flag
  only. Revisit: per Challenge 3 trigger.
- **Identity citation slots** (`name`/`vendor`/`entity_type` have no
  `attribute_citations` home) — mitigated by presence-grounding (name+vendor
  must appear in source text, fail-soft drop) landing in WS-2a; full citation
  slots deferred as a named CLAUDE.md line. Revisit: schema v5.
- **H1's empirical basis is one two-publisher data point** (the acceptance
  golden) — accepted; the honest-corpus regression is the guard.

## Outcome
**proceed-with-conditions** — WS-2 proceeds in this order:
1. **Standalone fix on `main` (pre-WS-2a):** sparsity quote-span vocabulary
   grounding (fail toward suspect) + vendor case-fold dedup, with tests.
2. **WS-2a (trust hardening, no network):** artifact + refold (`forget`,
   `db rebuild`, supersession); hardened conflict table (bounded, sanitized,
   Trojan-cased) via schema v4 + migration 0004 with full CHECK-mirrored
   bounds; G1/G3; H1 with normalized publisher; group-key normalization +
   `possible_split_metric`; name/vendor presence-grounding; S1/S2; §2.8
   Cf-stripping; J advisory; hostile suite + honest-corpus regression + flag
   budget. H2, B1, controlled vocabulary, identity citation slots: deferred
   with the named triggers above.
3. **WS-2b (fetcher):** as §1 of the plan, unchanged (direct-URL, HTTPS-only
   per-hop, size/redirect caps, magic bytes, rate limits, URL-slug doc_id —
   now safe because supersession exists).
Precommit gate to follow on the WS-2a diff, per convention.
