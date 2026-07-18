"""Foundry announcement fetcher — TSMC / Samsung / Intel newsroom pages.

STUB (this phase): the network fetch, HTML/PDF discovery, and rate limiting are
not implemented yet. The idempotent raw-storage path (base.store_raw) is real
and exercised by tests. When network fetch lands here it must:
  - honour config.rate_limits (requests_per_minute, max_concurrency),
  - validate the URL scheme (https only) before fetching — sources come from
    the operator's config watchlist, but treat fetched content as untrusted,
  - pass fetched bytes through store_raw so re-fetching an unchanged page is a
    no-op and a changed page produces a new sha256 (silent-revision detection).
"""

from __future__ import annotations

from typing import Iterable

from .base import Fetcher, RawRef, SourceRef


class FoundryFetcher(Fetcher):
    """Fetches foundry announcement pages. Not yet implemented."""

    def fetch(self, source: SourceRef) -> Iterable[RawRef]:
        raise NotImplementedError(
            "Foundry network fetch is not implemented yet (structure-only phase). "
            "Idempotent raw storage is available via ingest.base.store_raw."
        )
