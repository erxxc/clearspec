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
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


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


class Fetcher(Protocol):
    """A source-specific fetcher.

    Implementations turn a SourceRef into raw bytes (HTTP, file, etc.) and use
    `store_raw` to persist them idempotently. Network fetch is not implemented
    this phase — see foundry.py.
    """

    def fetch(self, source: SourceRef) -> Iterable[RawRef]:
        ...
