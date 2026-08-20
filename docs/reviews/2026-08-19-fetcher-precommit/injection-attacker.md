# injection-attacker — WS-2b fetcher precommit review

**Verdict: APPROVE WITH CONDITIONS**

## Scope note
This diff has no LLM/prompt surface — `fetch.py`'s PDF check is a fixed 5-byte
prefix compare (`looks_like_pdf`), never parsed as PDF structure, and no API
key or model call is reachable from any code path in this diff. Embedded
PDF instructions cannot alter fetcher behavior or reach `ANTHROPIC_API_KEY`
here — that risk lives entirely in `extract/`, out of this diff's scope. My
findings below are about what a hostile SERVER (not a hostile document body)
can do to the fetch/ingest pipeline.

## What I verified as solid (no bypass found)
- Per-hop scheme gate runs BEFORE every transport call, including redirect
  hops (`_fetch`'s loop: `_require_https(current, hop=hop)` precedes
  `transport(current, timeout)`), confirmed against `test_redirect_to_http_
  refused_mid_chain` — a mid-chain downgrade to `http://` is refused and the
  downgraded URL is never requested (`server.hits == ["/bounce"]`).
- Scheme-relative (`https:evil` with no `//`) and malformed Locations are
  caught by `not parts.netloc` / the `ValueError` catch in `_require_https`.
- Redirect cap is exact (6 requests = initial + 5 followed hops), verified
  against `test_redirect_cap_enforced`.
- `doc_id` derives from the OPERATOR-typed `requested_url`, never
  `final_url` — a hostile/compromised server cannot steer identity or force
  ping-pong doc_id churn via redirects (`pipeline.url_doc_id` docstring +
  code, confirmed).
- Error strings sent to the terminal (`report.errors`) are fixed text plus a
  200-char-truncated URL (`fetch._trunc`), and every echo in `cli.ingest()`
  routes both key and reason through `_ansi_safe`.

## Findings

**1. [MEDIUM] No wall-clock deadline on a single fetch — slow-loris trickle
can hang `run_ingest` indefinitely.**
`_read_capped` (`src/semianalyst/ingest/fetch.py:316-342`) and `_fetch`
(`:366-409`) enforce a byte-count cap and a per-socket-operation `timeout`,
but never track elapsed wall-clock time. Python's `timeout` on
`_OPENER.open`/`resp.read()` re-arms on every individual read: a hostile or
compromised watchlist host that trickles ~1 byte every `timeout - ε` seconds
never triggers a single read timeout, and there is no total-duration check
anywhere in the call chain. `run_ingest` fetches sequentially (`pipeline.py`
`pace()` gates each document), so one such connection blocks the entire
batch — every other configured source's documents wait behind it — for as
long as the attacker wants to hold the socket open, up to the 50MB cap.
Verified in code (no `time.monotonic()`/deadline tracking exists in
`fetch.py`); the trickle mechanics follow from documented stdlib socket
timeout semantics, not executed live in this review.
What would satisfy me: track elapsed time from the start of `_fetch` (or
per-hop) and abort with `FetchError` past a `max_duration`, independent of
the per-read `timeout` — or an explicit, written acceptance that a single
slow host can stall an entire ingest run (this is a batch-DoS of the
operator's own tool, not data corruption, so REJECT is not warranted, but
it should be a conscious choice, not a gap).

**2. [MEDIUM] SSRF-via-redirect to internal/link-local addresses is not
addressed by HTTPS-only-per-hop, and I could not find it named as an
accepted residual for WS-2b specifically.**
`_require_https` validates URL *scheme*, never the resolved IP. TLS
hostname verification checks the cert's SAN against the redirect target's
*hostname*, not the address actually connected to — classic DNS-rebinding
SSRF (attacker/compromised host redirects, via a normal 30x, to a hostname
it controls that resolves to `169.254.169.254` or an RFC1918 address; if a
cloud metadata endpoint or internal service responds with `%PDF-...` magic
bytes, that response is stored content-addressed and later extracted as if
it were vendor content — a path from SSRF to fabricated foundry claims, not
just recon). I read `docs/reviews/2026-08-18-live-ingest-plan/resolution.md`
Outcome §3 for WS-2b's contract; it names https-only/caps/magic-bytes/rate
limits/URL-slug doc_id but does not call out internal-address reachability.
This is squarely the "SSRF residual" my brief asked me to classify, and I
could not confirm it's knowingly accepted — flagging as a gap rather than
re-litigating a settled decision.
What would satisfy me: either an explicit written acceptance (operator-
curated watchlist is the stated trust boundary elsewhere in this codebase,
so this may well be intentional — CLAUDE.md's "residual risks accepted at
the gate" pattern is the right home for it), or a resolved-address check
rejecting loopback/link-local/RFC1918 ranges at connect time.

**3. [INFO/LOW, my angle specifically — risk other reviewers will likely
miss] `Document.url` newly becomes genuinely adversary-authored content, but
CLAUDE.md's display-safety guarantee doesn't name it.**
Before WS-2b, `Document.url` was populated only via `ingest_file`'s
operator-typed `--url` flag. After this diff, `pipeline.py` sets
`meta["url"] = outcome.final_url` — the post-redirect URL taken directly
from a server's `Location` header chain, i.e. fully server-controlled, the
same trust class as `quote_span`/`stated_caveats`. `Document.url` is typed
`Text2000` (`store/models.py:139`), whose `_NO_CTRL` pattern blocks only
C0/DEL — it does NOT strip Unicode category-Cf codepoints (bidi overrides,
zero-width — the Trojan-Source class), which per CLAUDE.md is deliberately
left to display-time `_ansi_safe`, not the model layer. I verified
`cli.report()` does not display `Document.url` today, so there is no live
bypass. But CLAUDE.md's explicit "OPEN" note — "any future evidence-display
feature MUST route [quote_span/stated_caveats] through `_ansi_safe`" —
names only those two fields. `final_url` is exactly the kind of thing an
audit-trail display feature would show next (that's its stated purpose:
"recorded in the sidecar for audit"), and whoever adds that feature has no
documented reminder that `url` needs the same treatment. This is a
documentation-scope gap, not a code bug.
What would satisfy me: add `Document.url` (and any other sidecar field now
populated from `final_url`/redirect data) to CLAUDE.md's OPEN-display-safety
note, so the guarantee's scope tracks the trust-class change this diff
introduces.

## Not flagged as findings (checked, judged acceptable)
- PDF magic check runs after the full (capped) download completes rather
  than short-circuiting on the first bytes — wastes bandwidth up to the
  cap on non-PDF responses but is bounded by the same 50MB cap and never
  stores the bytes; not a security bypass.
- doc_id slug collisions / S1 sidecar collisions on identical hostile bytes:
  tested (`test_sidecar_collision_isolated`) and behave correctly — first
  binding wins, refusal is per-document, batch continues.
