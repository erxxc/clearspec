"""Fetcher interface + content-addressed raw storage.

Raw documents live on the filesystem under data/raw/, keyed by the sha256 of
their bytes. This is deliberately NOT in SQLite — the store module owns the
database; raw blobs are ingest's concern. Content-addressing gives idempotency
for free: the same bytes always land at the same path, and re-fetching an
unchanged document is a no-op. A changed hash is a new file, which is exactly
how the schema's `file_sha256` detects silent revisions of the same URL.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

# A raw blob is stored at raw_dir/<sha256> (no suffix). Its provenance sidecar —
# the metadata needed to build a Document at extract time — lives beside it at
# raw_dir/<sha256>.meta.json. The sidecar is the ingest->extract handoff seam:
# whatever produced the bytes (an operator today, a network fetcher in WS-2)
# writes the SAME sidecar shape, so extract stays fetch-source-agnostic.
SIDECAR_SUFFIX = ".meta.json"


@dataclass(frozen=True)
class SourceRef:
    """A source to fetch, as described in the config watchlist."""

    name: str
    url: str
    doc_type: str
    source_tier: int


@dataclass(frozen=True)
class RawRef:
    """The result of storing a raw document."""

    sha256: str
    path: Path
    is_new: bool  # False when the identical bytes were already stored (idempotent no-op)


@dataclass(frozen=True)
class RawDoc:
    """A stored raw blob paired with the provenance metadata that lets extract
    reconstruct its Document. `meta` carries exactly the Document-construction
    fields ingest knows (doc_id, title, publisher, doc_type, source_tier, url,
    publish_date, ingest_date, file_sha256) — NOT extraction_model, which extract
    stamps once a run happens."""

    sha256: str
    blob_path: Path
    meta: dict


def store_raw(content: bytes, raw_dir: Path) -> RawRef:
    """Store bytes content-addressed under raw_dir. Idempotent by sha256."""
    digest = hashlib.sha256(content).hexdigest()
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / digest
    if dest.exists():
        return RawRef(sha256=digest, path=dest, is_new=False)
    # Write atomically so a crash mid-write never leaves a truncated blob under
    # a hash that claims to be complete.
    tmp = dest.with_suffix(".partial")
    tmp.write_bytes(content)
    tmp.replace(dest)
    return RawRef(sha256=digest, path=dest, is_new=True)


def write_sidecar(raw_dir: Path, sha256: str, meta: dict) -> Path:
    """Write the provenance sidecar for a stored blob (atomic). Overwrites an
    existing sidecar: the blob is content-addressed, so identical bytes always map
    to the same doc metadata for a given ingest — re-writing is a safe no-op-ish."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{sha256}{SIDECAR_SUFFIX}"
    tmp = dest.with_name(dest.name + ".partial")  # <sha>.meta.json.partial
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    tmp.replace(dest)
    return dest


def read_raw_docs(raw_dir: Path) -> list[RawDoc]:
    """Every raw blob that has a provenance sidecar, sorted by sha256 for a stable
    processing order. A sidecar whose blob is absent (a corrupt/partial state) is
    skipped — it is not an ingested document."""
    if not raw_dir.exists():
        return []
    docs: list[RawDoc] = []
    for sidecar in sorted(raw_dir.glob(f"*{SIDECAR_SUFFIX}")):
        sha256 = sidecar.name[: -len(SIDECAR_SUFFIX)]
        blob = raw_dir / sha256
        if not blob.exists():
            continue
        docs.append(RawDoc(sha256=sha256, blob_path=blob, meta=json.loads(sidecar.read_text())))
    return docs


class Fetcher(Protocol):
    """A source-specific fetcher.

    Implementations turn a SourceRef into raw bytes (HTTP, file, etc.) and use
    `store_raw` to persist them idempotently. Network fetch is not implemented
    this phase — see foundry.py.
    """

    def fetch(self, source: SourceRef) -> Iterable[RawRef]:
        ...
