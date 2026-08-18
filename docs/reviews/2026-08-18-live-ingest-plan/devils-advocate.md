# devils-advocate — attack on the WS-2 gate consensus (2026-08-18)

Target: the three reviews, not the plan. Read in order:
`injection-attacker.md`, `schema-purist.md`, `pragmatist-shipper.md` (all
CONDITIONAL). Grounded against shipped code: `analyze/corroborate.py`,
`extract/validate.py`, `extract/pipeline.py`, `ingest/{base,pipeline}.py`,
`store/db.py`, `cli.py`, `config.toml`, and the acceptance golden
`tests/fixtures/analyze/tsmc_n2_corroboration/expected_analysis.json`.

Three CONDITIONALs read like a healthy gate. They are not independent: they share
two premises neither of them tested, and their conditions do not compose — applied
together they produce a worse design than any one reviewer's pure position.

---

## 1. The shared assumption nobody checked: **that surfacing is a response**

Every mechanism this plan adds is additive and non-destructive:

| decision | what happens on detection |
|---|---|
| K1 | never overwrite — bad first value stays |
| K2 | later differing value dropped, conflict *recorded* |
| G3 | alias not unioned, conflict *recorded* |
| H1/H2 | status demoted / confidence capped — claims stay |
| B1 | `unbound_baseline` *flag*, explicitly flag-not-drop |
| J | advisory *flag*, explicitly not fail-loud |
| S1/S2 | loud *error*, blob/sidecar untouched |
| revision | `ExtractReport.revised` — surfaced, not extracted |

I checked for a remediation primitive anywhere in the shipped library: there is
none. No `DELETE`, no purge, no supersede, no retract — `store/db.py` is
insert/update-only, and the CLI is five commands (`db-init`, `ingest`,
`ingest-file`, `extract`, `report`), none of which removes anything. The store is
strictly append-only.

So the terminal state of every defense in this plan is: *the operator now knows
the store is poisoned, and has no command that fixes it.* All three reviewers
argued about what to write (injection-attacker: ground more fields;
schema-purist: name more columns; pragmatist: write less of both). None asked what
happens to what is already written once it is known to be wrong.

**The scenario where all three are wrong at once.** A tier-3 doc is fetched first
for some entity. It plants `vendor`/`name` (ungrounded — schema-purist's finding 3
is real: `GROUNDABLE` in `validate.py:92-97` covers `node.*`/`chip.*` only) and
null-fills attributes. Later honest documents arrive. Every defense fires exactly
as designed: K1 refuses to overwrite, K2 records a conflict, G3 refuses the alias
graft, J flags the residue, H1 demotes the group. The plan's own success criteria
are all met — and the entity is permanently wrong, with paperwork. The reviewers
each certified their piece of a machine whose output is a well-documented
falsehood that cannot be corrected.

**Ask for the human:** WS-2 ships at least one remediation primitive
(`forget <doc_id>` — delete the document's claims and re-derive entities from
survivors) *or* CLAUDE.md gains an explicit new Class A line, "no retraction path:
a poisoned document is permanent," with a named trigger. Choosing "flag it" as the
universal resolution is defensible; doing so without noticing there is no
resolution *after* the flag is not.

## 2. The shared false frame: the exposure is not in the future

All three accepted §0's sequencing rationale — "no hostile byte should be
fetchable before the store can survive it" (pragmatist explicitly graded it "real,
but only barely" and moved on). But CLAUDE.md's own WS-1 gate correction says the
hostile surface is *already live*: `run_extract` calls the real model on
operator-fed, third-party-authored vendor PDFs today. Hostile-derived model output
already reaches `persist_extraction`, `reconcile_entity`, and `report`.

This false frame cuts both ways and corrupts both sides of the gate:

- Pragmatist defers H2 and the conflict table as "speculative generality against a
  threat direct-URL WS-2b can't yet produce." But the threat is not produced by
  the fetcher; it is produced by the PDF, and the PDF arrives today. What he is
  actually proposing is *leaving undone, under live exposure*, not *deferring
  until exposure*.
- Injection-attacker's Finding 1 (ungrounded `conditions.sparsity`) is correct and
  is understated by the same frame: it is not a WS-2 design flaw, it is a **live
  bug in `main`** — `test_injection_*` does not cover it, `GROUNDABLE` does not
  include it, and the suspect-exclusion logic in `corroborate.py:80-81` already
  depends on it in production.

Neither the plan nor any reviewer says "this is broken *now*." The gate should not
let a design document absorb a live defect into a future workstream's scope.

## 3. The blind spot none of the three covered: **time**

All three reviewed the plan as if each document arrives once. WS-2b's only
material capability over the already-shipped `ingest_file` — under the direct-URL
scope cut all three endorsed — is *repeated, automated fetching of the same URLs*.
That axis is unexamined, and it is broken by the plan's own new decision.

**The watchlist cannot watch.** §1 sets `doc_id` = deterministic slug of the
normalized URL. `extract/pipeline.py:83-93` classifies same-doc_id + changed bytes
as `revised` — surfaced, never extracted — with the note:

> "same-doc_id re-extraction is not supported in WS-1 — **re-ingest under a new
> doc_id** to extract the revision."

That escape hatch was written for the operator path, where a human chooses the
doc_id. Under a URL-derived doc_id the operator *cannot* choose one. Therefore:
**for every watched URL, the first fetch is permanent and every subsequent
revision is unextractable, forever.** The plan's §1 says revisions are "surfaced
downstream by `run_extract` exactly as today" — but "exactly as today" plus a
derived doc_id equals a dead end, not a deferral. The one decision the plan defers
(supersession) is made undeferrable by a decision the plan newly makes (URL-slug
doc_id), and no reviewer traced the two together.

Consequences nobody costed:

- **The workaround poisons analyze.** The operator's only remedy is to mutate the
  URL (`?v=2`) to change the slug. That inserts a document and its own revision as
  two independent documents. `corroborate.py:144` groups on
  `(entity_id, metric, is_relative, baseline_entity, unit)` — nothing about
  documents — so a vendor and its own correction land in one group. H1 happens to
  catch the corroboration case (same publisher → `weakly_corroborated`), by
  accident, not by design; the plan never names "a document and its own revision"
  as a corroboration source and the 11-case hostile suite has no case for it.
  Nothing catches the **contradiction** case: a vendor correcting its own number
  produces a permanent `contradicted` verdict with `favored_tier` = its own tier —
  the divergence engine reporting a single source arguing with itself as
  cross-source divergence.
- **The conflict table fills with self-conflicts.** Doc-vs-its-own-revision
  identity/attribute differences are indistinguishable from hostile ones in the
  §2.5 record shape (`stored_value` / `offered_value` / offender `doc_id`). That
  simultaneously inflates the table pragmatist wants cut and degrades the signal
  injection-attacker wants surfaced.
- **The scope cut looks different in this light.** All three endorsed direct-URL-
  only ("don't second-guess this one"). But direct-URL-only means the operator
  still hand-finds every PDF URL — the same curation `ingest_file` already
  requires. Strip out re-fetch (broken, above) and WS-2b's residual value over the
  shipped path is *batching `curl`*. The largest slice in the project's history
  (WS-2a) is being justified as the safety precondition for that. This does not
  make the scope cut wrong; it makes the WS-2a/WS-2b cost ratio the human should
  actually be shown, and no reviewer computed it.

## 4. The sharpest unresolved conflict: the conflict record does not compose

This is the one the human must adjudicate, and it is a genuine three-way
collision that averaging destroys.

- **pragmatist (F1):** cut §2.5 to log-only, "`validate.py` already has a working,
  cheaper pattern for this (`Rejection`: kind + sanitized target + reason)."
- **injection-attacker (F3):** `offered_value`/`stored_value` are the highest-
  incentive Trojan-Source payload in the plan; bound them tightly and route them
  through `_ansi_safe` + Cf-stripping.
- **schema-purist:** endorses the persisted-table reasoning as correct.

They do not compose, for a reason none of them states. `extract/validate.py`'s
module docstring is explicit:

> "Rejections carry only a kind, a model-supplied identifier/path (sanitized
> before logging), and a fixed reason string — **never raw model text values,
> which under injection could carry a hostile string.**"

And `_safe()` (`validate.py:102-104`) strips `[\x00-\x1f\x7f]` and truncates to
120 — it does *not* strip Unicode Cf, i.e. it has precisely the bidi/zero-width
gap §2.8 exists to close, on a stream (stderr) that `cli._ansi_safe` never
touches.

So the "cheaper existing pattern" pragmatist points to is a pattern *defined by
not carrying the value*. Log-only therefore lands in one of two places:

1. **Log the id only** — then `offered_value` is gone, and K2's entire defense
   ("the honest value's arrival becomes a *visible conflict*, not a silent loss")
   is false. K2 becomes: silently drop the later value, log an id. Pragmatist
   lists K1/K2 as in "the direct causal path of a hostile byte reaching the store"
   and wants them kept — while cutting the only mechanism that makes them a
   defense rather than a data-loss policy.
2. **Log the value** — then the plan writes attacker-controlled text to a terminal
   stream through a sanitizer that is weaker than the one §2.8 is fixing, i.e.
   pragmatist's cheap option lands injection-attacker's Finding 3 in its *worst*
   form and outside every call site §2.8 enumerates.

**There is no averaged version.** Either the offered value is durable and
displayed through the hardened path (table + per-kind bound + `_ansi_safe` +
Cf-strip — injection-attacker's version at pragmatist's cost), or K1/K2 must be
re-described honestly in the plan text as "later value discarded, id logged."
Do not let the resolution say "log-only for now, sanitize later."

Two facts that shift the cost side of this trade, which the gate should have in
front of it:

- **The migration exists regardless.** Schema-purist's Finding 1 is right that
  B1's `unbound_baseline` needs a stored per-claim boolean (analyze cannot
  re-derive it — `source_text` is retained nowhere, and `get_claims_for_analysis`
  (`db.py:274-292`) selects 11 columns with no text among them). If B1 ships,
  `0004` ships. So pragmatist's "conflict-logging does not need a migration" is
  true and irrelevant: the marginal cost of the conflict table is one
  `CREATE TABLE`, not a migration. His #1 cost estimate and schema-purist's #1
  cancel, and neither reviewer could see it from inside their own review.
- **The write path costs more than §4 admits, in pragmatist's favor.**
  `reconcile_entity(conn, ent)` (`db.py:234-263`) takes no `doc_id` — the §2.5
  record's "offender doc_id" requires a signature change §4 does not list, in a
  function §4 calls "unchanged contract" at the `persist.py` layer. Worse, the
  null-fill is a single `UPDATE ... COALESCE(col, ?)` across ~11 columns: it
  cannot tell whether the newcomer's value was taken or discarded, and never
  compares values. Writing K2 conflicts requires replacing that statement with a
  read-compare-write loop. That is a rewrite of the most security-sensitive
  function in the store, not "conflict writes."

## 5. Second collision: §2.7 bounds — applying both conditions is worse than either

- schema-purist: mirror the bounds into SQLite `CHECK` constraints (DDL/pydantic
  parity is a CLAUDE.md rule; the DDL is the durable layer).
- pragmatist: trim §2.7 to `doc_id`/`url` — the fields WS-2b actually changes.

Apply both and you get `CHECK` constraints on two fields and pydantic-only (or
nothing) on the rest: the parity principle instantiated in the two places it
matters least, abandoned everywhere an adversary writes. And if pragmatist's
log-only wins in §4, schema-purist's DDL-parity argument has no column to attach
to for the highest-risk string in the plan. These are not independent conditions
and must not be merged as if they were.

## 6. What all three missed on the attack surface: the corroboration **group key**
   is attacker-controlled free text

Injection-attacker found that H1/H2/K3 rest on an ungrounded `sparsity` boolean.
True, and there is a second, independent path to the same place that no one named.

`corroborate.py:144` groups on `(entity_id, metric, is_relative, baseline_entity,
unit)`. `metric` is model-proposed free text. It is never grounded — `GROUNDABLE`
covers `node.*`/`chip.*` only, and a claim's grounding requirement is on
`citation.quote_span` (tied to `value`), not on `metric`. §2.7 bounds `metric`'s
*length* (≤120); nothing bounds its *content or vocabulary*.

Therefore an adversary chooses which group its claim lands in:

- **Evasion.** A hostile claim that would contradict an honest one only has to
  differ by one character in `metric` (`sram_density` vs `sram_bitcell_density`)
  or in `unit` spelling. Result: two singletons, two `uncorroborated`, no
  `contradicted`, no `favored_tier`, no divergence signal at all. The entire
  divergence engine is opt-in for the adversary — and this defeats K3 without
  touching the sparsity signal, so injection-attacker's fix (a) does not close it.
- **Manufacture.** Matching the honest string exactly is equally cheap; H1 raises
  that bar to two publishers, which §5 already concedes shell publishers clear.

The plan cites agentlens #2 ("a shared near-constant key must never merge distinct
records", plus the oversized-bucket heuristic) and applies it to *aliases* (G3).
The mirror-image failure — a key so narrow it never merges records that should
compare — is the one the corroboration engine actually has, and it is the key the
whole §2.3 debate is conducted on top of. Schema-purist came closest
(vendor-casing) but stayed on entity identity, not the claim group key.

**And H1's own new key has the same defect.** H1 compares `publisher` strings.
`publisher` is unnormalized free text from the sidecar; §1 says it comes from the
operator's watchlist entry. Two consequences the plan sells past:

1. `"TSMC"` vs `"TSMC "` vs `"tsmc"` are three publishers. The plan mandates
   case-insensitive comparison for aliases (G3) and says nothing for H1 — which is
   schema-purist's casing finding, one layer over, on the plan's own new machinery.
2. Because `publisher` comes from trusted config, H1 is really an
   *operator-diversity* floor, not a source-diversity floor. An operator who adds
   three URLs from one vendor's three microsites, typing three publisher names,
   passes H1 while nothing independent has corroborated anything. H1 is a
   trusted-input floor being presented as a hostile-input defense.

For the record, I verified H1 does *not* break the acceptance golden: the only
`corroborated` group there (`logic_speed`) has publishers "Hot Chips" and "TSMC".
That is one two-publisher data point, and it is the entire empirical basis for a
floor that governs the tool's headline verdict.

## 7. The question the group avoided: what does `report` look like on honest data?

Not one of the three reviewers asked about false positives, and the plan states no
acceptance criterion for them. Count what this plan adds to the operator's only
UI (`cli.py:112-128`, which prints flags inline per assessment): `single_publisher`,
`vendor_only`, `unbound_baseline`, `possible_slug_collision`, `identity_conflict`,
plus per-entity conflict counts — five new flag types and a new counter, on top of
`sparsity` / `marketing_only` / `unresolved_baseline` / `single_source`.

Now count what it takes away. `corroborated` already requires ≥2 non-suspect
members sharing an **exact free-text `metric` string**, the same unit, the same
`is_relative`, the same baseline, within 10%. H1 adds ≥2 distinct publishers. In
the acceptance golden — three hand-built sources, maximally favourable — exactly
**one of six** assessments reaches `corroborated`. On a direct-URL watchlist of
three foundry sources whose metric strings are written by a language model per
document, the realistic rate is lower.

So the plan's net effect on the honest path is: the one verdict a human wants to
see gets rarer, and every run gets louder. That is the third "all three wrong at
once" scenario, in product terms: the tool converges on a flag generator that
never says `corroborated`, the human learns to skim flags, and at that moment
*every* defense in this plan that terminates in "flag it" — B1, J, H1, H2, K2,
the conflict counts — has an effective value of zero. Injection-attacker's asks
add flags; schema-purist's asks add fields; pragmatist's asks reduce build cost,
not report noise. Nobody at this gate defended the reader, who is the only
component that actually resolves anything (see §1).

**Ask:** require the hostile suite to be paired with an **honest-corpus
regression** — the existing golden's six verdicts and flag lists must not change
except where a §2.3 decision deliberately changes them, and that change must be
written into the golden as an approved diff — plus a stated flag budget (no honest
assessment gains more than one new flag). If H1/H2 cannot meet it, they land
behind a config threshold rather than as unconditional defaults.

---

## Verdict

**Conditional on the plan, and on the gate itself.** The three reviews are
individually sound and collectively load-bearing on two untested premises (the
threat is future; surfacing is a resolution) and one unexamined axis (repeat
fetch over time). Their conditions actively trade against each other in two places
(§4, §5) where the merge rule "conflicts named with cost, never averaged" is about
to be tested.

What I would put in front of the human, in priority order:

1. **Retraction.** Ship a remediation primitive or write "no retraction path" into
   CLAUDE.md as a Class A line with a trigger. (§1)
2. **doc_id × supersession.** The URL-slug scheme kills the documented
   "re-ingest under a new doc_id" remedy. Either supersession comes into WS-2
   scope or `run_ingest` must refuse to re-fetch a URL whose revision it cannot
   process, and say so. Do not ship a watchlist that cannot watch. (§3)
3. **Conflict record: decide, do not average.** Durable + bounded + sanitized, or
   log-the-id-only with K1/K2's description corrected to match. Note that `0004`
   ships anyway for B1, so the table is nearly free. (§4)
4. **Ground `conditions.sparsity` now, as a bug on `main`** — not as a WS-2 line
   item, and never resolving ungrounded to the non-suspect direction.
   (injection-attacker F1, reframed by §2)
5. **Bound and normalize the group keys**, not just the values: `metric` needs a
   controlled vocabulary or a fuzzy-join, and H1's `publisher` comparison needs
   the same case-folding G3 mandates for aliases. (§6)
6. **Honest-corpus regression + flag budget** as an explicit gate condition
   alongside the hostile suite. (§7)
