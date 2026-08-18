"""Extraction artifacts + the refold architecture (WS-2a gate, Challenge 1), plus
sidecar/blob integrity (S1/S2).

The SQLite store is DERIVED state: run_extract retains each document's validated
extraction as a content-addressed artifact beside its raw blob, and run_rebuild
deterministically refolds the store from those artifacts (latest per doc_id wins).
That fold is what makes revision supersession and retraction (`forget`) offline
operations — no model call, no API key. Everything here runs offline through the
injected ReplayModelClient, exactly like test_pipeline_e2e.py.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from semianalyst import store
from semianalyst.analyze import run_analysis
from semianalyst.config import Config
from semianalyst.extract import (
    AnthropicExtractor,
    PromptVersion,
    ReplayModelClient,
    run_extract,
    run_rebuild,
)
from semianalyst.ingest import (
    SidecarCollision,
    extraction_artifact_path,
    forget,
    ingest_file,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CASE_DIR = FIXTURES_DIR / "tsmc_n2_2025"
INJ = FIXTURES_DIR / "injection_attack"
DOC_ID = "tsmc_n2_2025"

_INGEST_KW = dict(
    doc_id=DOC_ID, title="TSMC N2", publisher="TSMC",
    doc_type="foundry_announcement", source_tier=2,
    url="https://example.test/tsmc_n2_2025", ingest_date="2026-01-01",
)
_INJ_KW = dict(
    doc_id="injection_attack", title="Vendor Z brief", publisher="Vendor Z",
    doc_type="vendor_whitepaper", source_tier=3,
    url="https://example.test/injection", ingest_date="2026-01-02",
)


def _replay(case_dir: Path, name: str) -> AnthropicExtractor:
    return AnthropicExtractor(ReplayModelClient((case_dir / name).read_text()))


def _counts(config: Config) -> dict[str, int]:
    conn = store.connect(config.paths.db_path)
    try:
        return store.table_counts(conn)
    finally:
        conn.close()


def _stored_shas(config: Config) -> dict[str, str]:
    conn = store.connect(config.paths.db_path)
    try:
        return store.stored_doc_shas(conn)
    finally:
        conn.close()


def _extract_two_docs(config: Config) -> None:
    """Two independent docs, each extracted with its own recorded proposal —
    sequential runs because a single ReplayModelClient can only speak for one doc."""
    store.init_db(config)
    ingest_file(config, CASE_DIR / "raw.pdf", **_INGEST_KW)
    assert run_extract(config, extractor=_replay(CASE_DIR, "llm_response.json")).extracted == [DOC_ID]
    ingest_file(config, INJ / "raw.pdf", **_INJ_KW)
    rep = run_extract(config, extractor=_replay(INJ, "hostile_proposal.json"))
    assert rep.extracted == ["injection_attack"] and rep.errors == []


# --------------------------------------------------------------------------
# Artifact written on extract
# --------------------------------------------------------------------------
def test_extract_writes_extraction_artifact(tmp_config: Config):
    store.init_db(tmp_config)
    raw = ingest_file(tmp_config, CASE_DIR / "raw.pdf", **_INGEST_KW)
    assert run_extract(tmp_config, extractor=_replay(CASE_DIR, "llm_response.json")).extracted == [DOC_ID]

    path = extraction_artifact_path(tmp_config.paths.raw_dir, raw.sha256)
    assert path.exists()
    data = json.loads(path.read_text())
    assert set(data) == {"document", "entities", "claims", "_extracted_at", "_extracted_against"}
    assert data["document"]["doc_id"] == DOC_ID
    assert data["document"]["file_sha256"] == raw.sha256
    assert [e["entity_id"] for e in data["entities"]] == ["tsmc_n2", "tsmc_n3e"]
    # claims are retained UNSCOPED — persist re-scopes idempotently on every fold
    assert [c["claim_id"] for c in data["claims"]] == ["tsmc_n2_logic_speed"]
    # provenance stamp ties the artifact to the exact prompt bytes + model
    prompt = PromptVersion.load(tmp_config.model.prompt_version)
    assert data["_extracted_against"] == {
        "model": tmp_config.model.name, "prompt": prompt.name, "prompt_sha256": prompt.sha256,
    }
    dt.datetime.fromisoformat(data["_extracted_at"])  # a real, parseable timestamp


# --------------------------------------------------------------------------
# Determinism: incremental store == rebuilt store
# --------------------------------------------------------------------------
def test_rebuild_reproduces_the_incremental_store(tmp_config: Config):
    _extract_two_docs(tmp_config)
    incremental_counts = _counts(tmp_config)
    incremental_shas = _stored_shas(tmp_config)
    incremental_analysis = run_analysis(tmp_config).to_dict()

    rep = run_rebuild(tmp_config)
    assert sorted(rep.folded) == ["injection_attack", DOC_ID]
    assert rep.superseded == [] and rep.errors == []

    assert _counts(tmp_config) == incremental_counts
    assert _stored_shas(tmp_config) == incremental_shas
    assert run_analysis(tmp_config).to_dict() == incremental_analysis


# --------------------------------------------------------------------------
# Revision E2E: extract v1 -> re-ingest changed bytes -> only the revision persists
# --------------------------------------------------------------------------
def test_revision_supersedes_prior_extraction(tmp_config: Config, tmp_path: Path):
    store.init_db(tmp_config)
    ingest_file(tmp_config, CASE_DIR / "raw.pdf", **_INGEST_KW)
    assert run_extract(tmp_config, extractor=_replay(CASE_DIR, "llm_response.json")).extracted == [DOC_ID]

    # The revision: same doc_id, changed bytes (appended junk parses to identical
    # text) — and a DIFFERENT recorded value, so the winner is observable.
    revised_pdf = tmp_path / "revised.pdf"
    revised_pdf.write_bytes((CASE_DIR / "raw.pdf").read_bytes() + b"%% corrected\n")
    ingest_file(tmp_config, revised_pdf, **_INGEST_KW)
    recorded = json.loads((CASE_DIR / "llm_response.json").read_text())
    recorded["claims"][0]["value"] = 1.30  # quote_span unchanged, still grounded

    rep = run_extract(tmp_config, extractor=AnthropicExtractor(ReplayModelClient(json.dumps(recorded))))
    assert rep.revised == [DOC_ID] and rep.extracted == [] and rep.errors == []

    # The refolded store reflects ONLY the revision's claims — the 1.15 is gone.
    assert _counts(tmp_config)["document"] == 1 and _counts(tmp_config)["claim"] == 1
    assert _stored_shas(tmp_config)[DOC_ID] == hashlib.sha256(revised_pdf.read_bytes()).hexdigest()
    analysis = run_analysis(tmp_config)
    assert len(analysis.assessments) == 1
    a = analysis.assessments[0]
    assert a.value_range == [1.30, 1.30]
    assert a.members == [f"{DOC_ID}:tsmc_n2_logic_speed"]  # one member, doc-scoped

    # Idempotent after supersession: nothing re-extracts, nothing ping-pongs back
    # to the ORIGINAL bytes (its retained artifact makes it an honest skip, not a
    # "revision" that would out-timestamp the real one on the next fold).
    again = run_extract(tmp_config, extractor=AnthropicExtractor(ReplayModelClient(json.dumps(recorded))))
    assert again.extracted == [] and again.revised == [] and again.errors == []
    assert again.skipped.count(DOC_ID) == 2
    assert run_analysis(tmp_config).assessments[0].value_range == [1.30, 1.30]


# --------------------------------------------------------------------------
# forget E2E: quarantine + refold; blobs retained
# --------------------------------------------------------------------------
def test_forget_quarantines_and_refolds(tmp_config: Config):
    _extract_two_docs(tmp_config)
    assert _counts(tmp_config)["document"] == 2
    tsmc_sha = hashlib.sha256((CASE_DIR / "raw.pdf").read_bytes()).hexdigest()

    rep = forget(tmp_config, DOC_ID)
    assert rep.doc_id == DOC_ID
    quarantine_dir = tmp_config.paths.data_dir / "quarantine"
    assert sorted(rep.quarantined) == [f"{tsmc_sha}.extraction.json", f"{tsmc_sha}.meta.json"]
    for name in rep.quarantined:
        assert (quarantine_dir / name).exists()          # moved, not deleted
    assert not (tmp_config.paths.raw_dir / f"{tsmc_sha}.meta.json").exists()
    assert (tmp_config.paths.raw_dir / tsmc_sha).exists()  # the BLOB stays (content-addressed)
    assert rep.rebuild.folded == ["injection_attack"] and rep.rebuild.errors == []

    # Derived state reflects only the survivor.
    assert _counts(tmp_config)["document"] == 1
    assert list(_stored_shas(tmp_config)) == ["injection_attack"]
    analysis = run_analysis(tmp_config)
    assert {a.entity_id for a in analysis.assessments} == {"vendorz_z"}
    assert "tsmc_n2" not in analysis.entities_reconciled  # the forgotten doc's entities are gone too

    # And run_extract does NOT resurrect it: no sidecar -> nothing pending.
    after = run_extract(tmp_config, extractor=None)
    assert after.extracted == [] and after.errors == []
    assert _counts(tmp_config)["document"] == 1


def test_forget_unknown_doc_id_fails_loud(tmp_config: Config):
    store.init_db(tmp_config)
    with pytest.raises(ValueError, match="no ingested sidecar"):
        forget(tmp_config, "never_ingested")


# --------------------------------------------------------------------------
# S1: sidecar identity binding
# --------------------------------------------------------------------------
def test_same_bytes_different_doc_id_raises_sidecar_collision(tmp_config: Config):
    first = ingest_file(tmp_config, CASE_DIR / "raw.pdf", **_INGEST_KW)
    with pytest.raises(SidecarCollision) as exc:
        ingest_file(tmp_config, CASE_DIR / "raw.pdf", **{**_INGEST_KW, "doc_id": "impostor"})
    assert DOC_ID in str(exc.value) and "impostor" in str(exc.value)
    # The first ingest's identity binding is intact — not clobbered mid-refusal.
    sidecar = tmp_config.paths.raw_dir / f"{first.sha256}.meta.json"
    assert json.loads(sidecar.read_text())["doc_id"] == DOC_ID

    # Same-doc_id re-write stays allowed: a metadata refresh, not a collision.
    refreshed = ingest_file(tmp_config, CASE_DIR / "raw.pdf", **{**_INGEST_KW, "title": "TSMC N2 (rev)"})
    assert refreshed.sha256 == first.sha256
    assert json.loads(sidecar.read_text())["title"] == "TSMC N2 (rev)"


# --------------------------------------------------------------------------
# S2: blob hash re-verified at read
# --------------------------------------------------------------------------
def test_tampered_blob_is_reported_and_skipped(tmp_config: Config):
    store.init_db(tmp_config)
    raw = ingest_file(tmp_config, CASE_DIR / "raw.pdf", **_INGEST_KW)
    raw.blob_path.write_bytes(b"tampered after ingest")  # filename sha no longer matches content

    rep = run_extract(tmp_config, extractor=None)  # nothing valid pending -> no client built
    assert rep.extracted == [] and rep.skipped == []
    assert any(sha == raw.sha256 and "hash mismatch" in reason for sha, reason in rep.errors)
    assert _counts(tmp_config)["document"] == 0  # the tampered bytes never reach the extractor
