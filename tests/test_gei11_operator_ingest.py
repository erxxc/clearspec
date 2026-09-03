"""GEI-11: operator ingest for advisory JSON/PDF — zero network.

Proves ingest-file -> extract (ReplayModelClient) -> report on the GEI-10
golden set without live Anthropic or NVD/GHSA/KEV fetches. Kind is stamped
ONLY via attested_kind(doc_type, parser_role) / KIND_COMPAT. Sidecar and JSON
self-attestation of ghsa_reviewed / cisa_kev / nvd_cna is ignored.
GEI-9 grouping is not implemented here; report must still succeed.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from semianalyst import store
from semianalyst.analyze import run_analysis
from semianalyst.extract import AnthropicExtractor, PromptVersion, ReplayModelClient, run_extract
from semianalyst.extract.pipeline import run_extract as run_extract_mod
from semianalyst.ingest import (
    SidecarCollision,
    forget,
    identity_doc_id,
    ingest_file,
    write_sidecar,
)
from semianalyst.store.attestation import KIND_COMPAT, kind_from_sidecar

FIXTURES = Path(__file__).parent / "fixtures" / "advisory_golden"
JENKINS_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-23897"

# Operator ingest table for the GEI-10 golden set. parser_role is the
# discriminator; kind is derived through KIND_COMPAT, never from the file.
GOLDEN = [
    ("cve-2024-21626-nvd.json", "nvd_record", "cpe", "NVD",
     "https://nvd.nist.gov/vuln/detail/CVE-2024-21626"),
    ("cve-2024-21626-ghsa.json", "ghsa", "reviewed", "GitHub",
     "https://github.com/advisories/GHSA-xr7r-f8xq-rv7p"),
    ("cve-2024-6387-nvd.json", "nvd_record", "cpe", "NVD",
     "https://nvd.nist.gov/vuln/detail/CVE-2024-6387"),
    ("cve-2024-6387-vendor.json", "vendor_advisory", "json", "OpenSSH",
     "https://www.openssh.com/txt/release-9.8"),
    ("cve-2024-3400-nvd.json", "nvd_record", "cna", "NVD",
     "https://nvd.nist.gov/vuln/detail/CVE-2024-3400"),
    ("cve-2024-3400-vendor.json", "vendor_advisory", "json", "Palo Alto Networks",
     "https://security.paloaltonetworks.com/CVE-2024-3400"),
    ("cve-2023-44487-xnet.json", "nvd_record", "cpe", "NVD",
     "https://nvd.nist.gov/vuln/detail/CVE-2023-44487"),
    ("cve-2023-39325-stdlib.json", "nvd_record", "cna", "NVD",
     "https://nvd.nist.gov/vuln/detail/CVE-2023-39325"),
    ("cve-2024-23897-cna.json", "nvd_record", "cna", "NVD", JENKINS_URL),
    ("cve-2024-23897-cpe.json", "nvd_record", "cpe", "NVD", JENKINS_URL),
]


def _mini_pdf(text: str) -> bytes:
    """Tiny PDF whose payload is the operator-fed source text (GEI-11 PDF path)."""
    payload = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({payload}) Tj ET\n".encode("latin-1", "replace")
    objs = []
    objs.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objs.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objs.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objs.append(
        b"4 0 obj<< /Length " + str(len(stream)).encode() + b" >>stream\n"
        + stream + b"endstream\nendobj\n"
    )
    objs.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")
    header = b"%PDF-1.1\n"
    parts = [header]
    offsets = [0]
    pos = len(header)
    for obj in objs:
        offsets.append(pos)
        parts.append(obj)
        pos += len(obj)
    xref_pos = pos
    xref = [b"xref\n0 6\n0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode())
    trailer = (
        b"trailer<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode() + b"\n%%EOF\n"
    )
    return b"".join(parts) + b"".join(xref) + trailer


def _load(stem: str) -> dict:
    return json.loads((FIXTURES / stem).read_text())


def _source_json(tmp_path: Path, stem: str, extra: dict | None = None) -> Path:
    """Operator-fed JSON: source_text plus optional adversary-controlled kind keys."""
    case = _load(stem)
    payload = {"text": case["source_text"]}
    if extra:
        payload.update(extra)
    path = tmp_path / stem
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def case_source_and_proposal(stem: str) -> tuple[str, str]:
    case = _load(stem)
    # document_text() of the ingested JSON includes source_text as a substring
    return case["source_text"], json.dumps(case["proposal"])


def _replay_for_goldens() -> ReplayModelClient:
    mapping: dict[str, str] = {}
    for stem, *_ in GOLDEN:
        src, proposal = case_source_and_proposal(stem)
        mapping[src] = proposal
    return ReplayModelClient(mapping)


def test_kind_compat_keys_match_ticket():
    keys = set(KIND_COMPAT)
    assert keys == {
        ("nvd_record", "cna"), ("nvd_record", "cpe"), ("nvd_record", "catalog"),
        ("nvd_record", "exploit_field"),
        ("ghsa", "reviewed"), ("ghsa", "unreviewed"), ("ghsa", "exploit_field"),
        ("vendor_advisory", "json"), ("vendor_advisory", "cna"),
        ("vendor_advisory", "acknowledgement"), ("vendor_advisory", "cvss"),
        ("cisa_kev", "kev"),
        ("researcher_writeup", "peer"),
    }


def test_ingest_file_json_and_pdf_advisory_doc_types(tmp_config, tmp_path):
    """ingest-file accepts advisory JSON and a tiny PDF with advisory doc_types."""
    store.init_db(tmp_config)
    json_path = _source_json(tmp_path, "cve-2024-21626-nvd.json")
    nvd_url = "https://nvd.nist.gov/vuln/detail/CVE-2024-21626"
    nvd_id = identity_doc_id(nvd_url, "nvd_cpe")
    raw = ingest_file(
        tmp_config, json_path, doc_id=nvd_id, title="runc nvd", publisher="NVD",
        doc_type="nvd_record", source_tier=3, url=nvd_url,
        ingest_date="2026-09-02", parser_role="cpe",
    )
    assert raw.meta["doc_type"] == "nvd_record"
    assert raw.meta["parser_role"] == "cpe"
    assert "source_record_kind" not in raw.meta

    pdf_path = tmp_path / "advisory.pdf"
    pdf_path.write_bytes(_mini_pdf("vendor advisory json body 9.8p1"))
    pdf_raw = ingest_file(
        tmp_config, pdf_path, doc_id="openssh_vendor_pdf",
        title="OpenSSH vendor PDF", publisher="OpenSSH",
        doc_type="vendor_advisory", source_tier=3,
        url="https://example.test/openssh.pdf", ingest_date="2026-09-02",
        parser_role="json",
    )
    assert pdf_raw.blob_path.read_bytes().startswith(b"%PDF-")
    assert pdf_raw.meta["parser_role"] == "json"
    assert pdf_raw.meta["doc_type"] == "vendor_advisory"


@pytest.mark.parametrize("spoofed", ["ghsa_reviewed", "cisa_kev", "nvd_cna"])
def test_sidecar_and_json_self_attest_is_ignored(tmp_config, tmp_path, spoofed):
    """A sidecar/JSON that self-attests a high-weight kind does NOT persist it."""
    store.init_db(tmp_config)
    extra = {
        "source_record_kind": spoofed,
        "ghsa_reviewed": True,
        "cisa_kev": True,
        "nvd_cna": True,
    }
    path = _source_json(tmp_path, "cve-2024-21626-nvd.json", extra=extra)
    url = "https://nvd.nist.gov/vuln/detail/CVE-2024-21626"
    doc_id = identity_doc_id(url, "nvd_cpe")
    raw = ingest_file(
        tmp_config, path, doc_id=doc_id, title="runc", publisher="NVD",
        doc_type="nvd_record", source_tier=3, url=url, ingest_date="2026-09-02",
        parser_role="cpe",
    )
    assert raw.meta.get("source_record_kind") is None
    # Poison the sidecar the way an adversary-controlled file would: copy kind.
    poisoned = dict(raw.meta)
    poisoned["source_record_kind"] = spoofed
    write_sidecar(tmp_config.paths.raw_dir, raw.sha256, poisoned)
    # kind_from_sidecar WOULD launder it — operator ingest must not use that path.
    assert kind_from_sidecar(poisoned).value == spoofed
    src = inspect.getsource(run_extract_mod)
    assert "kind_from_sidecar(" not in src
    assert "kind_from_operator_sidecar" in src

    case = _load("cve-2024-21626-nvd.json")
    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(case["proposal"])))
    report = run_extract(tmp_config, extractor=extractor)
    assert report.errors == []
    assert doc_id in report.extracted
    conn = store.connect(tmp_config.paths.db_path)
    try:
        kinds = {r["source_record_kind"] for r in conn.execute("SELECT source_record_kind FROM claim")}
    finally:
        conn.close()
    assert kinds == {"nvd_cpe"}
    assert spoofed not in kinds


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

    # GEI-9 grouping is out of scope; report must still succeed (no crash).
    analysis = run_analysis(tmp_config)
    assert analysis.assessments == []  # advisory classes skipped until GEI-9


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
