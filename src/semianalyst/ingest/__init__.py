"""ingest — fetch raw releases and store them content-addressed by sha256."""

from .base import (
    EXTRACTION_SUFFIX,
    SIDECAR_SUFFIX,
    ExtractionArtifact,
    Fetcher,
    RawDoc,
    RawRef,
    SidecarCollision,
    SourceRef,
    extraction_artifact_path,
    sidecar_doc_id,
    read_extraction_artifacts,
    read_raw_docs,
    store_raw,
    write_extraction_artifact,
    write_sidecar,
)
from .foundry import FoundryFetcher
from .pipeline import ForgetReport, IngestReport, forget, ingest_file, run_ingest

__all__ = [
    "EXTRACTION_SUFFIX",
    "SIDECAR_SUFFIX",
    "ExtractionArtifact",
    "Fetcher",
    "RawDoc",
    "RawRef",
    "SidecarCollision",
    "SourceRef",
    "extraction_artifact_path",
    "sidecar_doc_id",
    "read_extraction_artifacts",
    "read_raw_docs",
    "store_raw",
    "write_extraction_artifact",
    "write_sidecar",
    "FoundryFetcher",
    "ForgetReport",
    "IngestReport",
    "forget",
    "ingest_file",
    "run_ingest",
]
