"""HTTPS document fetch — the WS-2b transport core (gate: plan §1, resolution
"Outcome" item 3). Stdlib urllib only; no new dependencies.

Design: POLICY and TRANSPORT are separate layers, and that separation is the
test seam. `_fetch` is the policy engine — it validates the scheme of EVERY
URL (the initial one and every redirect hop) BEFORE any bytes move, runs the
manual redirect loop, and enforces the streamed size cap. `_transport` is the
byte-mover: one request, redirects disabled, socket timeout set — mechanically
scheme-agnostic, because the HTTPS-ONLY guarantee deliberately does not live
there. The PUBLIC `fetch_url` binds the policy engine to the real transport
and takes no override: it can never be talked into a non-https request, not
even by a test. Tests inject a transport that rewrites https->http strictly
BELOW the policy boundary and serve from a local plaintext http.server, so the
real scheme checks / redirect loop / caps are what run under test (a local
server cannot present certificates, and an `_allow_insecure` flag on the
public surface would be a production backdoor dressed as a fixture).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_CHUNK = 65536
# Hop URLs come from server-controlled Location headers; when one must appear
# in an error message (the spec: refusals NAME the hop) it is length-bounded
# here, and every display of it goes through cli._ansi_safe like all
# adversary-influenced strings.
_URL_IN_ERR = 200


class FetchError(Exception):
    """A fetch refused or failed. Messages are FIXED TEXT plus a bounded URL
    and, for transport failures, an exception TYPE name — never response-body
    bytes and never server-authored prose (the `_err_repr` precedent:
    server-controlled text does not enter error strings)."""


@dataclass(frozen=True)
class FetchedDoc:
    content: bytes
    final_url: str  # post-redirect URL — recorded in the sidecar for audit


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disable urllib's automatic redirect following: returning None makes
    every 3xx surface as an HTTPError for `_fetch` to inspect. The redirect
    loop is manual so the https-only policy runs at EVERY hop — urllib's
    built-in follower would happily walk a compromised site's bounce to
    http:// before we ever saw the Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _transport(url: str, timeout: float):
    """One request, redirects disabled, socket timeout applied. See the module
    docstring: scheme enforcement lives in `_fetch`, one layer up — this is
    the injectable byte-mover under it."""
    return _OPENER.open(url, timeout=timeout)


def _trunc(url: str) -> str:
    return url if len(url) <= _URL_IN_ERR else url[:_URL_IN_ERR] + "..."


def _require_https(url: str, *, hop: int) -> None:
    """The per-hop scheme gate, run BEFORE the URL reaches any transport. A
    compromised or MITM'd site must not bounce us to http:// (plaintext),
    file:// (local read), or ftp:// — the refusal names the hop so the
    operator can see WHERE a chain went bad."""
    try:
        parts = urlsplit(url)
    except ValueError:
        raise FetchError(f"unparseable URL at hop {hop}: {_trunc(url)}") from None
    if parts.scheme.lower() != "https" or not parts.netloc:
        where = "before any request" if hop == 0 else f"at redirect hop {hop}"
        raise FetchError(
            f"refused non-https URL {where} "
            f"(scheme {parts.scheme.lower() or 'none'!r}): {_trunc(url)}"
        )


def looks_like_pdf(content: bytes) -> bool:
    """Magic-byte check, deliberately separate from transport: a fetched-but-
    not-PDF document is a distinct, precisely-nameable per-document refusal,
    not a transport failure — callers (FoundryFetcher) report it as such."""
    return content.startswith(b"%PDF-")


def _read_capped(resp, max_bytes: int, url: str) -> bytes:
    """Streamed read under the byte cap: abort the moment the cap is exceeded,
    never buffer unbounded. Content-Length is a COURTESY fast-abort only — it
    may lie or be absent, so the streamed count is the enforcement."""
    declared = resp.headers.get("Content-Length") if resp.headers else None
    if declared is not None:
        try:
            declared_n = int(declared)
        except ValueError:
            declared_n = None  # a garbage header is not a verdict either way
        if declared_n is not None and declared_n > max_bytes:
            raise FetchError(
                f"size cap exceeded (declared Content-Length > {max_bytes} bytes): {_trunc(url)}"
            )
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = resp.read(_CHUNK)
        except (TimeoutError, OSError) as exc:
            raise FetchError(f"read failed ({type(exc).__name__}): {_trunc(url)}") from exc
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(f"size cap exceeded (> {max_bytes} bytes streamed): {_trunc(url)}")
        chunks.append(chunk)


def fetch_url(
    url: str,
    *,
    max_bytes: int = 50_000_000,
    max_redirects: int = 5,
    timeout: float = 30.0,
) -> FetchedDoc:
    """Fetch one document over HTTPS — the ONLY public fetch surface.

    HTTPS-only at the initial URL and at every redirect hop; manual redirect
    loop capped at `max_redirects`; streamed read capped at `max_bytes`;
    socket timeout on every request. Permanently bound to the real transport —
    no scheme override, no insecure mode (the test seam is `_fetch`'s
    transport parameter, below the policy boundary; see the module docstring).
    """
    return _fetch(
        url, max_bytes=max_bytes, max_redirects=max_redirects, timeout=timeout,
        transport=_transport,
    )


def _fetch(
    url: str,
    *,
    max_bytes: int,
    max_redirects: int,
    timeout: float,
    transport: Callable[[str, float], object],
) -> FetchedDoc:
    """The policy engine (see module docstring). `transport` moves bytes for
    ONE already-validated URL; everything security-relevant — per-hop scheme
    checks, the redirect walk, both caps — happens here, identically for the
    real transport and a test's."""
    current = url
    # hop 0 is the initial request; hops 1..max_redirects are followed
    # redirects. A redirect off the last permitted request exits the loop.
    for hop in range(max_redirects + 1):
        _require_https(current, hop=hop)
        try:
            resp = transport(current, timeout)
        except urllib.error.HTTPError as err:  # subclasses URLError — catch first
            if err.code in _REDIRECT_CODES:
                location = err.headers.get("Location")
                code = err.code
                err.close()
                if not location:
                    raise FetchError(
                        f"redirect (HTTP {code}) without a Location header: {_trunc(current)}"
                    ) from None
                # Relative Locations resolve against the CURRENT hop's URL
                # (RFC 9110 §10.2.2); the resolved URL is re-validated at the
                # top of the next iteration before any request is made.
                current = urljoin(current, location)
                continue
            code = err.code
            err.close()
            raise FetchError(f"http error status {code}: {_trunc(current)}") from None
        except urllib.error.URLError as exc:
            reason = type(exc.reason).__name__ if exc.reason is not None else type(exc).__name__
            raise FetchError(f"connection failed ({reason}): {_trunc(current)}") from exc
        except (TimeoutError, OSError) as exc:
            raise FetchError(f"connection failed ({type(exc).__name__}): {_trunc(current)}") from exc
        with resp:
            return FetchedDoc(content=_read_capped(resp, max_bytes, current), final_url=current)
    raise FetchError(f"too many redirects (> {max_redirects}): {_trunc(current)}")
