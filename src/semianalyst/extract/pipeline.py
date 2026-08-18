"""Extract orchestration — the library entry points behind `semianalyst extract`
and `semianalyst db rebuild`.

Wires the built pieces into a pipeline: read each ingested raw doc (blob +
provenance sidecar) that hasn't been extracted yet, run the configured Extractor +
PromptVersion, and persist the grounded entities/claims through store. Read-side
of the ingest->extract handoff decided in docs/ROADMAP.md (sidecar + extract-time
Document): ingest writes the sidecar; extract builds the Document from it and
persist_extraction inserts it (unchanged).

WS-2a (gate resolution, Challenge 1) makes the SQLite store DERIVED state: every
successful extraction is retained as a content-addressed artifact beside its raw
blob (`<sha256>.extraction.json`), and `run_rebuild` deterministically refolds the
store from those artifacts — latest artifact per doc_id wins. That fold is what
delivers revision supersession here (a same-doc_id changed-bytes sidecar is now
EXTRACTED and folded in, retiring the WS-1 deferral) and retraction in
`ingest.forget` (quarantine the artifact, refold) — both offline, no model calls.

The Extractor is injectable so the full pipeline runs offline (ReplayModelClient,
no network, no API key) in tests; the default builds the real Anthropic client,
which is exercised by the @live E2E test — the ENFORCE anchor for the wiring.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

from .. import store
from ..config import Config, load_config
from ..ingest import (
    RawDoc,
    extraction_artifact_path,
    read_extraction_artifacts,
    read_raw_docs,
    write_extraction_artifact,
)
from ..store import models
from .base import AnthropicExtractor, AnthropicModelClient
from .prompts import PromptVersion
from .validate import ExtractionResult


@dataclass
class ExtractReport:
    extracted: list[str] = field(default_factory=list)   # doc_ids newly persisted (first extraction of the doc_id)
    skipped: list[str] = field(default_factory=list)      # already extracted: same bytes, or an already-retained revision
    revised: list[str] = field(default_factory=list)      # same doc_id, CHANGED bytes — extracted + folded; store holds only the latest
    errors: list[tuple[str, str]] = field(default_factory=list)  # (doc_id|sha256, reason) — one bad doc doesn't sink the batch
    note: str = ""


@dataclass
class RebuildReport:
    folded: list[str] = field(default_factory=list)      # doc_ids replayed into the fresh store (fold winners)
    superseded: list[str] = field(default_factory=list)  # doc_ids where older artifact(s) lost the latest-wins fold
    errors: list[tuple[str, str]] = field(default_factory=list)  # (doc_id|sha256, reason) — per-artifact isolation


def _build_document(meta: dict, model_name: str, prompt: PromptVersion) -> models.Document:
    """Construct the Document from the ingest sidecar. This is where the sidecar's
    operator-supplied fields (doc_type, source_tier, dates) are validated — pydantic
    fails loud on a bad value, naming the field. extraction_model records the exact
    (model, prompt bytes) provenance of this run; file_sha256 is authoritative from
    ingest and the doc_id is context, never a model output."""
    return models.Document(
        doc_id=meta["doc_id"],
        title=meta["title"],
        publisher=meta["publisher"],
        doc_type=meta["doc_type"],
        source_tier=meta["source_tier"],
        publish_date=meta.get("publish_date"),
        url=meta["url"],
        file_sha256=meta["file_sha256"],
        ingest_date=meta["ingest_date"],
        extraction_model=f"{model_name}+{prompt.name}@{prompt.sha256[:12]}",
    )


def _artifact_payload(
    document: models.Document, result: ExtractionResult, model_name: str, prompt: PromptVersion
) -> dict:
    """The retained extraction artifact: everything a rebuild needs to replay
    persist_extraction WITHOUT the model. Claims are the validated, UNSCOPED
    result — persist re-scopes claim_ids idempotently. `_extracted_at` (real
    clock) orders revisions of one doc_id in the latest-wins fold — the only
    thing run order decides; `_extracted_against` is the structured twin of
    Document.extraction_model, tying the artifact to exact prompt bytes."""
    return {
        "document": document.model_dump(mode="json"),
        "entities": [e.model_dump(mode="json") for e in result.entities],
        "claims": [c.model_dump(mode="json") for c in result.claims],
        "_extracted_at": dt.datetime.now(dt.UTC).isoformat(),
        "_extracted_against": {
            "model": model_name,
            "prompt": prompt.name,
            "prompt_sha256": prompt.sha256,
        },
    }


def run_extract(config: Config | None = None, *, extractor: AnthropicExtractor | None = None) -> ExtractReport:
    """Extract claims from ingested raw docs into the store.

    Idempotent by (doc_id, file_sha256): a doc already extracted with identical
    bytes is skipped, as is a changed-bytes sidecar whose extraction artifact is
    already retained (its result is preserved; the fold decides the winner — a
    re-extraction would stamp a fresher _extracted_at and let stale bytes win).
    A sidecar with a stored doc_id but DIFFERENT, not-yet-extracted bytes is a
    source revision: it IS extracted, its artifact retained, and the store
    refolded (run_rebuild) so it reflects only the latest revision per doc_id —
    surfaced in `revised`, never silently skipped. Each document is isolated: a
    malformed sidecar, a blob integrity failure (S2), or a persist failure is
    recorded in `errors` and the batch continues, so one bad doc never aborts
    the rest.
    """
    config = config or load_config()
    conn = store.connect(config.paths.db_path)
    try:
        stored = store.stored_doc_shas(conn)  # doc_id -> file_sha256
        raw_docs, read_errors = read_raw_docs(config.paths.raw_dir)
        errors: list[tuple[str, str]] = list(read_errors)  # S2: integrity failures are the caller's to see

        pending: list[tuple[RawDoc, bool]] = []  # (raw doc, is_revision)
        skipped: list[str] = []
        for rd in raw_docs:
            doc_id = rd.meta.get("doc_id", rd.sha256)
            prior = stored.get(doc_id)
            if prior is None:
                pending.append((rd, False))
            elif prior == rd.meta.get("file_sha256"):
                skipped.append(doc_id)          # already extracted, same bytes
            elif extraction_artifact_path(config.paths.raw_dir, rd.sha256).exists():
                skipped.append(doc_id)          # a PAST revision (or the pre-fold original): already retained + folded
            else:
                pending.append((rd, True))      # a fresh revision — extract + fold, never silently skip

        if not pending:
            note = ""
            if not raw_docs and not errors:
                note = "no pending raw docs — ingest one with `semianalyst ingest-file`."
            return ExtractReport(skipped=skipped, errors=errors, note=note)

        prompt = PromptVersion.load(config.model.prompt_version)
        # Build the real Anthropic extractor only when there is work AND no client
        # was injected — so `extract` with nothing pending never needs an API key.
        extractor = extractor or AnthropicExtractor(AnthropicModelClient(config.model.name))

        extracted: list[str] = []
        revised: list[str] = []
        for rd, is_revision in pending:
            doc_id = rd.meta.get("doc_id", rd.sha256)
            try:
                document = _build_document(rd.meta, config.model.name, prompt)
                result = extractor.extract(rd.blob_path.read_bytes(), document, prompt)
                if is_revision:
                    # The doc_id row already exists under older bytes — a direct
                    # persist would fail loud on the duplicate INSERT. Retain the
                    # artifact only; the refold below replaces the store wholesale
                    # so it reflects exactly this latest revision.
                    write_extraction_artifact(
                        config.paths.raw_dir, rd.sha256,
                        _artifact_payload(document, result, config.model.name, prompt),
                    )
                    revised.append(document.doc_id)
                else:
                    # One short transaction per document: the model call already
                    # happened; commit the persisted rows atomically or roll this
                    # doc back — the next doc is unaffected.
                    with conn:
                        store.persist_extraction(conn, document, result.entities, result.claims)
                    # Artifact AFTER a successful persist: what the store accepted
                    # is what a rebuild will replay. The store is derived state;
                    # the artifact + sidecar are the durable record.
                    write_extraction_artifact(
                        config.paths.raw_dir, rd.sha256,
                        _artifact_payload(document, result, config.model.name, prompt),
                    )
                    extracted.append(document.doc_id)
            except Exception as exc:  # per-document isolation, not a batch abort
                errors.append((doc_id, f"{type(exc).__name__}: {exc}"[:200]))

        note = ""
        if revised:
            # Supersession = refold. run_rebuild swaps in a fresh db file; this
            # connection keeps the pre-fold file open harmlessly until the finally.
            fold = run_rebuild(config)
            errors.extend(fold.errors)
            note = ("source revision(s) extracted and folded — the store reflects only "
                    "the latest revision per doc_id; prior extractions stay retained "
                    "as artifacts under data/raw/.")
        return ExtractReport(extracted=extracted, skipped=skipped, revised=revised,
                             errors=errors, note=note)
    finally:
        conn.close()


def run_rebuild(config: Config | None = None) -> RebuildReport:
    """Rebuild the SQLite store as a deterministic fold over retained extraction
    artifacts (gate resolution, Challenge 1). The DB is DERIVED state — artifacts
    + sidecars under data/raw/ are the source of truth — so retraction (`forget`)
    and revision supersession are offline rebuilds, never in-place row surgery
    and never model re-calls.

    Per doc_id the LATEST artifact wins (_extracted_at desc; sha256 lexical as a
    deterministic tie-break). Winners replay through the unchanged
    persist_extraction in (ingest_date, doc_id) order — the same first-doc-wins
    reconciliation a fresh incremental run would produce. The fold lands in a
    temp file and atomically replaces the configured db (os.replace), so a
    crashed rebuild never leaves a half-folded store. Per-artifact fault
    isolation mirrors run_extract: one bad artifact lands in `errors` and the
    fold continues. A document persisted without an artifact (pre-WS-2a rows)
    does NOT survive a rebuild — the artifact is the retention contract.
    """
    config = config or load_config()
    artifacts, read_errors = read_extraction_artifacts(config.paths.raw_dir)
    errors: list[tuple[str, str]] = list(read_errors)

    by_doc: dict[str, list] = {}
    for art in artifacts:
        doc = art.data.get("document")
        doc_id = doc.get("doc_id") if isinstance(doc, dict) else None
        if not doc_id:
            errors.append((art.sha256, "artifact has no document.doc_id"))
            continue
        by_doc.setdefault(doc_id, []).append(art)

    winners: list[tuple[str, object]] = []
    superseded: list[str] = []
    for doc_id, arts in by_doc.items():
        arts.sort(key=lambda a: (str(a.data.get("_extracted_at", "")), a.sha256))  # latest last
        winners.append((doc_id, arts[-1]))
        if len(arts) > 1:
            superseded.append(doc_id)
    # Deterministic replay order — (ingest_date, doc_id), NOT filesystem order —
    # so a rebuilt store reconciles entities exactly as the incremental one did.
    winners.sort(key=lambda w: (str(w[1].data["document"].get("ingest_date") or ""), w[0]))

    db_path = config.paths.db_path
    tmp_path = db_path.with_name(db_path.name + ".rebuild")
    tmp_path.unlink(missing_ok=True)  # a leftover from a crashed prior rebuild
    store.init_db(config, db_path=tmp_path)
    conn = store.connect(tmp_path)
    folded: list[str] = []
    try:
        for doc_id, art in winners:
            try:
                document = models.Document.model_validate(art.data["document"])
                entities = [models.Entity.model_validate(e) for e in art.data["entities"]]
                claims = [models.Claim.model_validate(c) for c in art.data["claims"]]
                with conn:  # per-document isolation, like run_extract
                    store.persist_extraction(conn, document, entities, claims)
                folded.append(doc_id)
            except Exception as exc:
                errors.append((doc_id, f"{type(exc).__name__}: {exc}"[:200]))
    finally:
        conn.close()
    os.replace(tmp_path, db_path)  # atomic swap: readers see the old store or the new, never half
    return RebuildReport(folded=folded, superseded=sorted(superseded), errors=errors)
