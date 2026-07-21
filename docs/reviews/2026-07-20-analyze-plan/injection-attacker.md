# injection-attacker — GATE 1 review of the analytical MVP plan

**Target:** `docs/reviews/2026-07-20-analyze-plan/plan-under-review.md`
**Angle:** hostile SOURCE DOCUMENT in a multi-source corpus (not hostile-PDF/prompt-injection this round — hostile *data* flowing through a trust boundary that this plan reopens).

## Verdict: CONDITIONAL

The workstream split (persist+reconcile / analyze / report) is sound and I'm not
blocking the architecture. But the plan under-specifies three trust boundaries
that a hostile document in the corpus can walk straight through, and the
acceptance fixture itself already smuggles one of them past the extraction
gate as if it were normal. None of these are named as open decisions
(section 6) even though they're the same *category* of decision as A and F —
they need to be before code lands, not discovered during code review.

---

## Finding 1 — the reconciling upsert is tier-blind and first-write-wins; this reopens exactly the clobbering GATE-2 closed, just one layer down

CLAUDE.md is explicit about *why* inserts are fail-loud: "a naive `INSERT OR
REPLACE` would let a later (or hostile) document clobber an entity an earlier
document created, destroying corroboration." The plan's reconciling upsert
(§2, Decision F) replaces that fail-loud for entities with: union aliases,
**fill null attributes from the newcomer**, and only flag a conflict when a
*non-null* attribute disagrees with an existing *non-null* value.

That "fill null from the newcomer" clause has no tier gate and no ordering
guarantee. If a hostile tier-3 document is ingested *before* the trustworthy
tier-1/2 document happens to extract a given `node`/`chip` attribute (e.g.
`hvm_date_claimed`, `transistor_type`), the hostile value lands in the
canonical entity uncontested — there is nothing to conflict with yet, so no
flag fires. When the trustworthy document arrives later with the *correct*
value, that's now the newcomer hitting a non-null field, so it becomes a
"conflict, don't overwrite" — meaning the attacker's value stays authoritative
for the reconciled entity's `attribute_citations`-backed value, and the
correction is downgraded to a footnote. The plan never says which value wins
for downstream reads (report, further analysis) when a conflict is recorded —
it just says "record a conflict." Per-attribute grounding (v2's
`attribute_citations`) proves a value is *grounded in its own document*; it
proves nothing about whether that document should get to plant the value
first. Corroboration (Workstream 2) is explicitly tier-weighted
(`favored_tier` = lowest-numbered); entity reconciliation (Workstream 1) is
not tier-aware at all. That asymmetry is the exploit: an attacker can't move
a corroboration verdict (tier-weighted), but can plant an entity attribute
permanently by winning a race that has no tier tiebreak.

## Finding 2 — alias union is unauthenticated and tier-blind; it's also the only reconciliation output the report actually surfaces

`aliases: union` (§2) accepts strings from *any* document, tier 3 included,
with zero validation. This isn't hypothetical residue — `expected_analysis.json`
`entities_reconciled.tsmc_n2.aliases` is exactly this union, rendered
verbatim: `["2nm-class", "N2", "TSMC 2nm"]`, contributed by conf/foundry/vendor
respectively. A hostile tier-3 document doesn't need to move a number to do
damage here — it can inject any string it wants into a real entity's
public-facing identity, including a real competitor's product name (`"Intel
18A"`, `"MI300X"`), and it will render in the report as if TSMC N2 and a
competitor's chip were the same reconciled entity, sourced from an
unreviewed vendor deck. Decision A defers alias-based *matching*, but says
nothing about gating alias *storage* — those are different attack surfaces
and only one of them is flagged as deferred.

## Finding 3 — "≥2 members within tolerance" has no tier-diversity floor; the anti-inflation rule only covers a *solo* marketing claim, not a colluding pair

§3's stated anti-inflation principle: "a `marketing_only` or `sparsity=true`
claim can NEVER by itself make a group corroborated." Read literally, two
(or five) tier-3 marketing claims that agree with *each other* — copy-pasted
launch-day numbers, syndicated across partner decks — satisfy "≥2 members
within tolerance" and are not "by itself" anything. Nothing in the grouping
or verdict logic requires tier diversity, only member count + spread. That
means a flooding attacker doesn't need to beat the tier-2/tier-1 sources on
trust, just outnumber them with mutually-consistent tier-3 documents to flip
a metric to `corroborated` (and per §3's confidence rule, "multiple ... tiers
agreeing → high" is ambiguous on whether "multiple" means multiple *tier
values* or just multiple *documents* — a tier{3,3} agreement could plausibly
read as qualifying). The fixture never exercises this case (there's exactly
one vendor document), so this gap ships untested by construction, not just
unaddressed.

---

## Risk others will miss: `baseline_entity` (and `chip.process_node_ref`) are unvalidated cross-document FK references, and the acceptance fixture already relies on the bypass

CLAUDE.md: "`validate.py` enforces a per-DOCUMENT trust boundary only (a
claim must reference an entity from its own proposal); cross-document trust
is the store workstream's job." Look at `source_vendor.json`: its `entities`
array declares only `tsmc_n2`. Its two claims both set
`comparison.baseline_entity: "tsmc_n3e"` — an entity this document **never
declares, grounds, or cites**. That reference is only resolvable because
*other* documents (foundry, conference) happen to have inserted `tsmc_n3e`
first. This is not an edge case I constructed — it's baked into the MVP's own
definition-of-done (`expected_analysis.json` groups
`vendorslide:perf_per_watt` under `baseline_entity: tsmc_n3e` and expects it
to land in the same corroboration group as the foundry claim).

The plan's persistence design (§2) only discusses entity-identity resolution
for entities a document *itself proposes* ("On a repeat entity_id..."). It
says nothing about validating `baseline_entity` / `process_node_ref` FK
references against entities the citing document didn't propose. Workstream
2's grouping key is `(entity_id, metric, baseline_entity)` — it takes that
string at face value. The consequence: a hostile document needs zero
grounding to attach a claim to *any* entity in the store, including a real
competitor's reconciled entity that a completely different, trustworthy
document introduced — it only has to guess or already know that entity's
`entity_id` string. It can inflate its own product by claiming a favorable
ratio "against" a competitor's node without citing anything about that
competitor, and that claim will silently join the competitor-baseline's
corroboration group, potentially skewing `spread_pct`/`favored_tier` for a
verdict about an entity the hostile document never legitimately touched.
This is the exact "hostile doc attaches claims to a real competitor's
reconciled entity across documents" scenario — and unlike Findings 1–3, it
isn't a gap in an otherwise-specified mechanism, it's a mechanism (FK trust
resolution) the plan doesn't mention having to design at all, even though
the extraction-side boundary it crosses is called out by name in CLAUDE.md.

---

## What would move this to approve
Add explicit decisions (in the style of A/F) for: tier-aware (or at least
order-independent) precedence in null-fill; a gate on alias acceptance
(citation-required, or tier-restricted, or explicitly deferred-with-flag
like Decision A); a tier-diversity requirement for `corroborated` status, not
just member count; and a grounding/validation rule for `baseline_entity` /
`process_node_ref` cross-document references (even if the MVP answer is "trust
it and flag `unresolved_baseline` if the entity doesn't already exist in the
store" — just make it a decision, not a silent behavior the fixture already
locks in).
