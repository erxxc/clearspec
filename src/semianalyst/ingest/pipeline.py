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

GEI-11: operator ingest accepts advisory JSON/PDF. Kind is attested via
`attested_kind(doc_type, parser_role)` / KIND_COMPAT only — never copied from
sidecar or advisory JSON (`source_record_kind` / `ghsa_reviewed` / `cisa_kev`
/ `nvd_cna` are adversary-controlled). HTTPS-only is N/A on this path.

GEI-14: curated NVD/GHSA/CISA KEV JSON URLs on the watchlist use the same
WS-2b fetch policy (HTTPS-only hops, caps) via WatchlistFetcher /
AdvisoryJsonFetcher. Sidecar gets parser_role; identity uses identity_doc_id
so NVD CNA vs CPE stay distinct. source_record_kind is never written to the
sidecar — extract stamps via attested_kind. HTML discovery stays deferred.
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
from ..store.attestation import KIND_COMPAT, attested_kind, identity_material
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
from .watchlist import WatchlistFetcher

if TYPE_CHECKING:  # runtime import lives inside forget() — see the comment there
    from ..extract.pipeline import RebuildReport

# Retracted files move here (under data_dir), never get deleted: an operator can
# audit what a hostile or wrong document tried to say, or restore it.
QUARANTINE_DIRNAME = "quarantine"

# doc_types that require operator parser_role and KIND_COMPAT attestation.
ADVISORY_DOC_TYPES = frozenset(key[0] for key in KIND_COMPAT)


@dataclass
class IngestReport:
    fetched: list[str] = field(default_factory=list)    # doc_ids whose bytes are NEW in data/raw/ (first fetch OR a revision)
    unchanged: list[str] = field(default_factory=list)  # identical bytes re-fetched — the honest no-op, distinct from fetched
    skipped: list[str] = field(default_factory=list)    # sources with no documents configured (HTML discovery: WS-3)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (requested_url, fixed reason) — per-doc isolation, one key semantic
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
    """Deterministic doc_id for a fetched document: a readable slug of the
    REQUESTED URL's host+path (lowercased, runs of non-[a-z0-9] collapsed to
    '_', stripped, truncated to 111 chars) plus an UNCONDITIONAL suffix of
    '_' + sha256(full url)[:8] — at most 120 chars, exactly DocId120's bound.

    Identity is the EXACT operator-typed URL string; the slug is a display
    affordance and the hash suffix is the discriminator. The suffix is
    unconditional (WS-2b precommit gate, schema-purist HIGH + devils-advocate):
    the slug alone drops query/case/fragment, so two distinct configured URLs
    (`?id=1234` vs `?id=5678`) would collapse into one doc_id and silently
    supersede each other's claims on refold — across RUNS, which no in-run
    preflight can catch. (An earlier docstring claimed analyze's
    `possible_slug_collision` advisory covered this; it does not — that
    advisory guards ENTITY slugs, not doc_ids.)

    Identity is never the post-redirect final URL: the redirect target is
    server-controlled and can change per fetch, so keying identity on it would
    let a hostile or flaky server mint a fresh doc_id on every fetch (each
    revision arrives as a "new" document, defeating same-doc_id supersession)
    or steer two watchlist entries onto one doc_id. URL = identity, content =
    version (plan §1); the final URL is still recorded in the sidecar for
    audit. Cost accepted at the gate: an operator retyping a URL with a
    trivial textual difference (trailing slash, host case) mints a new
    identity — operator-controlled and visible, unlike the silent collapse.
    """
    parts = urlsplit(url)
    slug = re.sub(r"[^a-z0-9]+", "_", f"{parts.netloc}{parts.path}".lower()).strip("_")
    digest = hashlib.sha256(url.encode()).hexdigest()[:_SLUG_HASH_LEN]
    # An empty host+path slug can't happen for a fetchable https URL (the
    # fetcher requires a netloc), but fail toward a valid DocId120 first char.
    return f"{(slug or 'doc')[:_SLUG_MAX]}_{digest}"


def identity_doc_id(url: str, kind: str) -> str:
    """DocId120 derived from identity_material(url, kind).

    NVD CNA and NVD CPE share a URL but hash different material, so they mint
    two doc_ids. URL alone is never the identity key (no UNIQUE(url)).
    """
    digest = hashlib.sha256(identity_material(url, kind)).hexdigest()[:_SLUG_HASH_LEN]
    parts = urlsplit(url)
    slug = re.sub(r"[^a-z0-9]+", "_", f"{parts.netloc}{parts.path}".lower()).strip("_")
    kind_slug = re.sub(r"[^a-z0-9]+", "", kind.lower())
    suffix = f"_{kind_slug}_{digest}"
    head = (slug or "doc")[: max(1, 120 - len(suffix))]
    return f"{head}{suffix}"[:120]


def _retracted_doc_ids(config: Config) -> set[str]:
    """doc_ids with a sidecar under data/quarantine/ — retracted via `forget`.

    run_ingest refuses to implicitly revive these (WS-2b precommit gate,
    devils-advocate): forget quarantines the sidecar+artifact but leaves the
    content-addressed blob, so before this guard a routine watchlist re-run
    would silently re-create the sidecar and the next extract would restore
    the retracted document — a retraction that reports success and then
    un-happens on the next scheduled command. Explicit revival stays available
    via `ingest-file` (a deliberate operator act), or by clearing the
    quarantined record. Unreadable quarantined sidecars are skipped: they
    can't be matched by doc_id, same posture as forget's own scan.
    """
    quarantine_dir = config.paths.data_dir / QUARANTINE_DIRNAME
    if not quarantine_dir.exists():
        return set()
    retracted: set[str] = set()
    # _quarantine_dest suffixes repeats as `<name>.1`, `<name>.2`, ... — match
    # any file carrying the sidecar suffix anywhere in its name.
    for path in sorted(quarantine_dir.iterdir()):
        if SIDECAR_SUFFIX not in path.name:
            continue
        try:
            meta = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        doc_id = meta.get("doc_id")
        if isinstance(doc_id, str):
            retracted.add(doc_id)
    return retracted


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

    Fault isolation mirrors ExtractReport: a FetchError, a non-PDF / non-JSON
    magic refusal, or a SidecarCollision lands in `errors` and the batch continues.

    A changed-bytes re-fetch of a known URL needs NO special handling here:
    store_raw content-addresses the new bytes as a new blob, the sidecar binds
    the same doc_id (same requested URL) to the new sha, and run_extract's
    revision path (extract + refold supersession) does the rest.
    """
    config = config or load_config()
    fetcher = fetcher or WatchlistFetcher()
    report = IngestReport()
    retracted = _retracted_doc_ids(config)

    # requests_per_minute > 0 is a pydantic constraint on RateLimits — an
    # invalid config fails loud at load/construction, never here.
    interval = 60.0 / config.rate_limits.requests_per_minute
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
        # Advisory JSON sources require parser_role (GEI-14 / GEI-11). Fail
        # the source's documents loud rather than writing an un-attestable sidecar.
        if source.doc_type in ADVISORY_DOC_TYPES and not source.parser_role:
            for url in source.documents:
                report.errors.append((
                    url,
                    "parser_role is required for advisory JSON ingest "
                    f"(doc_type={source.doc_type!r})",
                ))
            continue
        if source.doc_type in ADVISORY_DOC_TYPES:
            # Fail loud early if KIND_COMPAT misses the pair.
            attested_kind(source.doc_type, source.parser_role)
        ref = SourceRef(
            name=source.name, url=source.url, doc_type=source.doc_type,
            source_tier=source.source_tier, publisher=source.publisher,
            documents=source.documents, parser_role=source.parser_role,
        )
        for outcome in fetcher.fetch(ref, config.paths.raw_dir, pace=pace):
            if outcome.error is not None:
                # FetchOutcome enforces success XOR error at construction, so
                # error's presence alone is decisive here.
                report.errors.append((outcome.requested_url, outcome.error))
                continue
            if source.doc_type in ADVISORY_DOC_TYPES:
                kind = attested_kind(source.doc_type, source.parser_role)
                doc_id = identity_doc_id(outcome.requested_url, kind.value)
            else:
                doc_id = url_doc_id(outcome.requested_url)
            if doc_id in retracted:
                # Refuse implicit revival of a forgotten document (see
                # _retracted_doc_ids). The fetched bytes stay content-addressed
                # in data/raw/ but a blob without a sidecar is inert.
                report.errors.append((
                    outcome.requested_url,
                    "doc_id was retracted by forget; remove the URL from the "
                    "watchlist, or revive explicitly via ingest-file "
                    "(quarantined record: data/quarantine/)",
                ))
                continue
            meta = {
                "doc_id": doc_id,
                "title": _url_title(outcome.requested_url),
                # doc_type/source_tier/publisher are operator-trusted config;
                # publisher falls back to the source's display name.
                "publisher": source.publisher or source.name,
                "doc_type": source.doc_type,
                "source_tier": source.source_tier,
                # The FINAL post-redirect URL, recorded for audit; identity
                # stays keyed on the requested URL (url_doc_id / identity_doc_id).
                "url": outcome.final_url,
                "publish_date": None,  # unknown — never guessed from untrusted headers
                "ingest_date": today,
                "file_sha256": outcome.raw.sha256,
            }
            if source.parser_role:
                meta["parser_role"] = source.parser_role
            # NEVER write source_record_kind — extract stamps via attested_kind.
            try:
                write_sidecar(config.paths.raw_dir, outcome.raw.sha256, meta)
            except SidecarCollision as exc:
                # S1: these bytes are already bound to another doc_id — the
                # first ingest's provenance wins; this URL's claim is refused.
                # Keyed by requested_url like every other error entry (gate:
                # one key semantic); the colliding doc_ids are in the reason.
                report.errors.append((outcome.requested_url, str(exc)))
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
    parser_role: str | None = None,
) -> RawDoc:
    """Store a local file content-addressed and write its provenance sidecar.

    Operator path (GEI-11): PDF or JSON. Bytes are stored as-is; the file is
    never parsed for provenance. `source_record_kind` / `ghsa_reviewed` /
    `cisa_kev` / `nvd_cna` in the file or a hand-edited sidecar are ignored
    at extract (KIND_COMPAT via doc_type + parser_role only).

    Advisory doc_types require `parser_role` (the ingest discriminator:
    cna vs cpe, reviewed vs unreviewed, ...). Kind is attested with
    `attested_kind(doc_type, parser_role)` at ingest so a bad pair fails
    loud here, not at extract. Sidecar stores doc_type + publisher +
    parser_role — not model-emitted kind.

    Re-ingesting a forgotten doc_id here is the EXPLICIT revival path — a
    deliberate operator act with typed flags. `run_ingest` refuses the implicit
    equivalent (a quarantined doc_id resurfacing via the watchlist); this
    function deliberately does not. Same-bytes rebound to a *different*
    doc_id is still SidecarCollision.
    """
    content = Path(source_path).read_bytes()
    if doc_type in ADVISORY_DOC_TYPES:
        if not parser_role:
            raise ValueError(
                "parser_role is required for advisory ingest "
                "(cna|cpe|catalog|exploit_field|reviewed|unreviewed|json|kev|peer|...)"
            )
        attested_kind(doc_type, parser_role)  # fail loud if KIND_COMPAT misses the pair
    elif parser_role:
        raise ValueError("parser_role is only valid for advisory doc_types")

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
    if parser_role:
        meta["parser_role"] = parser_role
    # Never copy kind from the file. extract uses kind_from_operator_sidecar.
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
