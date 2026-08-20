# injection-attacker — WS-2a precommit gate (2026-08-18)

**Target:** `docs/reviews/2026-08-18-live-ingest-precommit/workstream.diff` (`git diff
5a8af2c..d6adb94` on `feat/ws2a-trust`), reviewed against the contract in
`docs/reviews/2026-08-18-live-ingest-plan/resolution.md`.

**Verdict: conditional**

**One-line:** The tested PDF-injection surface (grounding, G1/G3, presence-
grounding, Cf-stripping at display, bounded conflict values) is well built and
well tested; the workstream's own new artifact-fold mechanism introduces an
*unauthenticated* second write-path into the store that bypasses every one of
those defenses (grounding, G1, K/G3, sparsity vocabulary) whenever `data/raw/`
receives a file it didn't itself write — and that path is undocumented,
untested, and silently triggered by ordinary `extract`/`forget` runs.

---

## Finding 1 (the risk others will miss) — the extraction artifact is an
unauthenticated trust boundary; anyone who can write to `data/raw/` owns the
derived store, no model call and no grounding required

`run_rebuild` (`src/semianalyst/extract/pipeline.py`) reads every
`*.extraction.json` under `data/raw/` via `read_extraction_artifacts`, groups
them **by the `doc_id` embedded inside the artifact's own JSON**, picks the
winner per `doc_id` by **`_extracted_at`** (also embedded in the same JSON,
also attacker-controlled) with a sha256-lexical tie-break, and replays the
winners straight through `models.Document.model_validate` /
`models.Entity.model_validate` / `models.Claim.model_validate` →
`store.persist_extraction`. None of this touches `validate.py`.

Concretely, that means a party who can drop one file at
`data/raw/<anything>.extraction.json` gets, with **zero LLM call and zero
validate.py enforcement**:

- **No grounding.** `is_grounded`/quote-span substring checking lives only in
  `extract/validate.py`, invoked from `validate_proposal`/`build_result`.
  `run_rebuild` never calls either. CLAUDE.md's own words — "every extracted
  value cites a source span — code-enforced, not trusted to the model" — are
  simply false for anything replayed through the fold.
- **No G1 (alias grounding) / no identity presence-grounding.** Same reason:
  those checks are validate.py functions, not pydantic validators on
  `Entity`/`Claim`, so `model_validate()` never runs them.
- **No sparsity fail-safe.** The pre-WS-2a "fix on `main`" (quote-span
  vocabulary grounding, fail toward suspect) is also a validate.py function.
  A crafted artifact can set `sparsity=false`, `completeness=complete` on a
  totally fabricated number and it will never be re-examined.
- **Arbitrary `source_tier`.** `Document.source_tier` comes straight from the
  artifact's `document` object. An attacker mints a fake `source_tier=1`
  ("conference paper") claim with no conference paper anywhere, which
  directly feeds `favored_tier`, H1's confidence bump, and every corroboration
  weighting decision this whole workstream just hardened.
- **No sidecar cross-check, no S1 protection.** `read_extraction_artifacts`
  globs `.extraction.json` files independently of `.meta.json` sidecars. S1
  (`SidecarCollision`) only guards `write_sidecar`; the artifact fold never
  consults sidecars at all, so a hostile artifact doesn't need to win — or
  even fight — the sidecar-collision defense that was specifically built this
  gate to stop exactly this class of identity theft.
- **Silent supersession of an *already-honest, already-extracted* document.**
  Because the fold key is `doc_id` (attacker-chosen, can equal a real,
  trusted `doc_id`) and the winner is whichever artifact claims the latest
  `_extracted_at`, an attacker can replace a legitimate TSMC document's claims
  outright — not just plant a new hostile competitor entity — by dropping one
  file with a future timestamp. This is a stronger primitive than anything in
  the hostile suite: it is full content replacement of a document the store
  already trusts, not a race for a null attribute.

**Why this matters now, not "later, at WS-2b":** the team clearly *did* think
about adversarial writers to `data/raw/` this same workstream — that's
literally what S2 (blob hash re-verification) defends against, with the note
"matters once WS-2 introduces concurrent/adversarial writers to `data/raw/`."
WS-2a introduces a brand-new file type into that exact directory
(`.extraction.json`) with strictly more destructive potential than a tampered
blob (a tampered blob still has to survive a real model call and
`validate_proposal`; a tampered artifact skips both), and no equivalent
defense, test, or even acknowledgment was written for it. `test_hostile.py`'s
only interaction with a hand-written `.extraction.json` is
`test_malformed_sidecar_is_isolated`, which drops *garbage bytes* to prove
fault isolation — never a well-formed hostile artifact. There is no test
anywhere that asserts a crafted-but-valid artifact is rejected, flagged, or
even noticed.

**This also quietly undercuts a load-bearing claim in the resolution.** The
Outcome section says WS-2b's URL-slug `doc_id` is "now safe because
supersession exists." Supersession *is* the mechanism above. If the artifact
fold has no authentication, "safe because supersession exists" is only true
against accidental revision races, not against anyone who can write to
`data/raw/` — which is precisely the population WS-2b's fetcher will start
letting closer to (redirects, mirrors, cache layers, whatever ends up
between the fetcher and the filesystem).

**Recommendation (small, in-scope):** require `read_extraction_artifacts` /
`run_rebuild` to accept an artifact only if a **sidecar with the same sha256
and a matching `doc_id`** exists in `data/raw/` (the sidecar identity binding
S1 already built). That doesn't make the fold cryptographically sound, but it
forces an attacker to *also* win the sidecar-collision fight instead of
walking around it entirely, and it's a few lines given the pieces already
exist. At minimum this residual must be named in CLAUDE.md's Class-A section
next to S2, with the same "fine for single-writer MVP, matters once WS-2b"
framing — right now it isn't named anywhere.

---

## Finding 2 — casefold-only normalization is the single point of failure for
three separately-marketed defenses (G3, H1, J) at once

`store/db.py:_foreign_surface_forms`/`reconcile_entity` (G3 alias-collision),
`analyze/corroborate.py:_norm_key` (H1 publisher-diversity floor and the
group key), and `_slug_collisions` (J) all normalize attacker-influenceable
free text with **`.casefold()` + whitespace-collapse only**. None apply
Unicode confusable/skeleton normalization (no NFKC, no confusables map).

That means a single technique — swapping one or two Latin letters in
`vendor`/`publisher`/alias text for visually-identical Cyrillic/Greek
homoglyphs (e.g. Latin "a" U+0061 → Cyrillic "а" U+0430) — simultaneously:

- defeats **H1**: two "distinct" tier-3 publishers that are actually the same
  vendor with a homoglyph swap in the `publisher` field read as 2 distinct
  normalized publishers, promoting a single-voice flood to `corroborated`/
  `high` confidence — exactly the attack H1 exists to stop (`tier3_flood` in
  the hostile suite only tests literal-identical and case/whitespace-variant
  publisher strings, never a homoglyph);
- defeats **G3**: an alias that is a homoglyph-perturbed copy of a
  competitor's real name/alias will not match `foreign.casefold()` lookups,
  so it unions cleanly instead of raising `alias_collision` — the exact graft
  `test_alias_graft`/`test_alias_graft_via_new_entity` were written to catch,
  just with one character swapped for a lookalike;
- defeats **J**: `possible_slug_collision`'s surface-form intersection is the
  same casefold set, so a homoglyph-variant name silently fails to flag two
  entities that are, to a human reading `report` output, the same product.

This is not a hypothetical model-output artifact either — `metric`, `unit`,
`vendor`, `name`, and aliases are all attacker-authored free text the model
copies close to verbatim from the hostile PDF, and none of the new v4 bound
types (`Text80`/`Text120`, `_NO_CTRL`) restrict the *script* of characters,
only length and C0/DEL control bytes. A single shared `_confusable_key()`
helper (even a minimal one — casefold + NFKC + a small manual confusables
table for the Latin/Cyrillic/Greek pairs that actually render identically in
a terminal) would close all three at once, since they already funnel through
one function each. As shipped, three independently-reviewed, independently-
tested defenses share one untested blind spot.

---

## Finding 3 — `quote_span`/`stated_caveats` are deliberately unsanitized,
and nothing pins that as an open item the way the (now-closed) display gaps
were

`models.py`'s `Span2000`/`Caveat500` types are length-bounded only — no
`_NO_CTRL`, no Cf stripping possible at ingestion, by design ("verbatim
source text ... may legitimately contain newlines the no-control-chars
pattern would reject"). That's a defensible call for the *value* — but it
means raw ANSI escapes and Unicode Trojan-Source payloads from a hostile PDF
are stored verbatim, forever, in both the DB and the new
`<sha256>.extraction.json` artifacts, under a schema comment that gives no
forward warning.

Today this is inert because `cli.py:report()` never displays `quote_span` or
`stated_caveats` — only `metric`/`baseline_entity`/aliases/conflict values are
wired through `_ansi_safe`. But CLAUDE.md currently reads "every DB-derived
display string ... routes through it," which is not quite true of the field
most likely to be added to a "show me the evidence for this claim" feature
next (a very natural ask once conflicts are surfaced). The previous Unicode-
spoofing gap earned an explicit "OPEN" line in CLAUDE.md before this gate
closed it; this one doesn't get an equivalent line anywhere in the diff, so
the next person to wire citation display has no signal that they need to
route through `_ansi_safe` themselves rather than assume the DB layer already
guarantees it.

---

## What the diff gets right (for the record, not averaged against the above)

`test_trojan_display` genuinely exercises the hardest case in scope: a Cf
payload planted in `conflict.offered_value` *through a real reconcile
refusal*, verified sanitized at the exact `report()` render path — this is
the correct, non-lazy way to test a display-sanitization claim, and it also
correctly proves the ANSI half dies earlier, at pydantic shape, before it
ever reaches display. G1 (alias grounding) and identity presence-grounding
close the sparsity/identity-plant gaps the WS-1 gate named, and the insert-
path G3 gap (`test_alias_graft_via_new_entity`) is exactly the kind of
in-suite-discovered finding a hostile-input suite should be producing. The
`_err_repr` scrub-at-capture (not just at CLI display) is the right
instinct — model/pydantic-error text is genuinely a second injection surface
and this diff treats it as one.

## Note on the API-key / exfil angle specifically

I looked for a live path from a hostile PDF to the `ANTHROPIC_API_KEY` and
did not find one added by this diff: the key is read from the environment by
the SDK, never passed as an argument or interpolated into the prompt
(`extract/base.py`, unchanged by this diff), and error text captured by
`_err_repr` is local-process stdout only (never persisted to the DB, an
artifact, or a log file) — so even if an SDK exception ever echoed request
headers (not something I can confirm without the SDK source), the "leak" stays
on the operator's own terminal, not an external sink. I'm not treating this as
a finding; flagging only because it's the specific angle named in my brief and
I don't want its absence read as "not checked."
