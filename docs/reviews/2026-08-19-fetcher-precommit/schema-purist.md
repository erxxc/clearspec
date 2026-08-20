# schema-purist — WS-2b fetcher precommit review

**Verdict: APPROVE WITH CONDITIONS**

Angle: structural/shape integrity and boundary purity. Verified against
`workstream.diff` (git diff 42a81ff..4d0547e) plus targeted reads of
`ingest/base.py` (SidecarCollision/write_sidecar) and `analyze/corroborate.py`
(possible_slug_collision) to check a specific claim made in the diff's own
comments.

## Findings

### 1. HIGH — doc_id collision across distinct-content URLs has NO safety net; the code's claimed mitigation is factually wrong

`ingest/pipeline.py` `url_doc_id()` slugs `netloc+path` only — query strings,
fragments, and case are dropped (confirmed by the diff's own test:
`test_url_doc_id_slug` asserts `url_doc_id("https://a.com/x.pdf?v=2") ==
url_doc_id("https://a.com/x.pdf")`). The docstring claims this is covered:

> "Distinct short URLs that slug identically are an accepted residual
> surfaced by analyze's `possible_slug_collision` advisory (J)"
> (`ingest/pipeline.py:602-605`)

This is false. I checked `analyze/corroborate.py:247-251`:
`possible_slug_collision` runs `_slug_collisions(entities_detail)` — it flags
colliding **entity** name/vendor slugs (schema entities like "TSMC" vs
"tsmc "), not document `doc_id`s. There is no J-equivalent check anywhere for
doc_id collisions.

Walking the actual consequence: two `source.documents` entries whose URLs
differ only by query string (`?v=1` vs `?v=2`, or any CMS using
`?id=1234`/`?id=5678` — a realistic shape for the TSMC/Samsung/Intel targets
this workstream names) fetch **different bytes**, get **different sha256**,
and each gets its own sidecar file (`write_sidecar`'s `SidecarCollision`, per
`ingest/base.py:106-128`, only guards *same-sha256, different-doc_id* — it
never checks sha256-B's sidecar against sha256-A's claimed doc_id). Both
sidecars validly write, both bind to the **same** `doc_id`. Per CLAUDE.md,
`run_extract`/the artifact fold then treat this as an honest same-doc_id
revision and **supersede** — the second document silently discards the
first's claims from the store on refold. No error, no flag, no log line: two
genuinely distinct documents collapse into one identity, and it looks exactly
like a normal, honest revision.

Today's `config.toml` has zero active `documents` entries so this is latent,
not live — but the fetcher is the general-purpose mechanism this whole
workstream ships, and the false safety-net claim will mislead whoever adds
the first multi-document source.

**What would satisfy me:** either (a) fail loud / advisory-flag when two
distinct `source.documents` entries in one run slug to the same doc_id before
any fetch happens (cheap: build the set up front), or (b) stop relying on
lossy host+path slugging for identity — include a stable hash of the full
requested URL (path+query) in the slug unconditionally, not only past the
111-char truncation threshold. At minimum, fix the docstring: it currently
cites protection that does not exist.

### 2. MED — `FetchOutcome`'s "never both" invariant is convention, not enforced; `IngestReport.errors` mixes two key semantics in one untyped field

`FetchOutcome` (`ingest/base.py:168-180`) is documented as "success XOR
error, never both," but it's a plain frozen dataclass with no
`__post_init__` check — nothing stops a future call site from constructing
`FetchOutcome(raw=..., error=...)` and having it pass silently. The one
consuming site doesn't trust the XOR either:
`if outcome.error is not None or outcome.raw is None:` (`pipeline.py:169`)
checks both fields independently rather than treating `error is not None` as
sufficient — proof the invariant isn't actually relied on as a guarantee.
This project's stated philosophy is "code-enforced, not trusted to the
model" for citation grounding; the same discipline should apply to its own
dataclass contracts.

Separately, `IngestReport.errors: list[tuple[str, str]]` (`pipeline.py:60`)
holds `requested_url` as the first element for fetch/magic-refusal errors
(`pipeline.py:172-174`) but `doc_id` for `SidecarCollision` errors
(`pipeline.py:191-194`) — same field, same type, two different meanings, no
discriminator. `cli.py`'s consumer (`for key, reason in report.errors:`)
prints whichever it gets with no way to tell which kind it is. Tests pin
both behaviors (`test_fetch_error_isolated` asserts `key == missing_url`;
`test_sidecar_collision_isolated` asserts `key == url_doc_id(url_dup)`) so
this is intentional, but it's exactly the kind of "assume the field means
one thing" trap this project's own error-key-typing discipline elsewhere
tries to avoid.

**What would satisfy me:** a `__post_init__` assertion on `FetchOutcome`
(cheap, closes the gap for good); for `errors`, either split into
`fetch_errors`/`sidecar_errors` or wrap the tuple in a small named type with
an explicit `key_kind: Literal["url","doc_id"]` field.

### 3. INFO — sidecar `url` field semantics diverge by producer, and the true requested-URL identity has no durable exact record

Confirmed by reading `ingest_file` (`pipeline.py:206-239`, not in this diff):
its `url` field is the operator-supplied canonical URL, verbatim.
`run_ingest`'s sidecar (`pipeline.py:184`) puts the **final, post-redirect**
URL in the same field — server-influenced, since a compromised site's
redirect chain determines it (mitigated only by the https-only per-hop
check, which stops scheme downgrade, not target-domain steering within
https). The field-set itself stays exactly the canonical 9 keys (doc_id,
title, publisher, doc_type, source_tier, url, publish_date, ingest_date,
file_sha256) — I checked field-for-field against `ingest_file`'s dict and
they match in name and order, so this is *not* a shape violation under
CLAUDE.md's "no more, no less" contract. But the full `requested_url` (which
is the actual identity input to `url_doc_id`, including the query string the
slug drops) is persisted nowhere verbatim — only recoverable lossily by
reversing a slug that has already discarded query/case/fragment. This
compounds finding #1: there's no field an operator or auditor can read to
recover exactly which configured URL produced a given doc_id.

**What would satisfy me:** this is documented in-code (the diff's comments
are honest about the tradeoff) so I'm not blocking on it, but CLAUDE.md's
sidecar-handoff section should gain a line noting `url` means "final URL for
network-fetched docs, operator-supplied URL for local ingest" the next time
that section is touched.

## Passed checks (no defect found)
- Sidecar field set is exact-match, field-for-field, both producers — no
  extra/missing keys.
- `doc_id` first-char class, charset, and 111+1+8=120 truncation arithmetic
  are all correct and match `DocId120`; the empty-slug fallback path is
  unreachable on the success path (netloc is validated non-empty by
  `_require_https` before doc_id is ever computed).
- `Source.documents: tuple[str, ...]` matches `SourceRef.documents`'s type
  exactly; `publisher` fallback to `name` is a single site
  (`pipeline.py:187`).
- Boundary purity holds: no `store`/`sqlite3` import anywhere in this diff;
  `fetch.py` is stdlib-only; policy (`_require_https`, redirect loop, caps)
  stays in `fetch.py` and does not leak into `foundry.py`; `cli.py` changes
  are display-only (report formatting through `_ansi_safe`), zero business
  logic added.
- No schema/migration/prompt files touched.

## Risk others will miss
The false-safety-net comment (finding #1) is the one to flag loudest to the
other reviewers: it's not just a missing check, it's a check that the code
*believes* exists, cross-referencing a real mechanism (J) that solves a
different problem. That's the dangerous kind of gap — it will not get
rediscovered by someone reading the docstring, only by someone who chases
the cross-reference the way I just did.
