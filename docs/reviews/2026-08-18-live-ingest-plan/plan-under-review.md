# WS-2 — Live ingest + Class A trust model (plan, under review)

Gate target: the DESIGN, before any fetcher code. Per `docs/ROADMAP.md`, the
moment network fetch lands the entire Class A set goes live simultaneously, so
this gate resolves the deferred decisions **as a named set, not piecemeal**.
Ground in `CLAUDE.md` (authoritative Class A definitions),
`schema/extraction_schema_v3.yaml`, and the shipped code: `store/persist.py` +
`db.reconcile_entity` (first-non-null-wins, tier-blind, identity fields frozen by
first writer), `analyze/corroborate.py` (suspect-excluded corroboration count,
tier-blind `favored_tier`), `extract/validate.py` (per-document grounding,
name-pinned aliases), `ingest/base.py` (sidecar last-write-wins, no hash
re-verification), `cli._ansi_safe` (escapes stripped; Unicode Cf NOT stripped).

External references consulted (adjacent workspace repos): **agentlens**
`DECISIONS.md` #7 — the confidence "Floor": *disagreement means corroboration
didn't actually happen; never claim more confidence than the strongest single
agreeing source* — and #2 — a shared near-constant key must never merge distinct
records (definition-scoped keys excluded from the merge fast path), plus its
bucket-size heuristic (an oversized agreeing cluster is more likely a too-broad
key than a real corroboration cluster). **repoauditor** `CLAUDE.md` — untrusted
content is delimited evidence; validation failures are logged outcomes, never
silently swallowed; no guessing under low confidence (write `unresolved`, never
round up).

## 0. Structure: trust before exposure

WS-2 lands in two slices, gated together here but committed separately:

- **WS-2a — trust hardening (no network).** Every Class A decision below,
  enforced and tested with *constructed* hostile documents through the real
  `validate → persist_extraction → analyze → report` chain. Deterministic,
  offline, no model in the loop (the model-in-loop injection surface is already
  covered by `test_injection_*`).
- **WS-2b — the fetcher.** `FoundryFetcher.fetch` + `run_ingest` wiring, riding
  on the already-hardened store.

Rationale: no hostile byte should be fetchable before the store can survive it.

**Scope cut (proposed): direct document URLs only; HTML discovery deferred.**
`config.toml` sources gain explicit document URLs (a `documents = [...]` list per
source, or per-document `[[sources]]` entries). Crawling newsroom index pages to
*discover* PDFs is scraping fragility that adds zero trust-model coverage — every
Class A decision is forced by fetching one known URL. Discovery becomes WS-3.

## 1. WS-2b — fetcher design (`ingest/foundry.py`, `ingest/pipeline.py`)

- **Transport:** HTTPS-only, validated before the first request AND at every
  redirect hop (a compromised site must not bounce us to `http://` or `file://`);
  redirect cap 5; total-size cap 50 MB (streamed, aborted on overflow); connect +
  read timeouts; magic-byte check (`%PDF-`) before storing a blob we will treat
  as a PDF. Rate limits from `config.rate_limits` (token-bucket per host;
  `max_concurrency` honored).
- **Idempotency:** bytes → existing `store_raw` (sha256-addressed; re-fetch of
  unchanged bytes is a no-op; changed bytes at the same URL = new blob, revision
  surfaced downstream by `run_extract` exactly as today).
- **doc_id scheme (new decision):** `doc_id` = deterministic slug of the
  normalized URL (`host + path`, lowercased, non-alnum → `_`, bounded ≤120).
  URL is the document's identity; content is its version — this is what makes
  same-doc_id/changed-bytes revision detection work for fetched docs. Collisions
  between distinct URLs slugging identically are surfaced by the sidecar identity
  binding rule (§2.6), not silently merged.
- **Sidecar provenance:** `publisher`, `doc_type`, `source_tier` come from the
  operator's watchlist entry (trusted config). `title` is derived from the URL
  basename (bounded, charset-sanitized — it is display data, not identity).
  `publish_date` = null (unknown; never guessed from untrusted headers).
  `url` = the *final* post-redirect URL, recorded for audit.
- **Fault isolation:** one failed source lands in `IngestReport.errors`
  (mirroring `ExtractReport.errors`); the batch continues.

## 2. WS-2a — the Class A set, resolved (proposals)

### 2.1 K — tier precedence on reconciliation
- **K1 (propose): never-overwrite stays universal — no tier ever overwrites a
  non-null attribute.** Overwrite-by-authority is exactly how a poisoned
  "authoritative" doc wins; a higher-tier doc arriving later with a different
  value is a *conflict* (2.5), recorded and surfaced, never an auto-resolution.
- **K2 (propose): null-fill stays first-non-null and tier-blind**, but any later
  differing value — same or different tier — writes a conflict record. The race
  a hostile early doc can win is filling a null first; the defense is that the
  honest value's arrival becomes a *visible conflict*, not a silent loss.
- **K3 (propose): `favored_tier` stays tier-blind (suspects NOT excluded).**
  Deliberately contrarian to the note in CLAUDE.md: suspect-ness
  (`sparsity`/`marketing_only`) is *self-declared by the claim's own document*.
  Excluding suspects from `favored_tier` would punish the honest discloser and
  reward the concealer — a hostile doc trivially makes itself non-suspect by not
  disclosing sparsity. Tier-blind min preserves the honest discloser's tier
  authority; the `sparsity` flag on the group already tells the reader why the
  numbers diverge. (Aligned with agentlens's Floor reading: conflict handling
  must not let one side manufacture standing.)

### 2.2 G — alias-union gating
- **G1 (propose): aliases must be grounded** — each model-proposed alias must
  appear (whitespace-normalized, case-insensitive) in the contributing document's
  source text, enforced in `validate.py` beside claim grounding; ungrounded
  aliases dropped with a `Rejection`. (The pinned canonical `name` is exempt — it
  is the entity's own shape-validated identity field, not a free-text graft.)
- **G2 (propose): content bounds** (§2.7) apply to every alias.
- **G3 (propose): cross-entity collision refusal at reconcile** — an incoming
  alias that equals (case-insensitive) another *stored* entity's `name` or alias
  is NOT unioned; it writes an `alias_collision` conflict record (2.5). This is
  the agentlens definition-scoped-key lesson: a shared surface form must never
  silently bridge two distinct identities.

### 2.3 H — status-level floor for `corroborated`
- **H1 (propose): publisher-diversity floor.** `corroborated` requires ≥2
  non-suspect members within tolerance **from ≥2 distinct publishers**. A
  single-publisher agreeing group demotes to `weakly_corroborated` + new flag
  `single_publisher`. Five PDFs from one vendor agreeing with itself is one
  voice, not corroboration. (Requires adding `publisher` to `ClaimView`'s
  document join — one column.)
- **H2 (propose): tier-diversity confidence cap.** A `corroborated` group whose
  members are all tier-3 keeps the status (two *independent* vendors agreeing is
  real signal) but confidence caps at `medium` + flag `vendor_only`. This is the
  analyze-v2 "all-tier-3 cap" (proposed then, dropped in the honest-data MVP),
  landing now that hostile input is live.
- Rejected alternative: requiring ≥2 distinct *tiers* for `corroborated` — too
  strong; it would permanently deny corroborated status to a claim confirmed by
  two independent vendors, which is legitimate signal the tool exists to find.

### 2.4 Resolved-baseline poisoning + baseline binding
- **B1 (propose): baseline surface-form binding, flag-not-drop.** For a claim
  with `baseline_stated=true` and a resolved `cmp_baseline_entity`, analyze
  checks that *some surface form* of the baseline entity (its stored `name` or
  any alias, case-insensitive) appears in the claiming document's… source text is
  gone by analyze time — so the check runs at **validate** time against
  `source_text`, using the *proposal's own* baseline surface forms, and the
  result is persisted as a claim-level flag `unbound_baseline` when absent.
  Heuristic (name segments vs slugs), so it FLAGS, never drops — per
  repoauditor's rule: under low confidence, write the uncertainty, don't guess.
- **B2 (propose):** `cmp_baseline_entity` gets the same content bounds as
  `entity_id` (§2.7) — the FK drop removed the shape guard; this restores a
  shape bound without restoring the existence constraint (a dangling baseline
  stays legal and flagged, per P2).

### 2.5 Identity-field conflict + I (persisted conflict records)
- **Schema first (CLAUDE.md rule): `extraction_schema_v4.yaml`** adds a
  `conflict` record: `{conflict_id, kind: identity_field | attribute |
  alias_collision, entity_id, doc_id (offender), field, stored_value,
  offered_value, created_at}`. Models regenerated; **migration
  `0004_entity_conflicts.sql`** adds the table. Why persisted rather than
  derive-on-read (the corroboration precedent): a conflict's *offered value is
  otherwise lost* — reconcile drops it today, so there is nothing to re-derive
  from. Persisting is the only honest record. (B2/derive-on-read reasoning does
  not transfer: that was about a per-group verdict with no per-row home; this is
  a per-event fact with no other home at all.)
- `reconcile_entity` writes a conflict record whenever a later document differs
  on frozen identity fields (`vendor`, `name`, `entity_type`) or on a non-null
  attribute (K2), or on an alias collision (G3). Values stored bounded (§2.7).
- `report` surfaces per-entity conflict counts and an `identity_conflict` flag on
  affected assessments. A typo'd vendor no longer silently conflates two things —
  it conflates them *loudly*.

### 2.6 Sidecar identity binding + blob hash re-verification
- **S1 (propose):** `write_sidecar` refuses to overwrite an existing sidecar
  whose `doc_id` differs — same bytes re-ingested under a different doc_id is a
  loud `IngestReport.errors` entry (operator path raises), never a provenance
  clobber. Same-doc_id rewrite (metadata refresh) stays allowed.
- **S2 (propose):** `read_raw_docs` (consumed by `run_extract`) recomputes each
  blob's sha256 and drops mismatches into `ExtractReport.errors` (`"blob hash
  mismatch — tampered or corrupt"`). Cheap at this scale; mandatory once WS-2b
  introduces a second writer to `data/raw/`.

### 2.7 Content bounds (baseline content-bound, generalized)
- `_v4` schema + pydantic: bounded lengths and printable-charset constraints on
  every model- or network-influenced string — `entity_id`/`cmp_baseline_entity`
  (slug charset, ≤80), `name`/`vendor`/aliases (≤80 each, ≤16 aliases),
  `metric` (≤120), `doc_id` (≤120), `title` (≤300), `quote_span` (≤2000).
  Enforced at the pydantic layer (shape validation already drops malformed items
  per-item, fail-soft with `Rejection`); no SQLite DDL change needed.

### 2.8 Unicode display spoofing (report)
- `cli._ansi_safe` additionally strips every Unicode category-**Cf** codepoint
  (bidi overrides U+202A–202E / U+2066–2069, zero-widths U+200B/200C/200D,
  U+FEFF, and the rest of Cf — a category test, not an enumerated list, so new
  format characters fail safe). Closes the Trojan-Source half; covered by a test
  with an actual bidi-reordering payload.

### 2.9 J — slug-collision detection strength
- **J (propose): advisory analyze-time flag, not fail-loud.** Derive-on-read:
  two stored entities sharing `(entity_type, vendor)` with a case-insensitive
  surface-form intersection (name/alias overlap) get `possible_slug_collision`
  on their assessments. Fail-loud is rejected *because of G3*: if collisions
  blocked ingestion, a hostile doc could inject an overlapping alias to DoS
  honest ingestion. G3 blocks the graft; J surfaces the residue. No schema.

## 3. Named hostile suite (`tests/test_hostile.py` + `tests/fixtures/hostile/`)

Constructed documents/proposals through the REAL chain
(`validate → persist_extraction → analyze → report`) — never the honest
acceptance golden. Deterministic and offline (no model in the loop; the
model-facing injection surface keeps its existing `test_injection_*` coverage).
Named cases, one per attack:

| case | attack | must hold |
|---|---|---|
| `alias_graft` | tier-3 doc adds competitor's name as alias | not unioned; `alias_collision` conflict recorded |
| `alias_ungrounded` | alias absent from source text | dropped with Rejection (G1) |
| `field_flood` | oversize/control-char strings in metric/alias/baseline | rejected by bounds (§2.7) |
| `tier3_flood` | 3 same-publisher vendor docs agree | NOT `corroborated`; `weakly_corroborated` + `single_publisher` (H1) |
| `vendor_pair` | 2 *distinct*-publisher tier-3 docs agree | `corroborated` but confidence `medium` + `vendor_only` (H2) |
| `null_race` | hostile doc fills null attr first; honest doc follows | value stays, conflict recorded + surfaced (K2) |
| `identity_typo` | same entity_id, different vendor | conflict recorded; no silent conflation (2.5) |
| `baseline_freeride` | fabricated claim names real competitor baseline, no surface form in text | `unbound_baseline` flag (B1) |
| `sidecar_clobber` | same bytes ingested under second doc_id | loud error, first provenance intact (S1) |
| `blob_tamper` | blob bytes rewritten under same filename | `ExtractReport.errors` (S2) |
| `trojan_display` | bidi/zero-width payload in metric + alias | stripped at `report` (2.8) |

Fetcher tests (WS-2b, local HTTP server, zero external network in CI):
http-scheme refusal, redirect-to-http refusal, redirect cap, size-cap abort,
non-PDF magic-byte refusal, rate-limit pacing, idempotent re-fetch, revision
(changed bytes) surfacing E2E. Real-network fetch is validated manually at
rollout — never a CI dependency.

## 4. Files touched

New: `schema/extraction_schema_v4.yaml`, `store/migrations/0004_entity_conflicts.sql`,
`tests/test_hostile.py`, `tests/fixtures/hostile/`, `tests/test_fetch.py`.
Edited: `store/models.py` (bounds + Conflict model), `store/db.py`
(`reconcile_entity` conflict writes, `ClaimView.publisher`, conflict queries),
`store/persist.py` (unchanged contract, conflict pass-through),
`analyze/corroborate.py` (H1/H2, J flag, B1 flag surfacing),
`extract/validate.py` (G1, B1 check, bounds fail-soft),
`ingest/base.py` (S1, S2), `ingest/foundry.py` (real fetcher),
`ingest/pipeline.py` (`run_ingest` wiring, doc_id slug, errors), `cli.py`
(Cf stripping), `config.py`/`config.toml` (document URLs), `CLAUDE.md` +
`docs/ROADMAP.md` (retire resolved Class A lines). Prompt untouched
(`extract_foundry_v1` stays; nothing here changes model-facing text).

## 5. Open decisions the gate must settle (human-owned)

- **K3** — `favored_tier` tier-blind (proposed) vs suspect-excluded. The
  honesty-penalty argument (2.1) is the crux; attack it.
- **H1 axis** — publisher-diversity floor (proposed) vs tier-diversity floor vs
  both. Cost of publisher-only: colluding shell publishers still pass; cost of
  tier-required: legitimate two-vendor confirmation permanently denied.
- **B1** — flag-not-drop for unbound baselines (proposed) vs drop. Cost of flag:
  poisoned comparisons persist (visible); cost of drop: heuristic false
  positives silently delete honest claims.
- **Scope cut** — direct-URL fetch now, HTML discovery to WS-3 (proposed).
- **Conflict record scope (I)** — persisted table (proposed) vs log-only. The
  derive-on-read precedent argues log-only; §2.5 argues the offered value has no
  other home. Settle which principle governs.
