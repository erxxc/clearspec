"""GEI-7 schema v5 continued tests (split for MCP push)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError

from semianalyst import store
from semianalyst.extract.validate import validate_proposal
from semianalyst.store import models as m

from tests.test_schema_v5 import (
    REPO, V4_SHA, _sha, _doc, _cite, _interval, _range_claim, _pkg_runc,
)

def test_empty_ghsa_does_not_outrank_vendor_no_resolver(tmp_config):
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        product = m.Entity(
            entity_id="prod_openssh", entity_type=m.EntityType.product,
            vendor="OpenBSD", name="OpenSSH",
            product=m.ProductAttributes(name="OpenSSH", cpe="cpe:2.3:a:openbsd:openssh"),
            attribute_citations={
                "product.name": _cite("OpenSSH"),
                "product.cpe": _cite("cpe:2.3:a:openbsd:openssh"),
            },
        )
        vendor_range = _interval(end="9.7p1", end_incl=True)
        store.persist_extraction(
            conn, _doc("vendor_6387", doc_type=m.DocType.vendor_advisory,
                       publisher="OpenSSH", url="https://www.openssh.com/txt/release-9.8"),
            [product], [_range_claim(
                "vendor", "vendor_6387", "prod_openssh", "CVE-2024-6387",
                m.SourceRecordKind.vendor_json, vendor_range,
                "Portable OpenSSH versions between 8.5p1 and 9.7p1 (inclusive)",
                claim_class=m.ClaimClass.patched_in,
            )])
        with pytest.raises(ValidationError):
            _range_claim(
                "ghsa", "ghsa_empty", "prod_openssh", "CVE-2024-6387",
                m.SourceRecordKind.ghsa_unreviewed, None,  # type: ignore[arg-type]
                "unreviewed GHSA with empty vulnerabilities",
            )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"] == 1
        assert conn.execute("SELECT source_record_kind FROM claim").fetchone()[0] == "vendor_json"
    finally:
        conn.close()


def test_grouping_key_cve_id_split_44487_vs_39325(tmp_config):
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        xnet = m.Entity(
            entity_id="pkg_x_net", entity_type=m.EntityType.package,
            vendor="golang", name="x/net",
            package=m.PackageAttributes(ecosystem="go", name="golang.org/x/net"),
            attribute_citations={
                "package.ecosystem": _cite("go"),
                "package.name": _cite("golang.org/x/net"),
            },
        )
        stdlib = m.Entity(
            entity_id="pkg_go_stdlib", entity_type=m.EntityType.package,
            vendor="golang", name="std",
            package=m.PackageAttributes(ecosystem="go", name="stdlib"),
            attribute_citations={
                "package.ecosystem": _cite("go"),
                "package.name": _cite("stdlib"),
            },
        )
        store.persist_extraction(
            conn, _doc("nvd_44487", url="https://nvd.nist.gov/vuln/detail/CVE-2023-44487"),
            [xnet], [_range_claim(
                "c1", "nvd_44487", "pkg_x_net", "CVE-2023-44487",
                m.SourceRecordKind.nvd_cna, _interval(end="0.17.0", end_incl=False),
                "golang.org/x/net before 0.17.0",
            )])
        store.persist_extraction(
            conn, _doc("nvd_39325", url="https://nvd.nist.gov/vuln/detail/CVE-2023-39325"),
            [stdlib], [_range_claim(
                "c2", "nvd_39325", "pkg_go_stdlib", "CVE-2023-39325",
                m.SourceRecordKind.nvd_cna, _interval(end="1.21.1", end_incl=False),
                "Go stdlib before 1.21.1",
            )])
        conn.commit()
        views = store.get_claims_for_analysis(conn)
        keys = {v.advisory_group_key() for v in views}
        assert ("CVE-2023-44487", "pkg_x_net", "affected_range") in keys
        assert ("CVE-2023-39325", "pkg_go_stdlib", "affected_range") in keys
        assert len(keys) == 2
    finally:
        conn.close()


def test_kev_exploit_status_does_not_speak_to_affected_range():
    kev = m.Claim(
        claim_id="kev", doc_id="cisa", entity_id="prod_panos",
        cve_id="CVE-2024-3400", claim_class=m.ClaimClass.exploit_status,
        metric="known_exploited",
        exploit_status=m.ExploitStatus.known_exploited,
        source_record_kind=m.SourceRecordKind.cisa_kev,
        completeness=m.Completeness.complete,
        citation=_cite("Known Exploited Vulnerabilities Catalog"),
    )
    assert kev.version_range is None
    assert kev.source_record_kind == m.SourceRecordKind.cisa_kev
    with pytest.raises(ValidationError):
        m.Claim(
            claim_id="bad", doc_id="cisa", entity_id="prod_panos",
            cve_id="CVE-2024-3400", claim_class=m.ClaimClass.affected_range,
            metric="affected_range",
            source_record_kind=m.SourceRecordKind.cisa_kev,
            completeness=m.Completeness.complete,
            citation=_cite("KEV has no version range"),
        )


def test_panos_hotfix_list_is_multiple_intervals():
    vr = m.VersionRange(intervals=[
        m.VersionInterval(
            start=m.VersionBound(version="10.2.0", inclusive=True),
            end=m.VersionBound(version="10.2.8-h3", inclusive=False),
        ),
        m.VersionInterval(
            start=m.VersionBound(version="11.0.0", inclusive=True),
            end=m.VersionBound(version="11.0.3-h10", inclusive=False),
        ),
        m.VersionInterval(
            start=m.VersionBound(version="11.1.0", inclusive=True),
            end=m.VersionBound(version="11.1.2-h3", inclusive=False),
        ),
    ])
    claim = _range_claim(
        "vendor", "pan", "prod_panos", "CVE-2024-3400",
        m.SourceRecordKind.vendor_json, vr,
        "10.2 < 10.2.8-h3; 11.0 < 11.0.3-h10; 11.1 < 11.1.2-h3",
    )
    assert len(claim.version_range.intervals) == 3
    nvd_whole_branch = _range_claim(
        "nvd", "nvd_pan", "prod_panos", "CVE-2024-3400",
        m.SourceRecordKind.nvd_cpe,
        m.VersionRange(intervals=[
            m.VersionInterval(
                start=m.VersionBound(version="10.2.0", inclusive=True),
                end=m.VersionBound(version="10.3.0", inclusive=False),
            ),
        ]),
        "PAN-OS 10.2",
    )
    k_vendor = claim.advisory_group_key()
    k_nvd = nvd_whole_branch.advisory_group_key()
    assert k_vendor == k_nvd == ("CVE-2024-3400", "prod_panos", "affected_range")


def test_cvss_requires_numeric_value_and_record_kind():
    ok = m.Claim(
        claim_id="cv", doc_id="nvd", entity_id="cve_x",
        cve_id="CVE-2024-21626", claim_class=m.ClaimClass.cvss,
        metric="cvss_v3", value=8.6, unit="cvss",
        source_record_kind=m.SourceRecordKind.nvd_catalog,
        completeness=m.Completeness.complete,
        citation=_cite("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:H"),
    )
    assert ok.value == 8.6
    with pytest.raises(ValidationError):
        m.Claim(
            claim_id="cv", doc_id="nvd", entity_id="cve_x",
            cve_id="CVE-2024-21626", claim_class=m.ClaimClass.cvss,
            metric="cvss_v3",
            source_record_kind=m.SourceRecordKind.nvd_catalog,
            completeness=m.Completeness.complete,
            citation=_cite("CVSS 8.6"),
        )
