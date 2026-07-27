"""ingest — fetch raw releases and store them content-addressed by sha256."""

from .base import (
    Fetcher,
    RawDoc,
    RawRef,
    SourceRef,
    read_raw_docs,
    store_raw,
    write_sidecar,
)
from .foundry import FoundryFetcher
from .pipeline import IngestReport, ingest_file, run_ingest

__all__ = [
    "Fetcher",
    "RawDoc",
    "RawRef",
    "SourceRef",
    "read_raw_docs",
    "store_raw",
    "write_sidecar",
    "FoundryFetcher",
    "IngestReport",
    "ingest_file",
    "run_ingest",
]
