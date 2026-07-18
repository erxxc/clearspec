"""Ingest orchestration — the library entry point behind `semianalyst ingest`.

Iterates the config watchlist and drives the per-source fetchers. Network fetch
is stubbed this phase, so sources are reported as skipped rather than fetched.
Both the CLI and a future web UI call run_ingest().
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config, load_config


@dataclass
class IngestReport:
    fetched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    note: str = ""


def run_ingest(config: Config | None = None) -> IngestReport:
    config = config or load_config()
    report = IngestReport(
        note="network fetch not implemented yet (structure-only phase); "
        "idempotent raw storage is available via ingest.store_raw."
    )
    for source in config.sources:
        # A real fetcher would run here and append new sha256s to report.fetched.
        report.skipped.append(source.name)
    return report
