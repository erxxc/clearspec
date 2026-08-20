# devils-advocate — WS-2b fetcher precommit review

Attacking the three-way "APPROVE WITH CONDITIONS" consensus, not redoing the reviews.

## Attack 1 — schema-purist's own remedy for the doc_id collision doesn't close the hole it names; injection-attacker's slow-loris condition is real but mis-weighted

**Target:** schema-purist Finding #1; injection-attacker Finding #1.

The query-string-collision finding is correctly rated HIGH, not overblown — it's
not a theoretical edge case, it's the same class of harm CLAUDE.md treats as
maximally serious elsewhere ("never overwrite... the race becomes a visible
conflict, never a silent loss"). Here it's worse than an attribute overwrite:
a whole document's claims vanish on refold with zero trace. Silent identity
collapse deserves fail-loud, full stop.

But the purist's proposed remedy (a) — "build the set up front" from
`config.sources` before any fetch — only catches collisions **within one
`ingest` run**. It does nothing for the realistic case: URL `?id=1234` is
configured and fetched today (binds `doc_id`); weeks later an operator adds
`?id=5678` to `config.toml` and runs `ingest` again. Each run builds a fresh
in-memory set; there is no cross-run memory of the first URL. A cheaper fix
that actually closes the gap without touching the DB (ingest stays DB-free,
per CLAUDE.md) already has a precedent sitting right next to the bug:
`write_sidecar`'s S1 check (`src/semianalyst/ingest/base.py:106-132`) scans
`raw_dir` for a sha256-keyed collision before writing. The same file tree
already holds every doc_id binding ever made (one sidecar per sha256, each
carrying `doc_id`) — a doc_id-keyed pass over existing sidecars, run once
before `run_ingest` writes a NEW doc_id under a DIFFERENT sha256, closes both
the in-run and cross-run case, filesystem-only, no migration. Resolution
should require this, not the narrower in-run set the purist described.

Injection-attacker's slow-loris finding (1) is real (verified: `_read_capped`,
`src/semianalyst/ingest/fetch.py:316-342`, re-arms the timeout on every
`resp.read()` call, no `time.monotonic()` anywhere in the file) but the
reviewer's own proposed resolution — "or an explicit written acceptance" — is
sufficient by their own admission. Bundling it into "conditions" alongside a
data-integrity bug overstates its urgency; it's a batch-DoS of the operator's
own tool, cheaply deferrable with a named trigger (see Attack 4).

## Attack 2 — the shared blind spot: `forget` + a re-run of `ingest` resurrects a retracted document, and none of the three reviewers ran `ingest` twice in their heads

**Target:** all three.

All three reviewers evaluated `run_ingest` as a single synchronous batch
operation over a snapshot of `config.toml`. But this diff's entire premise —
rate pacing across a run, an `unchanged` bucket distinct from `fetched`,
idempotent re-fetch — is that `ingest` runs **repeatedly against a persistent
watchlist** (cron, or an operator re-running it). None of the three reasoned
about a SECOND run in the presence of `forget`.

Traced mechanics, verified in code:
- `forget` (`src/semianalyst/ingest/pipeline.py:254-301`) quarantines the
  sidecar + extraction artifact for every sha256 bound to a doc_id, but
  **never touches the raw blob** — `data/raw/<sha256>` stays in place (by
  design, per CLAUDE.md: "blobs stay, content-addressed").
- `store_raw` (`src/semianalyst/ingest/base.py:91-103`) checks `dest.exists()`
  by path alone — it finds the still-present blob and returns
  `is_new=False`, no re-write.
- `write_sidecar` (`base.py:106-132`) only raises `SidecarCollision` when a
  sidecar file **already exists** at that sha256's path with a different
  doc_id. After quarantine, no sidecar exists there — the write is a plain,
  silent create, not a "refresh."
- `run_ingest`'s bucket logic (`pipeline.py:196`) puts this under
  `report.unchanged`, the same bucket used for an utterly ordinary re-fetch —
  nothing distinguishes "unchanged because nothing happened" from "unchanged
  because a forgotten document's content hasn't moved."
- `run_extract`'s classification (`extract/pipeline.py:133`,
  `stored = store.stored_doc_shas(conn)`) is purely DB-derived, with no
  quarantine-awareness. Since `forget`'s refold removed the doc_id from the
  DB, the reborn sidecar reads as **unknown doc_id** — a completely ordinary
  extraction happens, and the next refold puts the document straight back.

Net effect: an operator forgets a document (a deliberate retraction — the tool
even fails loud if the retraction doesn't take), leaves the URL on the
watchlist (the ordinary case — nobody edits `config.toml` as part of running
`forget`), and the **next scheduled `ingest` run silently undoes the
retraction**, reported only as an unremarkable `unchanged` line. CLAUDE.md
calls `forget` "the retraction primitive every flag-terminated defense
resolves into" and requires it to "never report success while retracting
nothing" — this is the mirror-image failure the gate never named: a retraction
that reports success and then quietly un-happens on the very next routine
command. Untested: `tests/test_fetch.py` has zero `forget`/quarantine
coverage (grep confirms), and `test_rebuild.py`/`test_hostile.py`'s forget
tests predate network fetch and never re-run `ingest` afterward.

**Resolution should require:** at minimum, `run_ingest` (or `write_sidecar`)
check the quarantine directory for a doc_id/sha256 match before silently
reviving it, and refuse or loudly flag the revival; at minimum-minimum, this
interaction needs a named test and a documented decision (revive silently by
design, or block and require an explicit un-quarantine command).

## Attack 3 — injection-attacker's SSRF fix conflicts with the diff's own tested architecture

**Target:** injection-attacker Finding #2's proposed resolution, against
schema-purist's and pragmatist's own "boundary purity" praise.

The suggested code fix — "a resolved-address check rejecting
loopback/link-local/RFC1918 ranges at connect time" — would have to live in
`_require_https` (`ingest/fetch.py:292-306`) to run on every hop, since that's
the ONLY policy code above the transport-injection seam (per the module's own
docstring, `fetch.py:219-235`). But every one of the 19 tests in
`test_fetch.py` targets `127.0.0.1` (`_https()`, line ~827) — a loopback
address. An IP-range block placed where it would actually be effective blocks
the entire test suite, not just prod SSRF attempts. The only ways around that
are (a) a test/prod bypass flag — exactly the "`_allow_insecure` flag ... a
production backdoor dressed as a fixture" the module's docstring explicitly
designed against and that injection-attacker's own "solid" section credits as
correct — or (b) moving the check below the transport seam, where it would
never run under test and so could never be verified. This is a real
architectural conflict the reviewer who raised it didn't cross-check against
the reviewer who blessed the boundary it would have to cross. Resolution: this
belongs in the "residual risks accepted" list (CLAUDE.md already carries this
exact shape of risk — S2's blob-hash-only sidecar check, the attacker-writable
`_extracted_at` — bounded by a named trust boundary) with a named trigger, not
a quick patch.

## Attack 4 — scope discipline: several "conditions" are named-trigger deferrals wearing a blocker's clothes

CLAUDE.md's own convention for exactly this situation is a **named trigger**
(H2, B1, controlled-vocabulary, Unicode confusables all follow this pattern) —
not silent deferral, but also not automatic blocking. Sorted by that
convention:
- **Blocking, cheap, uncontroversial:** pragmatist's docs-drift (#1) and
  `rpm` `Field(gt=0)` (#2) — no reviewer disputes these, do them.
- **Blocking, correctness bug:** schema-purist #1's false docstring claim
  (must be corrected regardless of which fix lands) plus a real doc_id-collision
  guard (Attack 1's sharpened version).
- **Should be a NEW blocker the gate missed, not a nice-to-have:** the
  forget/resurrection interaction (Attack 2).
- **Named-trigger deferral, not a blocker:** slow-loris (trigger: "a live run
  demonstrably hangs, or watchlist size makes one stalled host costly");
  SSRF-via-redirect (trigger: matches the existing residual-risk pattern,
  Attack 3); pragmatist's CLI feedback (#3, already self-scoped as
  non-blocking by its own author — the one condition in this gate that
  applied the repo's convention correctly).

## Verdict

APPROVE WITH CONDITIONS is right in outcome, wrong in composition: the swarm's
conditions correctly include one real blocker (doc_id collision, though the
proposed fix is incomplete) and one correctly-scoped deferral (CLI feedback),
but bundle two genuinely optional deferrals (slow-loris, SSRF-via-redirect —
the latter's obvious fix actively conflicts with this diff's own tested
design) at the same urgency as the blocker, and **all three missed the one
finding that should have been a second hard blocker**: `forget` combined with
a re-run of `ingest` silently resurrects a retracted document with no test,
no flag, and no documented decision — a direct, untested collision with this
codebase's own stated invariant that retraction must never silently fail.
