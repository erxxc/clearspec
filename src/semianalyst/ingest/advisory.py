"""Advisory JSON fetcher — curated NVD / GHSA / CISA KEV document URLs (GEI-14).

Curated JSON URLs only: the operator names each document URL in config.toml
(`documents = [...]`). HTML discovery and vendor HTML pages stay deferred.
Transport is the same WS-2b policy engine as FoundryFetcher (`fetch_url` /
`_fetch`): HTTPS-only at every redirect hop, size/redirect caps. Magic check
is JSON (parseable UTF-8 object/array), not `%PDF-`.

parser_role mapping (config `parser_role`, attested via KIND_COMPAT at extract):
  nvd_record  + cna|cpe|catalog|exploit_field
  ghsa        + reviewed|unreviewed|exploit_field
  cisa_kev    + kev

Sidecar stores doc_type + publisher + parser_role — NEVER source_record_kind.
Self-attested kind fields inside the JSON body are inert adversary-controlled
bytes (extract stamps via kind_from_operator_sidecar / attested_kind only).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .base import FetchOutcome, SourceRef, store_raw
from .fetch import FetchedDoc, FetchError, fetch_url, looks_like_json


class AdvisoryJsonFetcher:
    """Fetch each explicitly-configured advisory JSON URL; refuse non-JSON;
    store accepted bytes content-addressed.

    Same `fetch_fn` injection seam as FoundryFetcher: tests bind `_fetch` to a
    local plaintext transport BELOW the HTTPS-only policy boundary.
    """

    def __init__(self, fetch_fn: Callable[[str], FetchedDoc] = fetch_url) -> None:
        self._fetch = fetch_fn

    def fetch(
        self, source: SourceRef, raw_dir: Path, *, pace: Callable[[], None]
    ) -> list[FetchOutcome]:
        outcomes: list[FetchOutcome] = []
        for url in source.documents:
            pace()
            try:
                fetched = self._fetch(url)
            except FetchError as exc:
                outcomes.append(FetchOutcome(requested_url=url, error=str(exc)))
                continue
            if not looks_like_json(fetched.content):
                outcomes.append(
                    FetchOutcome(
                        requested_url=url,
                        final_url=fetched.final_url,
                        error="not JSON (UTF-8 object/array parse failed)",
                    )
                )
                continue
            raw = store_raw(fetched.content, raw_dir)
            outcomes.append(
                FetchOutcome(requested_url=url, final_url=fetched.final_url, raw=raw)
            )
        return outcomes
