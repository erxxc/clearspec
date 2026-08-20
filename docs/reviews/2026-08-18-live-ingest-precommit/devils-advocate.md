# devils-advocate — WS-2a precommit gate (2026-08-18)

**Target:** the three reviewer opinions in this directory (not the diff directly).
Contract: `docs/reviews/2026-08-18-live-ingest-plan/resolution.md`.

**One-line:** All three certified the artifact fold as a faithful refold and then
argued about what to validate *inside* it — but the fold replays documents in a
DIFFERENT ORDER than the incremental path (`(ingest_date, doc_id)` vs sha256), so
every `db rebuild`, every `forget`, and every revision silently re-decides every
first-writer race in the store, including which document a conflict record
accuses; the two determinism tests pass only because their fixtures' two orders
coincide by construction.

---

## 0. Where the three agree — and what that agreement rests on

All three went conditional, and their asks are almost disjoint (fold
authentication / schema parity / sanitizer consolidation). What they share is
not an ask but a premise, stated by none of them:

> The artifact fold reproduces the store. Whatever we get right on the write path
> we get right on the refold path; the only open question is what runs *during*
> the replay.

Injection's Finding 1 is entirely about what does *not* run during the replay
(grounding, G1, G3). Schema-purist checked artifact payload *fidelity*
(`_extracted_at`, `_extracted_against` present) and never asked what the fold
does with those stamps. Pragmatist ticked the fold off as "built, tested
(`tests/test_rebuild.py`)". `CLAUDE.md:90` states the premise outright —
*"Incremental state and rebuilt state must stay equal — tested."*

The premise is false, and the test that "proves" it is fixture-lucky.

## 1. The shared premise nobody checked: the fold reorders reconciliation

`extract/pipeline.py:248`:

```python
winners.sort(key=lambda w: (str(w[1].data["document"].get("ingest_date") or ""), w[0]))
```

`ingest/base.py:130` (the incremental path):

```python
for sidecar in sorted(raw_dir.glob(f"*{SIDECAR_SUFFIX}")):   # == sha256-lexical
```

Reconciliation is first-writer-wins in every dimension this workstream just
built: identity fields frozen by the first document, null-fill first-non-null,
and G3 alias ownership (`_foreign_surface_forms` only knows what is *already*
stored). So replay order is not a cosmetic detail — it decides who owns an
entity's identity, who fills each null, who captures each surface form, and
therefore **which document each `entity_conflict` row names as the offender**.

- Within one `extract` batch, incremental order is sha256-lexical — effectively
  random w.r.t. `ingest_date`. For *n* pending docs the two orders agree with
  probability 1/n!: three pending docs, ~83% chance a later rebuild reorders them.
- After WS-2b, it is worse than random. `ingest_date` is day-granular; a fetcher
  run stamps a whole batch with the *same* date, so the fold degenerates to
  alphabetical-by-`doc_id` while the incremental path stays sha-random.
  Divergence becomes the guaranteed case at exactly the moment the fetcher lands.
- The trigger is ordinary operation, not an operator's explicit `db rebuild`:
  `run_extract` calls `run_rebuild(config)` whenever ANY document is a revision
  (pipeline.py:198). One revision to one document re-decides reconciliation for
  the entire corpus.

Two shipped docstrings assert the opposite. `store/persist.py:37-40`: *"a rebuild
replays persist_extraction over retained artifacts in the same (ingest_date,
doc_id) order, so incremental conflicts regenerate identically on refold."* The
incremental order is not `(ingest_date, doc_id)`. `pipeline.py:220-222` makes the
same claim ("the same first-doc-wins reconciliation a fresh incremental run would
produce").

**Why the tests don't catch it.** `test_rebuild_reproduces_the_incremental_store`
and `test_conflicts_regenerate_deterministically_on_rebuild` each extract their
two documents in *separate sequential `run_extract` calls* with ascending
`ingest_date` (`2026-01-01`, then `2026-01-02`) — so call order, sha order (never
exercised, one doc per call) and fold order coincide by construction. Neither
test ever puts two documents in one batch with sha order opposed to ingest_date
order. `_load_honest_corpus` (test_hostile.py:792) doesn't go through the fold at
all — it calls `persist_extraction` directly in a hard-coded list order that also
happens to be ingest_date order (`tsmc_pr_n2` 01-05, `hotchips_n2` 01-06,
`vendorslide` 01-07). **No test in the suite folds the honest corpus.**

**The one-word fix, cheaper than anything three reviewers asked for.** The
artifact already carries `_extracted_at`, stamped at real extraction time — i.e.
exactly the incremental order. Sorting the fold by `_extracted_at` instead of
`ingest_date` makes `CLAUDE.md:90` true for free, and is no more attacker-
influenceable than `ingest_date` already is (both come out of the same
attacker-writable JSON, see §3). If the human instead prefers `ingest_date` as
canonical, then say so and make `run_extract` sort `pending` by
`(ingest_date, doc_id)` too — and either way, document that a rebuild
**re-decides** races across batches (no key can make a from-scratch fold match a
history of incremental runs), and replace the fixture-lucky equality test with
one whose sha order and ingest_date order are deliberately opposed.

## 2. The scenario where all three are wrong at once

The chain below passes every defense this gate shipped, and each reviewer
inspected exactly one link and passed it.

1. A hostile vendor PDF names a competitor — which is what hostile comparison
   documents *do*; the plan gate's own Conflict-4 disposition rests on this
   ("competitors are *named* in hostile comparisons — that is the point of
   them"). So the string `Intel 18A` is verbatim in the hostile document.
2. **G1 passes.** `_grounded_ci(alias, source_text)` asks only whether the alias
   appears in *this document's* text. It does. G1 stops the model from inventing
   an alias; it does nothing about a document that plants one. Injection called
   G1 a closed gap ("closes the sparsity/identity-plant gaps"); pragmatist ticked
   it "built, tested". Neither stated its actual scope.
3. **G3 is order-dependent.** `_foreign_surface_forms` refuses only surface forms
   *already stored*. Hostile-first ⇒ the alias unions cleanly.
4. **The honest document then takes the conflict.** When the real Intel document
   arrives, its own alias `18A`/`Intel 18A` collides with the squatter's, and
   `reconcile_entity` writes `alias_collision` — `entity_id=intel_18a`,
   `doc_id=<the honest doc>`. `report` prints *"[alias_collision] intel_18a
   alias: refused Intel 18A from intel_doc"*. The record the human adjudicated
   into existence because *"the offered value is the only honest record of what a
   hostile document tried to write"* is, in the ordering that matters, a record
   of what the **honest** document tried to write, with the honest document named
   as the offender.
5. **J can't see it.** `_slug_collisions` skips any pair whose `_norm_key(vendor)`
   differs (corroborate.py:210). The squatter's vendor is `Vendor Z`, the
   victim's is `Intel` — different vendor, no `possible_slug_collision` flag. J
   catches same-vendor slug drift, i.e. the accident, not the attack.
6. **And §1 makes step 3 a coin flip that gets re-flipped.** Whoever won the
   surface form incrementally can lose it on the next unrelated `forget` or
   revision, silently, with the conflict rows regenerated in the new direction.

The premise underneath all of this — and underneath injection's Finding 1 — is
that `validate.py` is a **trust** boundary. It is a **fidelity** boundary: it
proves the model didn't fabricate *relative to the document*, where the document
is written by the adversary. Grounding a hostile document against itself is not a
trust guarantee, and CLAUDE.md's "the LLM output is a PROPOSAL; validation is the
guarantee" reads, to the next contributor, as if it were one. That sentence needs
a clause.

## 3. Injection's Finding 1 is real but mis-rated, and its fix is mis-named

The orchestrator's brief paraphrases the ask as "fold-time re-validation against
retained blobs". Injection did **not** ask for that — their recommendation is a
sidecar/doc_id binding check. The distinction matters, because the strong version
is much worse than it looks: re-validating grounding at fold time means
re-extracting PDF text at fold time, which makes the fold's output a function of
the pypdf version. A library bump would then silently drop previously-grounded
claims on the next `forget`. Never adopt the strong version; the fold must stay a
pure function of retained JSON.

The weak version is worth doing, but not for the reason given. Under injection's
own threat model — arbitrary write to `data/raw/` — the hostile artifact grants
**almost no new capability**:

- Write a blob + sidecar instead. Grounding validates the model's claims against
  *the attacker's own text* (§2), so a fabricated "99x, tier 1, publisher IEEE"
  claim can be made fully grounded through the legitimate path.
- `source_tier`, `publisher`, `ingest_date`, `doc_id` all come from the sidecar
  on that path — attacker-chosen already.
- Even injection's "stronger primitive" (full replacement of an already-trusted
  document) is already reachable: same `doc_id` + **changed** bytes is classified
  as a revision, extracted, and folded in as the winner (pipeline.py:147). The
  revision path *is* the supersession primitive; it needs no artifact.
- The genuine delta is: no model call (free, silent, no API key, no rate limit)
  and direct control of `_extracted_at` — which, per §1, is the global replay
  order. That is the part worth naming, and injection didn't name it.

So the sidecar-binding fix raises the attacker's cost by one file and closes no
class. Do not call it "authenticating the fold" — a defense that lives in the
same attacker-writable directory as the thing it defends authenticates nothing,
and a CLAUDE.md line claiming otherwise is worse than the current silence. Real
authentication means a MAC keyed outside `data/raw/`; that is WS-2b+ scope, and
the honest MVP posture is injection's *fallback* ask: name write access to
`data/raw/` as the trust boundary, beside S2.

**But there is a real, non-adversarial hole under this stone that no reviewer
found, and it breaks the primitive the whole plan gate was adopted to deliver.**
`ingest/pipeline.py:129` — `forget` skips an unreadable sidecar with `continue`
(the appsec fault-isolation fix). That sha's **artifact is therefore never
quarantined**, and `run_rebuild` reads artifacts by glob, independent of
sidecars — so the refold replays it and the "retracted" document is back in the
store. `forget` returns success; the CLI prints `refolded: N` with no names. Same
outcome for any artifact whose sidecar is missing for any reason. **Retraction
can silently fail to retract.**

The two-line fix is cheaper than the binding and strictly stronger for this
failure: assert the post-condition. After the refold, if `doc_id in
report.rebuild.folded`, raise/surface loudly. That closes the corrupt-sidecar
case, the missing-sidecar case, and hostile-artifact resurrection, without
claiming any authentication property. (Do injection's binding too if it's five
lines — as a *consistency* check, documented as such.)

## 4. Do the three asks compose? Three of them actively fight

**(a) Pragmatist wants to delete the exact tests schema-purist's fix would need.**
Pragmatist Finding 2 asks to cut the four `test_validate.py` bound tests as
redundant with `test_field_flood`. Schema-purist Findings 2 and 3 say two of
those bounds are **wrong** and must change. Deleting per-bound regression
detectors in the same gate that changes the bounds is backwards. This is the
sharpest direct conflict in the set and neither reviewer saw the other's paper.
Resolution: keep the four tests, revisit after the bounds settle — or, if they
must go, they go *after* the bound change lands with its own test.

**(b) Pragmatist's "one shared scrub" would silently weaken injection's one
best-tested guarantee.** Four of the five sites (`models._NO_CTRL`,
`db._CTRL_RE`, `pipeline._ERR_CTRL`, `validate._CTRL`) share a character class
but not semantics: `models._NO_CTRL` is a **reject** (pydantic pattern → the
entity drops fail-soft at shape, which is exactly what
`test_control_byte_chip_attribute_rejected_at_shape` pins), the other three are
**scrub-and-continue**. "One `_scrub_ctrl(text)` helper each module references"
is the natural refactor and it invites the next editor to make the model layer
sanitize instead of reject — a security regression wearing a cleanup's clothes.
Share the character-class *constant*, not the function; keep reject and scrub
visibly distinct.

**(c) The fifth site must NOT be consolidated, and pragmatist listed it as if it
should.** `cli._ansi_safe` has a different range (`\x7f-\x9f`) plus a Unicode-Cf
pass, and CLAUDE.md states terminal encoding is a display-edge concern
deliberately *not* a shared library capability (a web UI HTML-escapes instead).
Pulling it into `store/text_safety.py` alongside the ingestion filters would
either drag C1/Cf stripping into the store (changing stored data) or invite
someone to "align" them downward. Consolidate four; leave the fifth alone and say
why in a comment.

**(d) The shared `_fold()` helper is not a refactor — it is a behavior change to
refusal logic.** There are four idioms, not three (schema-purist and pragmatist
each listed a different three): `validate._grounded_ci` `.lower()`,
`validate` dedup `.strip().lower()`, `db` `.casefold()` (no strip), `analyze`
`_norm_key` (collapse+strip+casefold). Adopting `_norm_key` everywhere means
whitespace variants now collide in `_foreign_surface_forms` ⇒ **more**
`alias_collision` refusals and conflict rows, and more intra-document entity
merges in validate. That is the right direction and it must land with hostile +
honest tests, not as a tidy-up. Note the direction split nobody flagged:
schema-purist's whitespace fix makes reconcile *less* likely to fire a spurious
`identity_field`; injection's confusables ask makes G3 *more* likely to fire.
They compose, but they push the flag budget in opposite directions.

**(e) Schema-purist's bound fix collides with the repo's own migration rule.**
Fixing the `cond_stated_caveats`/`aliases` CHECKs means either amending an
**applied** migration (0004 is applied on the dogfood store — CLAUDE.md forbids
editing applied migrations in place) or shipping 0005 inside the same gate. And
the obvious escape hatch — "blow away the store and `db rebuild`" — is lossy:
pre-WS-2a documents have no artifacts and do not survive a fold (documented at
pipeline.py:223). So schema-purist's Finding 1 (carry-forward may crash) and
Finding 2 (bounds are wrong) are the same operator decision and must be decided
together. Mitigating note on Finding 1's severity: `init_db`'s `with conn:`
rolls the failed script back (and the `INSERT..SELECT` precedes every `DROP`), so
the failure mode is *fail-loud, store intact*, not corruption. That downgrades
the ask from "build `db migrate --check`" to "translate the error + one
documented triage query."

## 5. Two severity re-rates, both upward, both one root cause

Schema-purist's Findings 2 and 3 are instances of a single unstated invariant
violation created by Conflict 2's decision:

> **The DDL bounds the ACCUMULATED, SERIALIZED form. Pydantic bounds the
> PER-DOCUMENT, RAW form. Nobody wrote down that these must relate.**

The correct rule is: a DDL CHECK must be ≥ the worst-case serialization of the
maximum *accumulated* pydantic-legal value, or the model layer must bound the
accumulated form. Neither holds today, in both directions:

- **Serialization (Finding 2), understated.** 16 × `Caveat500` serializes to
  8,049 chars unescaped against a CHECK of 8,500; `Caveat500` is deliberately
  newline-permitting verbatim footnote text, and every `\n` and `"` costs one
  extra char. The consequence is worse than the reviewer said: `persist_extraction`
  has **no per-claim isolation** (persist.py:48-50), so one over-long serialized
  caveat list raises `IntegrityError` out of `with conn:` and rolls back the
  **entire document** — document row, entities, claims, all of it — into
  `ExtractReport.errors` with a message that names a CHECK, not a cause.
- **Accumulation (Finding 3) is a cross-document denial of service, not just a
  bound escape.** 16 aliases × 80 chars serializes to ~1,329 against a CHECK of
  1,500. Two hostile documents (each individually legal, each alias grounded —
  just print the strings in the PDF) saturate a *victim* entity's alias budget by
  reusing its `entity_id` with its vendor/name printed in their own text.
  Thereafter **every honest document that contributes one new alias to that
  entity fails to persist entirely**. The flood guard Conflict 2 shipped to stop
  a flood is the mechanism that converts the flood into an outage on the honest
  path — a fail-CLOSED durable layer under a fail-SOFT model layer, which is the
  exact inversion of the fail-safe posture CLAUDE.md insists on everywhere else.
  (`if alias in aliases` at db.py:439 is case-sensitive while the collision check
  beside it is case-folded, so case variants inflate the list too.)

This also constrains schema-purist's own remedy: enforcing `max_items: 16` at
merge must be implemented as **refuse the alias + record a conflict**, never as
"reject the document" — otherwise the fix reproduces the wedge it closes.

## 6. The question the group avoided: can the acceptance guard see any of this?

Pragmatist's DoD check ticks *"honest-corpus regression + flag budget: present,
verified at zero new flags."* Nobody asked what that guard is capable of
detecting. Its corpus is **three documents and two entities**
(`tests/fixtures/analyze/tsmc_n2_corroboration/`), with:

- no cross-entity surface-form overlap (`tsmc_n2` aliases `N2`/`TSMC 2nm`/
  `2nm-class`; `tsmc_n3e` alias `N3E`) ⇒ **any change to G3, `_foreign_surface_forms`,
  confusable folding, or alias-union gating is invisible to it**;
- no conflicts at all ⇒ the `identity_conflict` flag can only be exercised by a
  change that *creates* a conflict on 3 clean docs, which none of these fixes do;
- no whitespace/casing variance ⇒ blind to the `_fold()` unification;
- load order == ingest_date order, and it never goes through the fold ⇒ blind to §1.

So every fix all three reviewers propose is, by construction, invisible to the
guard that Challenge 4 installed to protect the reader. "Zero new flags" is a
true statement about a fixture, not evidence about the corpus. That is not a
reason to block — it is a reason to stop citing the budget as coverage, and to
add the two fixtures it lacks (two entities sharing a surface form across
vendors; one entity described by two docs with casing/whitespace variance) at the
same time as any change to refusal logic. Otherwise the next gate will approve a
refusal-behavior change on the strength of a test that cannot fail.

## 7. Cheapest coherent bundle

Ordered by (real risk closed) / (lines changed). Items 1–3 are the ones I would
not ship without.

1. **Fold order** (~1 line + 1 test + 1 doc line). Sort the fold by
   `_extracted_at`, or declare `(ingest_date, doc_id)` canonical and sort
   `run_extract`'s `pending` the same way. Fix the two false docstrings
   (persist.py:37, pipeline.py:220) and `CLAUDE.md:90`; replace the fixture-lucky
   equality test with one whose sha order opposes its ingest_date order. **Blocks
   WS-2b**: a batch fetcher makes divergence the guaranteed case.
2. **`forget` post-condition** (~2 lines + 1 test). If the forgotten `doc_id`
   appears in `rebuild.folded`, fail loud. Closes silent non-retraction via
   unreadable/missing sidecar *and* hostile-artifact resurrection.
3. **The accumulated-vs-serialized invariant** (1 migration + 2 CHECK values +
   merge-time alias refusal). Set each JSON CHECK to the worst-case serialization
   of the max accumulated pydantic-legal value; enforce `max_items` at merge as a
   refusal-with-conflict. Decide amend-0004 vs 0005 explicitly (see §4e) and
   record the dogfood-store consequence.
4. **Documentation-only, zero code, do all three:** name `data/raw/` write access
   as the trust boundary beside S2 (injection's fallback ask); add the "OPEN"
   line for unsanitized `quote_span`/`stated_caveats` (injection F3); add the
   clause that grounding is fidelity-to-this-document, not trust (§2).
5. **Shared control-byte *constant*** (not function) across the four ingestion
   sites; leave `cli._ansi_safe` alone with a comment saying why (§4b/c).
6. **Shared `_fold()`** at today's semantics + reconcile's missing `.strip()`,
   shipped **with** the two new honest fixtures from §6 — as a behavior change,
   not a refactor.

**Reject or defer:** pragmatist's deletion of the four bound tests (§4a — wrong
order of operations); injection's confusables/NFKC (F2) — right target, but it
changes refusal behavior with a guard that provably cannot see false positives;
land it after §6's fixtures exist, in the shared `_fold()`. And do not adopt the
strong reading of injection's Finding 1: fold-time re-validation against blobs
would make the fold non-deterministic across PDF-library versions, and would buy
re-fidelity to a document the same attacker wrote.
