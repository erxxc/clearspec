"""Ingest orchestration — the library entry points behind `semianalyst ingest`
and `semianalyst ingest-file`.

`run_ingest` iterates the config watchlist and drives the per-source fetchers.
Network fetch is stubbed this phase (WS-2), so watchlist sources are reported as
skipped rather than fetched.

`ingest_file` is the operator path that works TODAY, with zero network: it stores
a local file content-addressed and writes its provenance sidecar, so `extract`
can pick it up. This keeps the curated-fixture trust boundary — an operator
hand-feeds a document; no hostile document reaches the store. Both the CLI and a
future web UI call these.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config, load_config
from .base import RawDoc, store_raw, write_sidecar


@dataclass
class IngestReport:
    fetched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    note: str = ""


def run_ingest(config: Config | None = None) -> IngestReport:
    config = config or load_config()
    report = IngestReport(
        note="network fetch not implemented yet (WS-2); ingest a local file with "
        "ingest.ingest_file / `semianalyst ingest-file`."
    )
    for source in config.sources:
        # A real fetcher would run here and append new sha256s to report.fetched.
        report.skipped.append(source.name)
    return report


def ingest_file(
    config: Config,
    source_path: str | Path,
    *,
    doc_id: str,
    title: str,
    publisher: str,
    doc_type: str,
    source_tier: int,
    url: str,
    publish_date: str | None = None,
    ingest_date: str | None = None,
) -> RawDoc:
    """Store a local file content-addressed and write its provenance sidecar.

    The (doc_type, source_tier, publish_date) fields are recorded verbatim and
    validated at extract time when the Document is constructed (pydantic) — ingest
    stays decoupled from the store's model. Returns the stored RawDoc.
    """
    content = Path(source_path).read_bytes()
    raw = store_raw(content, config.paths.raw_dir)
    meta = {
        "doc_id": doc_id,
        "title": title,
        "publisher": publisher,
        "doc_type": doc_type,
        "source_tier": source_tier,
        "url": url,
        "publish_date": publish_date,
        "ingest_date": ingest_date or dt.date.today().isoformat(),
        "file_sha256": raw.sha256,
    }
    write_sidecar(config.paths.raw_dir, raw.sha256, meta)
    return RawDoc(sha256=raw.sha256, blob_path=raw.path, meta=meta)
