# injection-attacker — GATE 1 v2 (re-gate) review of the analytical MVP plan

**Target:** `docs/reviews/2026-07-20-analyze-plan-v2/plan-under-review.md`
**Prior opinion:** `docs/reviews/2026-07-20-analyze-plan/injection-attacker.md` (three findings:
tier-blind first-write-wins reconciliation; no tier-diversity floor for `corroborated`;
unvalidated cross-doc `baseline_entity` FK refs)
**Angle:** hostile SOURCE DOCUMENT in a multi-source corpus — same as prior round.

## Verdict: CONDITIONAL

P1 and P2 are real, verified fixes and I'm not relitigating them — `validate.py`'s
`marketing_only` branch (read at `src/semianalyst/extract/validate.py:262-275`) now
requires *both* `entity_vendor` and `baseline_vendor` to be non-`None` before
declaring cross-vendor, which closes the `None`-as-different-vendor misfire
devils-advocate traced last round. The regenerated fixture is internally honest.

But of my three original findings, v2's proposed fixes close **zero of them
completely** — each closes the easy half and leaves the attack-relevant half open,
and the plan's own language sometimes obscures that the hard half is still open.
None of this should block indefinitely — G and H are correctly named as open
decisions for the human to close — but §1's null-fill design is presented as if it
already answers injection F1, and it doesn't, for the exact ordering that matters.

---

## Finding 1 — "tier-aware, order-independent" null-fill only works if there's a race to be order-independent *about*; the described API never creates one

§1: "Fill is **tier-aware / order-independent**: the higher-trust (lower
`source_tier`) document's value wins a null-fill race (injection F1). A non-null
conflict is **logged, not stored**."

Walk the actual call shape: `store.persist_extraction(document, ExtractionResult)`
is invoked once per document, sequentially (§4's acceptance test: "load 3 sources →
`persist_extraction` → `run_analysis`"). There is no batch step, no staging area,
no "collect every document's candidate value for this attribute, then pick the
best tier" — each call sees the DB as it currently stands and does exactly one of
two things to a given `node`/`chip` field: fill it (was null) or hit the "non-null
conflict, log only" branch (was already non-null). Under that shape, "tier-aware"
can only ever apply going *forward* from the moment a field first becomes
non-null — and the field's very first write is, by definition, unconditional (fill
a null; nothing exists yet to tier-compare against).

So run the attack the orchestrator asked me to check directly: hostile tier-3 doc
arrives first, sets `chip.tdp_w` (or `node.hvm_date_claimed`, or
`node.transistor_type`) to a bogus value with a technically-grounded citation
(grounding proves the string is *in the document*, not that the document should
get to plant it first — my prior review's point, still true). That's a null-fill,
tier-blind by construction because there's nothing to compare against yet. Now the
honest tier-1 document arrives with the correct value for the same field: the
field is now non-null, so this hits "non-null conflict → logged, not stored." The
attacker's value stays canonical; the correction is a log line. The plan's
tier-check ("higher-trust document's value wins a null-fill race") only fires for
the *reverse* ordering — honest-first, hostile-second — which was never the
threat model. This is functionally identical to what I flagged against v1; the
new language describes a mechanism (a genuine multi-candidate race) that the
per-document, sequential persistence API as specified cannot produce.

Two ways to actually close this, neither currently in the plan: (a) retain
per-attribute the *tier* that produced the current value, and let a
strictly-more-trusted incoming document overwrite even a non-null field (i.e. tier
beats first-write on every attempt, not just the first one) — this contradicts the
flat "non-null conflict: logged, not stored" rule as written and needs to be
stated as an explicit exception; or (b) genuinely defer commit until a batch is
known complete, which is a bigger design the plan doesn't describe or scope. Either
way, this is a decision on par with G/H and should be named as one (call it "K" —
does tier ever override a non-null value, or only race a null one?), not asserted
as already answering injection F1 in §1's prose.

Also: this stays untested by construction. All three fixture entities populate
zero `node`/`chip` attributes (confirmed by reading `source_conf.json`,
`source_foundry.json`, `source_vendor.json` — each `tsmc_n2` entity carries only
`entity_id`/`entity_type`/`vendor`/`name`/`aliases`). §4 promises a unit test for
"null-fill tier-precedence" but doesn't specify it must cover the *hostile-first*
ordering specifically — a test that only exercises honest-first-then-hostile-second
(the ordering that already worked before this plan) would pass while the actual
attack ordering ships unverified.

## Finding 2 — the tier-diversity cap (Decision H) caps `confidence`, not `status`; flooding still reaches `corroborated`, and the exclusion rule that would stop it is content-based, not tier-based

Verifying the orchestrator's specific question: **it relabels, it doesn't stop.**
§2's "corroboration count excludes suspect members" rule only excludes a claim
that is *itself* flagged `sparsity=true` or `marketing_only`. Two or more tier-3
documents that agree on a number and simply don't set `conditions.sparsity=true`
(nothing forces a document to disclose its own methodology honestly — `validate.py`
grounds `citation.quote_span` and, per v2, `attribute_citations`, but nothing
grounds the `conditions.*` booleans against the source text) are **not** suspect
under this rule, count fully toward "≥2 within tolerance," and reach
`status: corroborated`. Decision H's proposed cap then limits `confidence` to
`low` — but `status` is the field the schema actually persists
(`claim.corroboration.status`), the field Decision C's write-back is scoped to
(§2: "correctly scoped to `status` + `related_claim_ids`" per the v1 merge), and
the field most likely to be read directly once write-back's fast-follow condition
("a direct reader of the stored verdict exists") is met. Nothing in that
fast-follow trigger implies anyone revisits the flooding gap at that point — it
reads as "wire up the write," not "re-examine the algorithm." A same-tier-3,
mutually-consistent flood becomes a permanently-persisted `corroborated` verdict
with the only defensive signal (`confidence: low`) living in a report field a
downstream consumer has no reason to check if they're filtering on `status`.

This is exactly my original Finding 3, and v2's own §0 example of what it fixes
("all-tier-3 corroboration is capped at low, never high") concedes the group *is*
still `corroborated` — the cap is a confidence adjective, not a status gate. A
real fix needs a tier-diversity floor on `status` eligibility itself (e.g.
`corroborated` requires either ≥2 distinct tiers among non-suspect members, or at
least one member at tier ≤2) — not a downstream label on a status that already
flipped. The fixture can't catch this either way: it has exactly one document per
tier, so no same-tier pair ever exists to exercise flooding in either direction.

---

## Risk others will miss: P2 only closes the *dangling* half of the baseline-FK problem; poisoning a REAL, already-resolved entity's corroboration group is still completely unvalidated, and — unlike G/H — it isn't even named as an open decision

P2 (ratified): "a baseline that resolves to a stored entity is used; a dangling
baseline... is kept and flagged `unresolved_baseline`." I need to be precise about
what this actually closes versus what it was tuned to close. Devils-advocate's v1
review of my own opinion made a fair hit: my prior remediation ("flag
`unresolved_baseline` only if the entity is absent from the store") was calibrated
to exactly the strength that keeps a fixture where the baseline happens to
resolve, green. P2 now formalizes that lenient form as the ratified answer — and
the *new* fixture entry (`vs_intel` / `intel_18a`) exercises only the dangling
case, which is the **less dangerous** half. A dangling baseline produces an inert
singleton (`uncorroborated`, flagged, harmless) — the fixture proves that path
works. It says nothing about the case where the string *does* resolve.

Confirmed by reading the code: `validate.py`'s provenance check
(`extract/validate.py:236-239`, "`claim.entity_id not in kept_entity_ids`") only
ever checks `claim.entity_id` — the claim's own subject — against the *citing
document's own declared entities*. `comparison.baseline_entity` is never checked
against anything at the extract layer (by design — CLAUDE.md calls this "the
store workstream's job"), and the v2 plan's persistence/analyze design (§1–§2)
still only discusses entity-identity resolution for entities a document *itself
proposes*, plus the P2 dangling-baseline flag. Nothing validates whether a
document had any grounding basis to *reference* an entity it never declared, once
that entity happens to already exist in the store.

Concretely: any hostile tier-3 document can set `comparison.baseline_entity` to
the `entity_id` of a real competitor's node or chip — already reconciled in the
store by completely unrelated, trustworthy documents — cite nothing about that
competitor, and its claim silently joins that competitor's corroboration group
under the grouping key `(entity_id, metric, is_relative, baseline_entity)`,
skewing `spread_pct`/`favored_tier` for an assessment about an entity the hostile
document never legitimately touched. This gets *more* dangerous as the corpus
grows, not less — every additional trustworthy document that legitimately
introduces a new competitor entity is a new, free target string for this attack,
and P2's flag never fires because the reference resolves cleanly. This is the
sharper variant of the risk I flagged last round, it survives both the P1 and P2
fixes untouched, and — tellingly — §5's open-decisions list (G, H, I, J) has no
letter for it. G/H at least got named as unresolved; this didn't, which makes it
easy for the re-gate to read "P2: done" and move on without noticing the harder
half was never in scope.

## Secondary note — Decision G (alias union) is still open and, unlike `unresolved_baseline`, has zero interim signal

Not a new finding (my prior Finding 2, unchanged), but worth restating now that
it's explicitly named as open rather than silently shipped: the fixture still
unions `vendorslide`'s tier-3, uncited `"2nm-class"` into `tsmc_n2`'s canonical
`aliases` with no gate and no flag. `unresolved_baseline` at least gives a
downstream reader *something* to filter on; there is no analogous
`unvetted_alias`-style signal proposed even as a stopgap while G is unresolved. If
G resolves toward "ungated union" (the cheapest option, and the only one that
doesn't touch the fixture), a hostile tier-3 document can inject an arbitrary
string — including a real competitor's product name — into a real entity's public
identity, and the report renders it exactly as it renders `"N2"` or `"TSMC 2nm"`:
indistinguishable, unflagged, sourced from an unreviewed vendor deck.

---

## What would move this to approve
- Finding 1: either implement genuine tier-precedence that survives a non-null
  field (an explicit exception to "non-null conflict: logged, not stored" for a
  strictly-more-trusted incoming value), or name the current gap as an explicit
  open decision instead of citing it in §1 as already resolving injection F1 — and
  add a unit test for the hostile-tier-first ordering specifically, not just its
  mirror.
- Finding 2: move the tier-diversity requirement from `confidence` to `status`
  eligibility for `corroborated` — a diversity floor, not a downstream label —
  since `status` is what write-back will eventually persist.
- Risk: give the "poison a real, resolved entity via `baseline_entity`" case a
  decision letter and an owner. Even the minimal honest answer — "trust it,
  cross-document baseline references get zero provenance requirement, full stop,
  ship it" — is acceptable *if named*, the way P2 named the dangling case; it is
  not acceptable left invisible.
- Secondary: an interim `unvetted_alias`-style flag (or equivalent) on any
  reconciled-entity alias contributed only by a tier-3 document, until Decision G
  resolves.
