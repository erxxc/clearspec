"""Watchlist fetcher — routes foundry PDF vs advisory JSON by doc_type (GEI-14).

Foundry announcements keep PDF magic; curated NVD/GHSA/CISA KEV sources use
AdvisoryJsonFetcher. Both share the same `fetch_fn` (WS-2b policy). HTML
discovery / vendor pages are not routed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..store.attestation import KIND_COMPAT
from .advisory import AdvisoryJsonFetcher
from .base import FetchOutcome, SourceRef
from .fetch import FetchedDoc, fetch_url
from .foundry import FoundryFetcher

_ADVISORY_DOC_TYPES = frozenset(key[0] for key in KIND_COMPAT)


class WatchlistFetcher:
    """Dispatch FoundryFetcher vs AdvisoryJsonFetcher from source.doc_type."""

    def __init__(self, fetch_fn: Callable[[str], FetchedDoc] = fetch_url) -> None:
        self._foundry = FoundryFetcher(fetch_fn=fetch_fn)
        self._advisory = AdvisoryJsonFetcher(fetch_fn=fetch_fn)

    def fetch(
        self, source: SourceRef, raw_dir: Path, *, pace: Callable[[], None]
    ) -> list[FetchOutcome]:
        if source.doc_type in _ADVISORY_DOC_TYPES:
            return self._advisory.fetch(source, raw_dir, pace=pace)
        return self._foundry.fetch(source, raw_dir, pace=pace)
