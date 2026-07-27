# injection-attacker — WS-1 extract-wiring precommit

**Verdict: CONDITIONAL**

## Angle
Everything that lands on disk or in the DB is hostile until proven otherwise.
I looked for: prompt-injection reaching the model, API-key leakage, and stored
content that corrupts claims or spoofs the human reading `report`. I also
specifically checked whether this diff *quietly* pre-commits the hostile-fetch
future (WS-2) to inheriting a gap it can't see, even though today's trust
boundary (operator-typed sidecars, zero network) is honest about what it defers.

## What I ruled out (stated for completeness, not a finding)
- No new prompt-injection surface: sidecar fields (`doc_id`, `title`,
  `publisher`, `url`, ...) never reach `AnthropicModelClient.complete` — only
  `pdf_to_text(raw)` does, inside the existing `DOC_OPEN`/`DOC_CLOSE` DATA
  delimiter (`src/semianalyst/extract/base.py:46-52`). `_build_document` in
  `pipeline.py` is a pure metadata→pydantic construction; it never touches the
  model call.
- No new key-leak surface: `run_extract`/`ingest_file` don't touch
  `ANTHROPIC_API_KEY` or the model client construction path beyond what already
  existed; `AnthropicExtractor` is still only instantiated when there's pending
  work, unchanged pattern.
- `doc_id` isn't used to construct filesystem paths (blob path comes from the
  sha256 filename, not from sidecar content), so no path traversal via the
  sidecar's `doc_id` field into `data/raw/`.

## Findings (my angle only)

**1. `read_raw_docs` trusts the sidecar FILENAME as the sha256 — it never
recomputes the blob's actual content hash and compares.**
`src/semianalyst/ingest/base.py:86-99`: `sha256 = sidecar.name[:-len(SIDECAR_SUFFIX)]`,
then `blob = raw_dir / sha256` is read and fed straight to the extractor. The
only place a real hash is *computed* is `store_raw` at write time
(`hashlib.sha256(content).hexdigest()`); read time takes the name on faith.
CLAUDE.md's stated guarantee — "a changed hash is a new file... how silent
revisions of the same URL are detected" — is therefore an ingest-time property
only. If the bytes at `data/raw/<sha256>` are ever replaced post-write (bug,
concurrent-write race once WS-2 lands, or direct filesystem tampering) without
the filename changing, `run_extract` will silently extract different content
than what `file_sha256` and every downstream provenance record claim, and
nothing in the pipeline would ever notice or flag it. This is a MVP-scale gap
today (operator-only, single-writer), but the module's own docstring says WS-2's
network fetcher reuses this exact `read_raw_docs` read path unmodified — so the
gap ships forward automatically into a regime with concurrent/adversarial writes
unless it's re-verified before then.

**2. Zero per-document isolation in `run_extract` — one bad sidecar takes down
the whole pending batch.**
`src/semianalyst/extract/pipeline.py:436-445`: `_build_document(rd.meta, ...)`
does `meta["doc_id"]`, `meta["title"]`, `meta["url"]`, `meta["file_sha256"]`,
`meta["ingest_date"]` — plain dict indexing, no `.get`/try, and pydantic
validates `doc_type`/`source_tier` as a hard fail. A single malformed or
incomplete sidecar (missing key, bad enum value, non-int `source_tier` —
nothing here requires malice, a copy-paste typo suffices) raises an uncaught
`KeyError`/`ValidationError` from inside the `for rd in pending:` loop. That
aborts `run_extract` entirely: every doc after the bad one in sorted order is
never attempted, the CLI gets a bare traceback instead of an `ExtractReport`
(`cli.py`'s `extract` command has no exception handling around `run_extract`
the way the old stub-era code did around `NotImplementedError`), and there's no
signal distinguishing "nothing pending" from "crashed halfway through five."
Docs already committed earlier in the same run stay committed (each is its own
`with conn:` block) but that partial success is never reported. One poisoned or
merely-corrupt sidecar file is a full-batch denial of service on extraction.

**3. `write_sidecar` unconditionally overwrites — same bytes, contradictory
identity, no conflict signal.**
`src/semianalyst/ingest/base.py:74-83`: no check that a new `meta` for an
existing `sha256` is consistent with the sidecar already on disk (or with what's
already persisted in the DB under that content). Two `ingest_file` calls over
identical bytes with different `doc_id`/`source_tier`/`title` silently replace
one identity with another. If the first `doc_id` was already extracted, its
on-disk provenance record (the sidecar) is now gone even though its `Document`
row survives in the DB — and the *same bytes* are eligible to be re-extracted
under a second, contradictory `doc_id` on the next `run_extract` (nothing checks
"this content already has a Document under a different id"). This is a sibling
to CLAUDE.md's named "Identity-field conflict" Class A item, but at the sidecar
layer, and it isn't named there or in ROADMAP.md's decision log — a gap in an
otherwise carefully-enumerated deferred list.

## Risk others will miss
`_ansi_safe` (`cli.py:41-50`) only strips ASCII/C1 control and escape bytes
(`\x00-\x1f`, `\x7f-\x9f`, plus the named OSC/CSI patterns). It does nothing
about Unicode bidirectional-override or zero-width characters (U+202E RLO,
U+2066–U+2069, U+200B, U+FEFF, ...) — none of which fall in those byte ranges,
so none of the three regexes touch them. Those are exactly the class of
character a "Trojan-Source"-style attacker embeds in a proposal-controlled
`metric`/`entity_id`/alias/`baseline_entity` to visually reorder or hide text
when a human reads `semianalyst report` in a terminal — no ANSI escape required,
just directional-override codepoints the terminal renders natively. CLAUDE.md
now marks "Report display safety" **RESOLVED** on the strength of `_ansi_safe`;
that closes the escape-sequence half of terminal display safety but not the
Unicode-spoofing half, and nothing in this diff or in ROADMAP.md flags the
closure as partial. Schema-purist and pragmatist-shipper are unlikely to probe
this because it isn't a crash or a schema violation — the string round-trips
just fine; it only lies to the human reading it.

## Reasoning for CONDITIONAL (not BLOCK, not APPROVE)
Nothing here is exploitable by an external adversary *today* — the trust
boundary is honest (operator hand-types every sidecar, zero network, no hostile
PDF can reach `persist_extraction` yet), and I found no new key-leak or
prompt-injection surface. But finding 1 and 2 aren't quarantined by that
boundary the way the manifest implies: this diff's own docstrings declare the
sidecar read path (`read_raw_docs`) and the per-document loop (`run_extract`) as
the exact, unmodified seam WS-2's network fetcher plugs into. That means two
real gaps are being built into the reused seam *now*, under the cover of a
currently-safe trust boundary, without being named in the Class A list the way
every other deferred decision is. Condition: name gaps 1–3 in CLAUDE.md's Class
A list (or fix #2 trivially with a per-document try/except before commit — it's
cheap and doesn't touch the trust-model design gate WS-2 owns), and correct
"Report display safety... RESOLVED" to scope it explicitly to escape sequences,
not Unicode spoofing, so WS-2 doesn't inherit an undocumented false sense of
closure.
