"""Extract orchestration — the library entry point behind `semianalyst extract`.

Wires the three built pieces into a pipeline: read each ingested raw doc (blob +
provenance sidecar) that hasn't been extracted yet, run the configured Extractor +
PromptVersion, and persist the grounded entities/claims through store. Read-side
of the ingest->extract handoff decided in docs/ROADMAP.md (sidecar + extract-time
Document): ingest writes the sidecar; extract builds the Document from it and
persist_extraction inserts it (unchanged).

The Extractor is injectable so the full pipeline runs offline (ReplayModelClient,
no network, no API key) in tests; the default builds the real Anthropic client,
which is exercised by the @live E2E test — the ENFORCE anchor for the wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import store
from ..config import Config, load_config
from ..ingest import read_raw_docs
from ..store import models
from .base import AnthropicExtractor, AnthropicModelClient
from .prompts import PromptVersion


@dataclass
class ExtractReport:
    extracted: list[str] = field(default_factory=list)   # doc_ids newly persisted
    skipped: list[str] = field(default_factory=list)      # already extracted (same doc_id + same bytes)
    revised: list[str] = field(default_factory=list)      # same doc_id, CHANGED bytes — a source revision, surfaced not extracted
    errors: list[tuple[str, str]] = field(default_factory=list)  # (doc_id, reason) — one bad doc doesn't sink the batch
    note: str = ""


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


def run_extract(config: Config | None = None, *, extractor: AnthropicExtractor | None = None) -> ExtractReport:
    """Extract claims from ingested raw docs into the store.

    Idempotent by (doc_id, file_sha256): a doc already extracted with identical
    bytes is skipped. A sidecar with a doc_id already in the store but DIFFERENT
    bytes is a source revision — it is surfaced in `revised`, NOT silently skipped
    (that would defeat the schema's `file_sha256` revision signal) and NOT
    auto-re-extracted (same-doc_id supersession is deferred; see CLAUDE.md). Each
    document is isolated: a malformed sidecar or a persist failure is recorded in
    `errors` and the batch continues, so one bad doc never aborts the rest.
    """
    config = config or load_config()
    conn = store.connect(config.paths.db_path)
    try:
        stored = store.stored_doc_shas(conn)  # doc_id -> file_sha256
        raw_docs = read_raw_docs(config.paths.raw_dir)

        pending: list = []
        skipped: list[str] = []
        revised: list[str] = []
        for rd in raw_docs:
            doc_id = rd.meta.get("doc_id", rd.sha256)
            prior = stored.get(doc_id)
            if prior is None:
                pending.append(rd)
            elif prior == rd.meta.get("file_sha256"):
                skipped.append(doc_id)          # already extracted, same bytes
            else:
                revised.append(doc_id)          # same doc_id, changed bytes — loud, not skipped

        if not pending:
            note = ""
            if not raw_docs:
                note = "no pending raw docs — ingest one with `semianalyst ingest-file`."
            elif revised:
                note = ("source revision(s) detected (same doc_id, changed bytes); "
                        "same-doc_id re-extraction is not supported in WS-1 — "
                        "re-ingest under a new doc_id to extract the revision.")
            return ExtractReport(skipped=skipped, revised=revised, note=note)

        prompt = PromptVersion.load(config.model.prompt_version)
        # Build the real Anthropic extractor only when there is work AND no client
        # was injected — so `extract` with nothing pending never needs an API key.
        extractor = extractor or AnthropicExtractor(AnthropicModelClient(config.model.name))

        extracted: list[str] = []
        errors: list[tuple[str, str]] = []
        for rd in pending:
            doc_id = rd.meta.get("doc_id", rd.sha256)
            try:
                document = _build_document(rd.meta, config.model.name, prompt)
                result = extractor.extract(rd.blob_path.read_bytes(), document, prompt)
                # One short transaction per document: the model call already
                # happened; commit the persisted rows atomically or roll this doc
                # back — the next doc is unaffected.
                with conn:
                    store.persist_extraction(conn, document, result.entities, result.claims)
                extracted.append(document.doc_id)
            except Exception as exc:  # per-document isolation, not a batch abort
                errors.append((doc_id, f"{type(exc).__name__}: {exc}"[:200]))
        return ExtractReport(extracted=extracted, skipped=skipped, revised=revised, errors=errors)
    finally:
        conn.close()
