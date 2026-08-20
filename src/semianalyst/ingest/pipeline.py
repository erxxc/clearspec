"""Ingest orchestration — the library entry points behind `semianalyst ingest`
and `semianalyst ingest-file`.

`run_ingest` (WS-2b, live) iterates the config watchlist and drives the
per-source fetchers over each source's explicitly-configured document URLs:
fetch (https-only, capped), magic-check, store content-addressed, write the
provenance sidecar — the same sidecar shape `ingest_file` writes, so extract
stays fetch-source-agnostic (CLAUDE.md, sidecar-handoff). Sources without a
`documents` list are skipped: HTML discovery of documents from index pages is
WS-3.

`ingest_file` is the operator path: it stores a local file content-addressed
and writes its provenance sidecar, so `extract` can pick it up. Both the CLI
and a future web UI call these.

`forget` is the retraction primitive (WS-2a gate, Challenge 1): quarantine a
doc_id's sidecars + extraction artifacts, then refold the store so no trace of
the document remains in derived state.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlsplit

from ..config import Config, load_config
from .base import (
    SIDECAR_SUFFIX,
    Fetcher,
    RawDoc,
    SidecarCollision,
    SourceRef,
    extraction_artifact_path,
    store_raw,
    write_sidecar,
)
from .foundry import FoundryFetcher

if TYPE_CHECKING:  # runtime import lives inside forget() — see the comment there
    from ..extract.pipeline import RebuildReport

# Retracted files move here (under data_dir), never get deleted: an operator can
# audit what a hostile or wrong document tried to say, or restore it.
QUARANTINE_DIRNAME = "quarantine"


@dataclass
class IngestReport:
    fetched: list[str] = field(default_factory=list)    # doc_ids whose bytes are NEW in data/raw/ (first fetch OR a revision)
    unchanged: list[str] = field(default_factory=list)  # identical bytes re-fetched — the honest no-op, distinct from fetched
    skipped: list[str] = field(default_factory=list)    # sources with no documents configured (HTML discovery: WS-3)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (requested_url|doc_id, fixed reason) — per-doc isolation
    note: str = ""


@dataclass
class ForgetReport:
    doc_id: str
    quarantined: list[str] = field(default_factory=list)  # file names now under data/quarantine/
    rebuild: RebuildReport | None = None


# doc_id slug geometry: 111 + 1 ('_') + 8 (hash) = 120, DocId120's max length.
_SLUG_MAX = 111
_SLUG_HASH_LEN = 8


def url_doc_id(url: str) -> str:
    """Deterministic doc_id for a fetched document: host+path of the REQUESTED
    URL, lowercased, runs of non-[a-z0-9] collapsed to '_', stripped; when that
    exceeds 111 chars it is truncated and suffixed with '_' + sha256(url)[:8]
    so two long URLs sharing a prefix stay distinct (120 chars total — exactly
    DocId120's bound, whose charset permits '_').

    Identity is the OPERATOR-TYPED (requested) URL, never the post-redirect
    final one: the redirect target is server-controlled and can change per
    fetch, so keying identity on it would let a hostile or flaky server mint a
    fresh doc_id on every fetch (each revision arrives as a "new" document,
    defeating same-doc_id supersession) or steer two watchlist entries onto
    one doc_id. URL = identity, content = version (plan §1); the final URL is
    still recorded in the sidecar for audit. Distinct short URLs that slug
    identically are an accepted residual surfaced by analyze's
    `possible_slug_collision` advisory (J), never silently merged bytes —
    each revision is its own blob + sidecar.
    """
    parts = urlsplit(url)
    slug = re.sub(r"[^a-z0-9]+", "_", f"{parts.netloc}{parts.path}".lower()).strip("_")
    if len(slug) > _SLUG_MAX:
        digest = hashlib.sha256(url.encode()).hexdigest()[:_SLUG_HASH_LEN]
        slug = f"{slug[:_SLUG_MAX]}_{digest}"
    # A URL with an empty host+path slug can't happen for a fetchable https URL
    # (the fetcher requires a netloc), but fail toward a valid, deterministic
    # id rather than an empty string DocId120 would reject.
    return slug or f"doc_{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def _url_title(url: str) -> str:
    """Display title from the requested URL's path basename — display data,
    not identity — bounded to Document.title's 300 chars. The requested URL is
    operator-typed config, so no charset scrub is needed here; pydantic still
    fail-louds on control bytes at extract time."""
    name = PurePosixPath(urlsplit(url).path).name
    return (name or url_doc_id(url))[:300]


def run_ingest(
    config: Config | None = None,
    *,
    fetcher: Fetcher | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> IngestReport:
    """Fetch every explicitly-configured document URL on the watchlist and
    write the same provenance sidecar shape `ingest_file` writes.

    Rate pacing: fetching is SEQUENTIAL with a min-interval sleep of
    60/requests_per_minute seconds between consecutive requests, shared across
    all sources in the run. Sequential execution honors any max_concurrency
    >= 1 (a single in-flight request never exceeds a concurrency budget).
    `sleeper` is injectable so tests record the pacing instead of sleeping.

    Fault isolation mirrors ExtractReport: a FetchError, a non-PDF magic
    refusal, or a SidecarCollision lands in `errors` and the batch continues.

    A changed-bytes re-fetch of a known URL needs NO special handling here:
    store_raw content-addresses the new bytes as a new blob, the sidecar binds
    the same doc_id (same requested URL) to the new sha, and run_extract's
    revision path (extract + refold supersession) does the rest.
    """
    config = config or load_config()
    fetcher = fetcher or FoundryFetcher()
    report = IngestReport()

    rpm = config.rate_limits.requests_per_minute
    if rpm <= 0:
        # Fail loud, never reinterpret: rounding 0 up to some rate would fetch
        # FASTER than the operator configured — the wrong fail direction.
        raise ValueError("rate_limits.requests_per_minute must be positive to fetch")
    interval = 60.0 / rpm
    requested_before = False  # no sleep before the run's very first request

    def pace() -> None:
        nonlocal requested_before
        if requested_before:
            sleeper(interval)
        requested_before = True

    today = dt.date.today().isoformat()
    for source in config.sources:
        if not source.documents:
            # Direct-URL scope (gate, plan §1): a source carrying only an
            # index-page url has nothing fetchable until WS-3's HTML discovery.
            report.skipped.append(source.name)
            continue
        ref = SourceRef(
            name=source.name, url=source.url, doc_type=source.doc_type,
            source_tier=source.source_tier, publisher=source.publisher,
            documents=source.documents,
        )
        for outcome in fetcher.fetch(ref, config.paths.raw_dir, pace=pace):
            if outcome.error is not None or outcome.raw is None:
                report.errors.append(
                    (outcome.requested_url, outcome.error or "fetcher returned no blob")
                )
                continue
            doc_id = url_doc_id(outcome.requested_url)
            meta = {
                "doc_id": doc_id,
                "title": _url_title(outcome.requested_url),
                # doc_type/source_tier/publisher are operator-trusted config;
                # publisher falls back to the source's display name.
                "publisher": source.publisher or source.name,
                "doc_type": source.doc_type,
                "source_tier": source.source_tier,
                # The FINAL post-redirect URL, recorded for audit; identity
                # stays keyed on the requested URL (url_doc_id above).
                "url": outcome.final_url,
                "publish_date": None,  # unknown — never guessed from untrusted headers
                "ingest_date": today,
                "file_sha256": outcome.raw.sha256,
            }
            try:
                write_sidecar(config.paths.raw_dir, outcome.raw.sha256, meta)
            except SidecarCollision as exc:
                # S1: these bytes are already bound to another doc_id — the
                # first ingest's provenance wins; this URL's claim is refused.
                report.errors.append((doc_id, str(exc)))
                continue
            (report.fetched if outcome.raw.is_new else report.unchanged).append(doc_id)

    if report.skipped:
        report.note = (
            "skipped source(s) have no `documents = [...]` URLs configured — "
            "direct document URLs only this phase; HTML discovery is WS-3."
        )
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
    return RawDoc(sha256=raw.sha256, blob_path=raw.path, meta=meta, is_new=raw.is_new)


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

    rebuild = run_rebuild(config)
    # Post-condition: retraction that did not retract is a hard failure, never a
    # success report (precommit gate, devils-advocate §3 — an orphaned or
    # resurrected artifact must not silently survive the refold).
    if doc_id in rebuild.folded:
        raise RuntimeError(
            f"retraction failed: {doc_id!r} survived the refold — an artifact for "
            f"it still folds; inspect data/raw/ and quarantine it manually"
        )
    return ForgetReport(doc_id=doc_id, quarantined=quarantined, rebuild=rebuild)
