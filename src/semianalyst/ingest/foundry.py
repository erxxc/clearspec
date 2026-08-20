"""Foundry direct-document fetcher — TSMC / Samsung / Intel watchlist sources.

WS-2b scope (gate: docs/reviews/2026-08-18-live-ingest-plan/, plan §1 +
resolution "Outcome" item 3): the operator names each document URL explicitly
in config.toml (`documents = [...]`); crawling newsroom index pages to
DISCOVER documents is scraping fragility that adds zero trust-model coverage
and is deferred to WS-3. Every fetched byte is untrusted — semi-adversarial
vendor marketing is the tool's whole subject — so this module refuses non-PDF
bytes by magic before storing anything, and the transport underneath
(fetch.fetch_url) is https-only at every redirect hop with size/redirect caps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .base import FetchOutcome, SourceRef, store_raw
from .fetch import FetchedDoc, FetchError, fetch_url, looks_like_pdf


class FoundryFetcher:
    """Fetch each explicitly-configured document URL for a source; refuse
    non-PDF magic; store accepted bytes content-addressed.

    `fetch_fn` is the injection seam for tests: it defaults to the real,
    permanently-https-only `fetch_url`, and tests bind fetch._fetch to a
    transport that serves from a local plaintext server BELOW the policy
    boundary (see fetch.py's module docstring) — the policy code under test is
    identical either way. Per-document fault isolation lives here (a
    FetchError or a magic refusal becomes an error OUTCOME; the source's
    remaining documents still fetch); doc_id derivation, sidecars, and
    reporting live in pipeline.run_ingest.
    """

    def __init__(self, fetch_fn: Callable[[str], FetchedDoc] = fetch_url) -> None:
        self._fetch = fetch_fn

    def fetch(
        self, source: SourceRef, raw_dir: Path, *, pace: Callable[[], None]
    ) -> list[FetchOutcome]:
        outcomes: list[FetchOutcome] = []
        for url in source.documents:
            # Rate pacing before every document request (run_ingest owns the
            # interval). Redirect hops WITHIN one fetch_url call are not
            # separately paced — they are one logical fetch, bounded by
            # max_redirects.
            pace()
            try:
                fetched = self._fetch(url)
            except FetchError as exc:
                outcomes.append(FetchOutcome(requested_url=url, error=str(exc)))
                continue
            if not looks_like_pdf(fetched.content):
                # Refused BEFORE store_raw: bytes we will not treat as a
                # document never land content-addressed in data/raw/. Fixed
                # text only — served bytes never enter the reason.
                outcomes.append(
                    FetchOutcome(
                        requested_url=url,
                        final_url=fetched.final_url,
                        error="not a PDF (magic bytes %PDF- missing)",
                    )
                )
                continue
            raw = store_raw(fetched.content, raw_dir)
            outcomes.append(
                FetchOutcome(requested_url=url, final_url=fetched.final_url, raw=raw)
            )
        return outcomes
