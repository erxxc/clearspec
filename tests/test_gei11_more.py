"""GEI-11 continued tests (split for MCP push size)."""
from __future__ import annotations

import hashlib
import json

import pytest

from semianalyst import store
from semianalyst.analyze import run_analysis
from semianalyst.extract import AnthropicExtractor, PromptVersion, ReplayModelClient, run_extract
from semianalyst.ingest import SidecarCollision, forget, identity_doc_id, ingest_file

from tests.test_gei11_operator_ingest import (
    GOLDEN,
    JENKINS_URL,
    _load,
    _mini_pdf,
    _replay_for_goldens,
    _source_json,
)

def test_nvd_cna_vs_cpe_same_url_two_doc_ids(tmp_config, tmp_path):
    store.init_db(tmp_config)
    cna_id = identity_doc_id(JENKINS_URL, "nvd_cna")
    cpe_id = identity_doc_id(JENKINS_URL, "nvd_cpe")
    assert cna_id != cpe_id
    assert store.identity_material(JENKINS_URL, "nvd_cna") != store.identity_material(JENKINS_URL, "nvd_cpe")

    ingest_file(
        tmp_config, _source_json(tmp_path, "cve-2024-23897-cna.json"),
        doc_id=cna_id, title="jenkins cna", publisher="NVD",
        doc_type="nvd_record", source_tier=3, url=JENKINS_URL,
        ingest_date="2026-09-02", parser_role="cna",
    )
    ingest_file(
        tmp_config, _source_json(tmp_path, "cve-2024-23897-cpe.json"),
        doc_id=cpe_id, title="jenkins cpe", publisher="NVD",
        doc_type="nvd_record", source_tier=3, url=JENKINS_URL,
        ingest_date="2026-09-02", parser_role="cpe",
    )
    extractor = AnthropicExtractor(_replay_for_goldens())
    report = run_extract(tmp_config, extractor=extractor)
    assert sorted(report.extracted) == sorted([cna_id, cpe_id])
    conn = store.connect(tmp_config.paths.db_path)
    try:
        docs = list(conn.execute("SELECT doc_id, url, doc_type FROM document"))
        kinds = {r["source_record_kind"] for r in conn.execute("SELECT source_record_kind FROM claim")}
        urls = {r["url"] for r in docs}
        ids = {r["doc_id"] for r in docs}
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='document'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert ids == {cna_id, cpe_id}
    assert urls == {JENKINS_URL}
    assert kinds == {"nvd_cna", "nvd_cpe"}
    assert "UNIQUE" not in schema.replace("PRIMARY KEY", "")


def test_ingest_extract_report_golden_set_zero_network(tmp_config, tmp_path):
    """ingest-file -> extract (replay) -> report on the golden set. No network."""
    store.init_db(tmp_config)
    doc_ids = []
    for stem, doc_type, role, publisher, url in GOLDEN:
        kind = store.attested_kind(doc_type, role)
        doc_id = identity_doc_id(url, kind.value)
        # Same URL + different kind must not collide (Jenkins CNA vs CPE).
        ingest_file(
            tmp_config, _source_json(tmp_path, stem),
            doc_id=doc_id, title=stem, publisher=publisher,
            doc_type=doc_type, source_tier=3, url=url,
            ingest_date="2026-09-02", parser_role=role,
        )
        doc_ids.append(doc_id)

    extractor = AnthropicExtractor(_replay_for_goldens())
    extracted = run_extract(tmp_config, extractor=extractor)
    assert extracted.errors == []
    assert set(extracted.extracted) == set(doc_ids)

    conn = store.connect(tmp_config.paths.db_path)
    try:
        claims = list(conn.execute(
            "SELECT claim_id, source_record_kind, version_range FROM claim"
        ))
        kinds = {r["source_record_kind"] for r in claims}
        blobs = " ".join(r["version_range"] or "" for r in claims)
        n_docs = conn.execute("SELECT COUNT(*) AS n FROM document").fetchone()["n"]
    finally:
        conn.close()
    assert n_docs == len(GOLDEN)
    assert None not in kinds
    assert "1.1.12" not in blobs  # version_bound stays grounded; no exclusive+1
    assert "1.1.11" in blobs

    # GEI-9 detailed contradicted-range asserts: tests/test_gei9_golden_assessments.py
    analysis = run_analysis(tmp_config)
    assert analysis.assessments  # non-empty once advisory grouping lands


def test_quarantined_doc_id_still_refused(tmp_config, tmp_path):
    store.init_db(tmp_config)
    url = "https://nvd.nist.gov/vuln/detail/CVE-2024-21626"
    doc_id = identity_doc_id(url, "nvd_cpe")
    path = _source_json(tmp_path, "cve-2024-21626-nvd.json")
    ingest_file(
        tmp_config, path, doc_id=doc_id, title="runc", publisher="NVD",
        doc_type="nvd_record", source_tier=3, url=url, ingest_date="2026-09-02",
        parser_role="cpe",
    )
    # Same bytes rebound to a different doc_id while the sidecar binding exists (S1).
    with pytest.raises(SidecarCollision):
        ingest_file(
            tmp_config, path, doc_id="attacker_rebind", title="runc", publisher="NVD",
            doc_type="nvd_record", source_tier=3, url=url, ingest_date="2026-09-02",
            parser_role="cpe",
        )
    case = _load("cve-2024-21626-nvd.json")
    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(case["proposal"])))
    assert run_extract(tmp_config, extractor=extractor).extracted == [doc_id]

    forgotten = forget(tmp_config, doc_id)
    assert forgotten.quarantined
    conn = store.connect(tmp_config.paths.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM document").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"] == 0
    finally:
        conn.close()


def test_extract_advisory_v1_bytes_unchanged():
    """Frozen prompt: GEI-11 must not edit extract_advisory_v1.md (changes are v2)."""
    from semianalyst.config import REPO_ROOT
    path = REPO_ROOT / "prompts" / "extract_advisory_v1.md"
    data = path.read_bytes()
    pv = PromptVersion.load("extract_advisory_v1")
    assert pv.sha256 == hashlib.sha256(data).hexdigest()
    assert b"IMMUTABLE" in data or b"PROMPT VERSIONING" in data
    assert b"source_record_kind" in data
    # This ticket does not land extract_advisory_v2.
    assert not (REPO_ROOT / "prompts" / "extract_advisory_v2.md").exists()


def test_advisory_ingest_requires_parser_role(tmp_config, tmp_path):
    store.init_db(tmp_config)
    path = _source_json(tmp_path, "cve-2024-21626-nvd.json")
    with pytest.raises(ValueError, match="parser_role"):
        ingest_file(
            tmp_config, path, doc_id="nvd_21626", title="runc", publisher="NVD",
            doc_type="nvd_record", source_tier=3,
            url="https://nvd.nist.gov/vuln/detail/CVE-2024-21626",
        )


def test_foundry_rejects_parser_role(tmp_config, tmp_path):
    store.init_db(tmp_config)
    pdf = tmp_path / "n2.pdf"
    pdf.write_bytes(_mini_pdf("TSMC N2"))
    with pytest.raises(ValueError, match="parser_role is only valid"):
        ingest_file(
            tmp_config, pdf, doc_id="tsmc_n2", title="N2", publisher="TSMC",
            doc_type="foundry_announcement", source_tier=2,
            url="https://example.test/n2", parser_role="cna",
        )


def test_advisory_extract_uses_advisory_prompt_not_foundry(tmp_config, tmp_path):
    store.init_db(tmp_config)
    url = "https://nvd.nist.gov/vuln/detail/CVE-2024-21626"
    doc_id = identity_doc_id(url, "nvd_cpe")
    ingest_file(
        tmp_config, _source_json(tmp_path, "cve-2024-21626-nvd.json"),
        doc_id=doc_id, title="runc", publisher="NVD",
        doc_type="nvd_record", source_tier=3, url=url, ingest_date="2026-09-02",
        parser_role="cpe",
    )
    seen = {}

    class _Capture(ReplayModelClient):
        def complete(self, system: str, document_text: str) -> str:
            seen["system"] = system
            return super().complete(system, document_text)

    case = _load("cve-2024-21626-nvd.json")
    extractor = AnthropicExtractor(_Capture(json.dumps(case["proposal"])))
    run_extract(tmp_config, extractor=extractor)
    advisory = PromptVersion.load("extract_advisory_v1")
    foundry = PromptVersion.load("extract_foundry_v1")
    assert seen["system"] == advisory.text
    assert seen["system"] != foundry.text
