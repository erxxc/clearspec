"""End-to-end pipeline wiring: ingest_file -> run_extract -> persist -> report.

Proves the glue WS-1 added, not the components (each is covered by its own suite):
  - `test_extract_e2e_offline` drives the WHOLE chain with an injected
    ReplayModelClient (no network, no API key). It asserts the recorded golden
    proposal lands in the store as the expected rows, that analyze reads them back
    through the report path with doc-scoped claim_ids, and that a re-run is
    idempotent (already-persisted docs are skipped, not re-inserted).
  - `test_extract_e2e_live` (@live) runs the SAME chain against the real extractor
    — the ENFORCE anchor for the wiring — and skips on a plain `uv run pytest`.
  - `test_report_display_is_ansi_sanitized` covers the report display-safety guard.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from semianalyst import store
from semianalyst.analyze import run_analysis
from semianalyst.cli import _ansi_safe
from semianalyst.config import Config, PathsConfig, load_config
from semianalyst.extract import AnthropicExtractor, ReplayModelClient, run_extract
from semianalyst.ingest import ingest_file, store_raw, write_sidecar

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CASE_DIR = FIXTURES_DIR / "tsmc_n2_2025"
INJ = FIXTURES_DIR / "injection_attack"
DOC_ID = "tsmc_n2_2025"

_INGEST_KW = dict(
    doc_id=DOC_ID, title="TSMC N2", publisher="TSMC",
    doc_type="foundry_announcement", source_tier=2,
    url="https://example.test/tsmc_n2_2025", ingest_date="2026-01-01",
)


def _expected() -> dict:
    data = json.loads((CASE_DIR / "expected.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _counts(config: Config) -> dict[str, int]:
    conn = store.connect(config.paths.db_path)
    try:
        return store.table_counts(conn)
    finally:
        conn.close()


def test_extract_e2e_offline(tmp_config: Config):
    store.init_db(tmp_config)
    ingest_file(tmp_config, CASE_DIR / "raw.pdf", **_INGEST_KW)

    # The recorded golden proposal, fed as canned model output — exercises the real
    # parse + validate + ground + persist path without a live call.
    recorded = json.loads((CASE_DIR / "llm_response.json").read_text())
    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(recorded)))

    report = run_extract(tmp_config, extractor=extractor)
    assert report.extracted == [DOC_ID]
    assert report.skipped == []

    expected = _expected()
    counts = _counts(tmp_config)
    assert counts["document"] == 1
    assert counts["entity"] == len(expected["entities"])  # 2 (tsmc_n2, tsmc_n3e)
    assert counts["claim"] == len(expected["claims"])      # 1

    # Analyze reads the persisted claims back through the report path. The one
    # relative claim vs a resolved baseline is a singleton -> uncorroborated, and
    # its member id is doc-scoped by persist_extraction.
    analysis = run_analysis(tmp_config)
    assert len(analysis.assessments) == 1
    a = analysis.assessments[0]
    assert a.entity_id == "tsmc_n2" and a.metric == "logic_speed"
    assert a.status == "uncorroborated"
    assert a.flags == ["single_source"]  # baseline tsmc_n3e is resolved -> no unresolved_baseline
    assert a.members == [f"{DOC_ID}:tsmc_n2_logic_speed"]

    # Idempotent: a re-run (same doc_id, same bytes) persists nothing new and skips.
    again = run_extract(tmp_config, extractor=extractor)
    assert again.extracted == [] and again.revised == [] and again.errors == []
    assert again.skipped == [DOC_ID]
    assert _counts(tmp_config)["document"] == 1


def test_run_extract_no_pending_is_a_noop(tmp_config: Config):
    store.init_db(tmp_config)
    report = run_extract(tmp_config, extractor=None)  # nothing ingested -> never builds a client
    assert report.extracted == [] and report.skipped == []
    assert report.revised == [] and report.errors == []
    assert report.note  # tells the operator to ingest a file


def test_source_revision_is_extracted_and_superseded(tmp_config: Config, tmp_path: Path):
    """Same doc_id + CHANGED bytes must NOT be silently classified 'skipped' (that
    would defeat the schema's file_sha256 revision signal). WS-2a: the revision IS
    extracted, its artifact retained, and the store refolded so it holds only the
    latest revision per doc_id (gate resolution, Challenge 1). Deeper store-state
    assertions live in test_rebuild.py."""
    store.init_db(tmp_config)
    ingest_file(tmp_config, CASE_DIR / "raw.pdf", **_INGEST_KW)
    recorded = json.loads((CASE_DIR / "llm_response.json").read_text())
    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(recorded)))
    assert run_extract(tmp_config, extractor=extractor).extracted == [DOC_ID]

    revised_pdf = tmp_path / "revised.pdf"
    revised_pdf.write_bytes((CASE_DIR / "raw.pdf").read_bytes() + b"%% corrected\n")
    ingest_file(tmp_config, revised_pdf, **_INGEST_KW)  # same doc_id, different bytes

    rep = run_extract(tmp_config, extractor=extractor)
    assert rep.extracted == [] and rep.errors == []
    assert rep.revised == [DOC_ID]        # the revision is surfaced AND processed...
    assert DOC_ID in rep.skipped          # ...while the original bytes stay an honest skip
    assert rep.note                        # loud: superseded via refold, not silent
    # the refolded store holds exactly ONE extraction — the revision's, not two
    assert _counts(tmp_config)["document"] == 1 and _counts(tmp_config)["claim"] == 1
    conn = store.connect(tmp_config.paths.db_path)
    try:
        stored = store.stored_doc_shas(conn)
    finally:
        conn.close()
    assert stored[DOC_ID] == hashlib.sha256(revised_pdf.read_bytes()).hexdigest()

    # a re-run is idempotent: both sidecars (original + revision) are honest skips
    again = run_extract(tmp_config, extractor=extractor)
    assert again.extracted == [] and again.revised == [] and again.errors == []
    assert again.skipped.count(DOC_ID) == 2
    assert _counts(tmp_config)["document"] == 1 and _counts(tmp_config)["claim"] == 1


def test_malformed_sidecar_is_isolated_not_a_batch_abort(tmp_config: Config):
    """One bad sidecar records an error and the rest of the batch still extracts —
    no bare traceback, no head-of-line block (gate decision: per-document isolation)."""
    store.init_db(tmp_config)
    ingest_file(tmp_config, CASE_DIR / "raw.pdf", **_INGEST_KW)  # a good doc
    bad = store_raw(b"malformed-doc-bytes", tmp_config.paths.raw_dir)
    # sidecar missing the required title/publisher/... — a KeyError at Document build
    write_sidecar(tmp_config.paths.raw_dir, bad.sha256,
                  {"doc_id": "bad_doc", "file_sha256": bad.sha256})
    recorded = json.loads((CASE_DIR / "llm_response.json").read_text())
    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(recorded)))

    rep = run_extract(tmp_config, extractor=extractor)
    assert DOC_ID in rep.extracted                              # good doc processed
    assert any(doc_id == "bad_doc" for doc_id, _ in rep.errors)  # bad doc isolated
    assert _counts(tmp_config)["document"] == 1


def test_injection_wiring_offline(tmp_config: Config):
    """Prompt-injection defense holds through the PRODUCTION wiring, not just the
    extractor in isolation (gate decision Q3): a hostile proposal flowing
    ingest_file -> run_extract -> persist has its exfil + fabricated claims dropped
    by validation before they can reach the store."""
    store.init_db(tmp_config)
    ingest_file(tmp_config, INJ / "raw.pdf", doc_id="injection_attack",
                title="Vendor Z brief", publisher="Vendor Z",
                doc_type="vendor_whitepaper", source_tier=3,
                url="https://example.test/injection", ingest_date="2026-01-01")
    hostile = json.loads((INJ / "hostile_proposal.json").read_text())
    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(hostile)))

    rep = run_extract(tmp_config, extractor=extractor)
    assert rep.extracted == ["injection_attack"] and rep.errors == []

    conn = store.connect(tmp_config.paths.db_path)
    try:
        claims = store.get_claims_for_analysis(conn)
    finally:
        conn.close()
    # Only the grounded 2x-throughput claim survives; the api_key exfil and the
    # fabricated 500x claim (quotes absent from the PDF) never reach the store.
    assert [c.claim_id for c in claims] == ["injection_attack:legit"]
    assert all(c.metric != "api_key" for c in claims)
    assert claims[0].metric == "throughput"


@pytest.mark.live
def test_extract_e2e_live(tmp_path: Path):
    real = load_config()
    cfg = Config(
        model=real.model,
        paths=PathsConfig(
            data_dir=tmp_path, raw_dir=tmp_path / "raw", db_path=tmp_path / "semianalyst.db"
        ),
        rate_limits=real.rate_limits,
        sources=(),
    )
    store.init_db(cfg)
    ingest_file(cfg, CASE_DIR / "raw.pdf", **_INGEST_KW)

    report = run_extract(cfg)  # default extractor -> the real Anthropic model
    assert report.extracted == [DOC_ID]
    assert _counts(cfg)["claim"] >= 1


def test_report_display_is_ansi_sanitized():
    hostile = "N2\x1b[31mHACK\x1b[0m\x1b]0;pwned\x07 speed"
    safe = _ansi_safe(hostile)
    assert "\x1b" not in safe and "\x07" not in safe
    assert "[31m" not in safe and "0;pwned" not in safe
    assert "HACK" in safe and "speed" in safe  # payload text survives, but inert
