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

# A document's VALIDATED extraction result is retained beside its blob at
# raw_dir/<sha256>.extraction.json (WS-2a gate, Challenge 1). Artifacts +
# sidecars are the source of truth; the SQLite store is a deterministic fold
# over them (extract.run_rebuild) — which is what makes retraction (`forget`)
# and revision supersession offline DB rebuilds instead of model re-calls.
EXTRACTION_SUFFIX = ".extraction.json"


class SidecarCollision(ValueError):
    """Same bytes ingested under a second doc_id (S1). The sidecar is the
    sha256->identity binding; last-write-wins here would silently clobber the
    first ingest's provenance — the sidecar sibling of the identity-field
    conflict. Message is fixed text plus the two doc_ids only."""


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
    is_new: bool = True  # False when ingest found the identical bytes already stored


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
    """Write the provenance sidecar for a stored blob (atomic). A re-write under
    the SAME doc_id is allowed (a metadata refresh for the same identity); a
    DIFFERENT doc_id raises SidecarCollision (S1) — the first ingest's identity
    binding is never silently clobbered. `ingest_file` propagates the collision."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{sha256}{SIDECAR_SUFFIX}"
    if dest.exists():
        try:
            existing = json.loads(dest.read_text()).get("doc_id")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            # An unreadable existing sidecar is evidence, not free space —
            # overwriting it would destroy whatever provenance it carried.
            raise SidecarCollision(
                f"existing sidecar for this content is unreadable "
                f"({type(exc).__name__}); refusing to overwrite it"
            ) from exc
        incoming = meta.get("doc_id")
        if existing != incoming:
            raise SidecarCollision(
                f"content already ingested under doc_id {existing!r}; "
                f"refusing to rebind it to doc_id {incoming!r}"
            )
    tmp = dest.with_name(dest.name + ".partial")  # <sha>.meta.json.partial
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    tmp.replace(dest)
    return dest


def read_raw_docs(raw_dir: Path) -> tuple[list[RawDoc], list[tuple[str, str]]]:
    """Every raw blob that has a provenance sidecar, sorted by sha256 for a stable
    processing order, plus (sha256, reason) integrity failures the caller MUST
    surface. Each blob's sha256 is recomputed at read (S2): the sidecar FILENAME
    is an address, not proof of content — a mismatch (tampered/truncated blob) is
    excluded and reported, never handed to the extractor as if it were the
    ingested bytes. A sidecar whose blob is absent is likewise an error entry,
    not a silent skip."""
    if not raw_dir.exists():
        return [], []
    docs: list[RawDoc] = []
    errors: list[tuple[str, str]] = []
    for sidecar in sorted(raw_dir.glob(f"*{SIDECAR_SUFFIX}")):
        sha256 = sidecar.name[: -len(SIDECAR_SUFFIX)]
        blob = raw_dir / sha256
        if not blob.exists():
            errors.append((sha256, "sidecar present but raw blob missing"))
            continue
        actual = hashlib.sha256(blob.read_bytes()).hexdigest()
        if actual != sha256:
            errors.append((sha256, f"blob hash mismatch: content hashes to {actual[:12]}"))
            continue
        # A corrupt/hand-edited sidecar is that DOCUMENT's failure, never the
        # batch's (appsec, 2026-08-18: an uncaught decode error here crashed the
        # whole extract run — and, via forget's refold, blocked retraction).
        try:
            meta = json.loads(sidecar.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append((sha256, f"unreadable sidecar: {type(exc).__name__}"))
            continue
        docs.append(RawDoc(sha256=sha256, blob_path=blob, meta=meta))
    return docs, errors


@dataclass(frozen=True)
class ExtractionArtifact:
    """A retained extraction result read back for a rebuild. `data` is the JSON
    payload run_extract wrote: document/entities/claims plus the _extracted_at /
    _extracted_against provenance stamps."""

    sha256: str
    path: Path
    data: dict


def extraction_artifact_path(raw_dir: Path, sha256: str) -> Path:
    """Canonical artifact location for a blob. Lives here because this module
    owns the data/raw layout — extract never constructs these paths itself."""
    return raw_dir / f"{sha256}{EXTRACTION_SUFFIX}"


def write_extraction_artifact(raw_dir: Path, sha256: str, artifact: dict) -> Path:
    """Persist a document's validated extraction beside its blob (atomic, like
    the sidecar). Content-addressed by the SOURCE bytes' sha256 — one artifact
    per ingested revision — so the latest-per-doc_id fold (extract.run_rebuild)
    can supersede a revision without re-calling the model."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = extraction_artifact_path(raw_dir, sha256)
    tmp = dest.with_name(dest.name + ".partial")  # <sha>.extraction.json.partial
    tmp.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    tmp.replace(dest)
    return dest


def read_extraction_artifacts(raw_dir: Path) -> tuple[list[ExtractionArtifact], list[tuple[str, str]]]:
    """Every retained extraction artifact, sorted by sha256, plus (sha256, reason)
    errors. An unreadable artifact is reported, never silently dropped — a rebuild
    that quietly lost a document would defeat the fold's guarantee."""
    if not raw_dir.exists():
        return [], []
    artifacts: list[ExtractionArtifact] = []
    errors: list[tuple[str, str]] = []
    for path in sorted(raw_dir.glob(f"*{EXTRACTION_SUFFIX}")):
        sha256 = path.name[: -len(EXTRACTION_SUFFIX)]
        try:
            data = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append((sha256, f"unreadable extraction artifact: {type(exc).__name__}"))
            continue
        artifacts.append(ExtractionArtifact(sha256=sha256, path=path, data=data))
    return artifacts, errors


class Fetcher(Protocol):
    """A source-specific fetcher.

    Implementations turn a SourceRef into raw bytes (HTTP, file, etc.) and use
    `store_raw` to persist them idempotently. Network fetch is not implemented
    this phase — see foundry.py.
    """

    def fetch(self, source: SourceRef) -> Iterable[RawRef]:
        ...
