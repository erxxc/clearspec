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

`forget` is the retraction primitive (WS-2a gate, Challenge 1): quarantine a
doc_id's sidecars + extraction artifacts, then refold the store so no trace of
the document remains in derived state.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Config, load_config
from .base import SIDECAR_SUFFIX, RawDoc, extraction_artifact_path, store_raw, write_sidecar

if TYPE_CHECKING:  # runtime import lives inside forget() — see the comment there
    from ..extract.pipeline import RebuildReport

# Retracted files move here (under data_dir), never get deleted: an operator can
# audit what a hostile or wrong document tried to say, or restore it.
QUARANTINE_DIRNAME = "quarantine"


@dataclass
class IngestReport:
    fetched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ForgetReport:
    doc_id: str
    quarantined: list[str] = field(default_factory=list)  # file names now under data/quarantine/
    rebuild: RebuildReport | None = None


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


def _quarantine_dest(quarantine_dir: Path, name: str) -> Path:
    """Never clobber an earlier quarantined file — MOVE-not-delete exists for
    auditability, so a repeat forget of a re-ingested doc gets a numbered sibling
    instead of overwriting the first retraction's evidence."""
    dest = quarantine_dir / name
    n = 1
    while dest.exists():
        dest = quarantine_dir / f"{name}.{n}"
        n += 1
    return dest


def forget(config: Config, doc_id: str) -> ForgetReport:
    """Retract a document: MOVE every sidecar bound to `doc_id` — plus its
    extraction artifact, if retained — into data/quarantine/ (never delete), then
    refold the store (extract.run_rebuild) so no trace of the doc remains in
    derived state. Raw BLOBS stay in data/raw/: they are content-addressed and in
    principle shared; a blob without a sidecar is inert (read_raw_docs never
    yields it, and the rebuild reads artifacts only). An unknown doc_id fails
    loud — a retraction that silently retracted nothing would be worse than an
    error.
    """
    raw_dir = config.paths.raw_dir
    sidecars = sorted(raw_dir.glob(f"*{SIDECAR_SUFFIX}")) if raw_dir.exists() else []
    matches: list[str] = []  # every sha256 bound to doc_id (original + revisions)
    for sidecar in sidecars:
        try:
            meta = json.loads(sidecar.read_text())
        except (OSError, json.JSONDecodeError):
            continue  # unreadable sidecar can't be matched by doc_id; run_extract surfaces it
        if meta.get("doc_id") == doc_id:
            matches.append(sidecar.name[: -len(SIDECAR_SUFFIX)])
    if not matches:
        raise ValueError(f"unknown doc_id: no ingested sidecar is bound to {doc_id!r}")

    quarantine_dir = config.paths.data_dir / QUARANTINE_DIRNAME
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantined: list[str] = []
    for sha256 in matches:
        for path in (raw_dir / f"{sha256}{SIDECAR_SUFFIX}", extraction_artifact_path(raw_dir, sha256)):
            if path.exists():
                dest = _quarantine_dest(quarantine_dir, path.name)
                shutil.move(str(path), str(dest))
                quarantined.append(dest.name)

    # Imported lazily: extract.pipeline imports this package at module load, so a
    # top-level import here would be circular. At call time both are loaded.
    from ..extract.pipeline import run_rebuild

    return ForgetReport(doc_id=doc_id, quarantined=quarantined, rebuild=run_rebuild(config))
