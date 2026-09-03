"""GEI-7: extraction schema v5 for advisory entities and claims.

Proves new enums, structured version intervals (not string-only), two-layer
bounds, NVD CNA vs NVD CPE as distinct records, never-auto-resolve, and that
the v4/foundry path still round-trips. Does not ingest live, does not implement
extract_advisory_v1 / grouping / operator ingest.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from semianalyst import store
from semianalyst.extract.validate import validate_proposal
from semianalyst.store import models as m

REPO = Path(__file__).resolve().parents[1]
V4_SHA = "4e060ad98db141f9c154aa5c6ea761df2a586e08"


def _sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _doc(doc_id: str, *, doc_type=m.DocType.nvd_record, publisher="NVD",
         url="https://nvd.nist.gov/vuln/detail/CVE-2024-23897") -> m.Document:
    return m.Document(
        doc_id=doc_id, title="t", publisher=publisher, doc_type=doc_type,
        source_tier=m.SourceTier.vendor, url=url, file_sha256="0" * 64,
        ingest_date=dt.date(2026, 9, 2),
    )


def _cite(span: str) -> m.Citation:
    return m.Citation(quote_span=span, location_type=m.LocationType.unknown)


def _interval(start=None, start_incl=True, end=None, end_incl=False) -> m.VersionRange:
    s = None if start is None else m.VersionBound(version=start, inclusive=start_incl)
    e = None if end is None else m.VersionBound(version=end, inclusive=end_incl)
    return m.VersionRange(intervals=[m.VersionInterval(start=s, end=e)])


def _range_claim(claim_id, doc_id, entity_id, cve_id, kind, vr, span,
                 claim_class=m.ClaimClass.affected_range) -> m.Claim:
    return m.Claim(
        claim_id=claim_id, doc_id=doc_id, entity_id=entity_id, cve_id=cve_id,
        claim_class=claim_class, metric=claim_class.value,
        version_range=vr, source_record_kind=kind,
        completeness=m.Completeness.complete, citation=_cite(span),
    )


def test_v4_yaml_sha_unchanged():
    v4 = REPO / "schema" / "extraction_schema_v4.yaml"
    if not v4.exists():
        pytest.skip("v4 yaml not in this working tree; asserted on the PR branch")
    assert _sha(v4) == V4_SHA


def test_v5_yaml_exists_and_does_not_edit_v4():
    v5 = (REPO / "schema" / "extraction_schema_v5.yaml").read_text()
    assert "NEVER AUTO-RESOLVE" in v5
    assert "source_record_kind" in v5
    assert "nvd_cna" in v5 and "nvd_cpe" in v5
    assert "affected_range" in v5
    assert "quote_span" in v5


def test_new_enums_round_trip():
    assert m.DocType.nvd_record.value == "nvd_record"
    assert m.DocType.ghsa.value == "ghsa"
    assert m.EntityType.cve.value == "cve"
    assert m.EntityType.product.value == "product"
    assert m.EntityType.advisory.value == "advisory"
    assert m.ClaimClass.affected_range.value == "affected_range"
    assert m.ClaimClass.patched_in.value == "patched_in"
    assert m.ClaimClass.cvss.value == "cvss"
    assert m.ClaimClass.exploit_status.value == "exploit_status"
    assert m.ClaimClass.workaround.value == "workaround"
    assert m.Completeness.missing_range.value == "missing_range"
    assert m.Completeness.missing_product.value == "missing_product"
    # foundry enums still present
    assert m.DocType.foundry_announcement.value == "foundry_announcement"
    assert m.EntityType.process_node.value == "process_node"
    assert m.ClaimClass.performance.value == "performance"


def test_range_requires_structured_interval_not_display_string():
    with pytest.raises(ValidationError):
        m.Claim(
            claim_id="c", doc_id="d", entity_id="pkg_runc",
            cve_id="CVE-2024-21626", claim_class=m.ClaimClass.affected_range,
            metric="< 1.1.12",  # display string is not the range
            source_record_kind=m.SourceRecordKind.nvd_cpe,
            completeness=m.Completeness.complete,
            citation=_cite("runc 1.1.11 and earlier"),
        )
    ok = _range_claim(
        "c", "d", "pkg_runc", "CVE-2024-21626", m.SourceRecordKind.nvd_cpe,
        _interval(end="1.1.12", end_incl=False), "runc 1.1.11 and earlier",
    )
    assert ok.version_range.intervals[0].end.version == "1.1.12"
    assert ok.version_range.intervals[0].end.inclusive is False
    assert ok.version_range.intervals[0].start is None  # unbounded below
    assert ok.citation.quote_span == "runc 1.1.11 and earlier"


def test_version_bound_rejects_control_bytes_and_oversize():
    with pytest.raises(ValidationError):
        m.VersionBound(version="1.0\x1b[31m", inclusive=True)
    with pytest.raises(ValidationError):
        m.VersionBound(version="v" * 81, inclusive=True)


def test_foundry_claim_still_requires_numeric_value():
    with pytest.raises(ValidationError):
        m.Claim(
            claim_id="c", doc_id="d", entity_id="e",
            claim_class=m.ClaimClass.performance, metric="logic_speed",
            completeness=m.Completeness.complete,
            citation=_cite("x"),
        )


def _pkg_runc() -> m.Entity:
    return m.Entity(
        entity_id="pkg_runc", entity_type=m.EntityType.package,
        vendor="opencontainers", name="runc",
        package=m.PackageAttributes(
            ecosystem="go", name="github.com/opencontainers/runc",
            purl="pkg:golang/github.com/opencontainers/runc",
        ),
        attribute_citations={
            "package.ecosystem": _cite("ecosystem go"),
            "package.name": _cite("github.com/opencontainers/runc"),
            "package.purl": _cite("pkg:golang/github.com/opencontainers/runc"),
        },
    )


def test_nvd_cna_and_nvd_cpe_are_distinct_records_same_url(tmp_config):
    """Jenkins: NVD CNA vs NVD CPE share a URL but are different records.
    Document-level source_tier is the same; source_record_kind distinguishes them.
    """
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        url = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-23897"
        pkg = m.Entity(
            entity_id="pkg_jenkins_core", entity_type=m.EntityType.package,
            vendor="jenkins", name="jenkins-core",
            package=m.PackageAttributes(
                ecosystem="maven", name="org.jenkins-ci.main:jenkins-core",
            ),
            attribute_citations={
                "package.ecosystem": _cite("maven"),
                "package.name": _cite("org.jenkins-ci.main:jenkins-core"),
            },
        )
        store.persist_extraction(conn, _doc("nvd_23897", url=url, publisher="NVD"), [pkg], [
            _range_claim(
                "cpe", "nvd_23897", "pkg_jenkins_core", "CVE-2024-23897",
                m.SourceRecordKind.nvd_cpe,
                _interval(end="2.426.3", end_incl=False),
                "LTS versionEndExcluding 2.426.3 no lower bound",
            ),
            _range_claim(
                "cna", "nvd_23897", "pkg_jenkins_core", "CVE-2024-23897",
                m.SourceRecordKind.nvd_cna,
                m.VersionRange(intervals=[
                    m.VersionInterval(
                        start=m.VersionBound(version="1.606", inclusive=True),
                        end=m.VersionBound(version="2.426.3", inclusive=False),
                    ),
                ]),
                "version 0 lessThan 1.606 unaffected; GHSA/CNA start at 1.606",
            ),
        ])
        conn.commit()
        rows = conn.execute(
            "SELECT claim_id, source_record_kind, version_range FROM claim ORDER BY claim_id"
        ).fetchall()
        kinds = {r["source_record_kind"] for r in rows}
        assert kinds == {"nvd_cna", "nvd_cpe"}
        assert conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"] == 2
        assert conn.execute("SELECT COUNT(*) AS n FROM document").fetchone()["n"] == 1
        url_row = conn.execute("SELECT url FROM document").fetchone()["url"]
        assert url_row == url
        # neither record won — both version_range blobs are stored
        blobs = {r["source_record_kind"]: r["version_range"] for r in rows}
        assert "1.606" in blobs["nvd_cna"]
        assert "2.426.3" in blobs["nvd_cpe"]
        assert "1.606" not in blobs["nvd_cpe"]
    finally:
        conn.close()


def test_never_auto_resolve_conflicting_ranges_both_persist(tmp_config):
    """runc subset: NVD unbounded <1.1.12 vs GHSA >= rc93. Both claims persist.
    No winner is selected. Grouping keys match so GEI-9 can see the fight.
    """
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        pkg = _pkg_runc()
        nvd = _interval(end="1.1.12", end_incl=False)
        ghsa = m.VersionRange(intervals=[m.VersionInterval(
            start=m.VersionBound(version="1.0.0-rc93", inclusive=True),
            end=m.VersionBound(version="1.1.11", inclusive=True),
        )])
        store.persist_extraction(
            conn, _doc("nvd_21626", publisher="NVD",
                       url="https://nvd.nist.gov/vuln/detail/CVE-2024-21626"),
            [pkg], [_range_claim(
                "nvd", "nvd_21626", "pkg_runc", "CVE-2024-21626",
                m.SourceRecordKind.nvd_cpe, nvd, "runc 1.1.11 and earlier",
            )])
        store.persist_extraction(
            conn, _doc("ghsa_xr7r", doc_type=m.DocType.ghsa, publisher="GitHub",
                       url="https://github.com/advisories/GHSA-xr7r-f8xq-vfvv"),
            [pkg], [_range_claim(
                "ghsa", "ghsa_xr7r", "pkg_runc", "CVE-2024-21626",
                m.SourceRecordKind.ghsa_reviewed, ghsa,
                ">= 1.0.0-rc93, <= 1.1.11",
            )])
        conn.commit()
        rows = list(conn.execute("SELECT source_record_kind FROM claim"))
        assert {r["source_record_kind"] for r in rows} == {"nvd_cpe", "ghsa_reviewed"}
        assert store.get_conflicts(conn) == []  # claims coexist; no attribute fight
        views = store.get_claims_for_analysis(conn)
        keys = {(v.cve_id, v.entity_id, v.claim_class) for v in views}
        assert keys == {("CVE-2024-21626", "pkg_runc", "affected_range")}
        # analyze must NOT collapse them via ±10% or pick a favored record kind
        from semianalyst.analyze import analyze_claims
        report = analyze_claims(views, store.get_entities_index(conn))
        assert report.assessments == []  # skipped; GEI-9 owns range grouping
    finally:
        conn.close()


def test_empty_ghsa_does_not_outrank_vendor_no_resolver(tmp_config):
    """OpenSSH: unreviewed GHSA with empty range vs vendor patched_in. Both
    persist. Schema documents that empty GHSA does not outrank vendor — there
    is no code path that drops the vendor claim.
    """
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
        # unreviewed GHSA carries no range — it is not an affected_range claim
        # (cannot outrank vendor because it cannot even be a range claim)
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
    """HTTP/2 Rapid Reset: two CVEs on related packages. Grouping key includes
    cve_id so GEI-9 will not mix CVE-2023-44487 with CVE-2023-39325.
    """
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
    """CISA KEV with no version range is exploit_status only. Building an
    affected_range claim from it fails pydantic (no version_range).
    """
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
    """PAN-OS vendor hotfix list is a structured union of intervals, not a
    display string of versions.
    """
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


def test_no_python_resolver_function_exists():
    """Never auto-resolve: ranking tables live in yaml only. There must be no
    pick-a-winner helper on the models or store modules.
    """
    import semianalyst.store.models as models_mod
    import semianalyst.store.db as db_mod
    forbidden = (
        "pick_winner", "resolve_conflict", "winning_tier", "rank_source",
        "advisory_source_weight", "choose_tier", "auto_resolve",
    )
    for name in forbidden:
        assert not hasattr(models_mod, name), name
        assert not hasattr(db_mod, name), name
        assert not hasattr(m.Claim, name), name


def test_sqlite_version_range_flood_guard(tmp_config):
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        store.persist_extraction(
            conn, _doc("d1"), [_pkg_runc()],
            [_range_claim(
                "ok", "d1", "pkg_runc", "CVE-2024-21626",
                m.SourceRecordKind.nvd_cpe, _interval(end="1.1.12"),
                "runc 1.1.11 and earlier",
            )])
        conn.commit()
        # flood: oversize JSON bypasses pydantic by going straight to SQL
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO claim (claim_id, doc_id, entity_id, claim_class, metric, "
                "completeness, cite_quote_span, cite_location_type, version_range, source_record_kind) "
                "VALUES ('flood','d1','pkg_runc','affected_range','affected_range',"
                "'complete','span','unknown', ?, 'nvd_cpe')",
                ("[" + "x" * 40001 + "]",),
            )
            conn.commit()
    finally:
        conn.close()


def test_foundry_path_still_persists(tmp_config):
    """v4/foundry claim with numeric value still inserts; migrations include 0005."""
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        versions = [r["version"] for r in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
        assert versions == [1, 2, 3, 4, 5]
        node = m.Entity(
            entity_id="tsmc_n2", entity_type=m.EntityType.process_node,
            vendor="TSMC", name="N2",
            node=m.NodeAttributes(transistor_type=m.TransistorType.gaa_nanosheet),
            attribute_citations={
                "node.transistor_type": _cite("N2 GAA"),
            },
        )
        foundry_doc = m.Document(
            doc_id="tsmc_n2_2025", title="TSMC N2", publisher="TSMC",
            doc_type=m.DocType.foundry_announcement, source_tier=m.SourceTier.foundry,
            url="https://example.com/n2", file_sha256="a" * 64,
            ingest_date=dt.date(2025, 4, 24),
        )
        claim = m.Claim(
            claim_id="c1", doc_id="tsmc_n2_2025", entity_id="tsmc_n2",
            claim_class=m.ClaimClass.performance, metric="logic_speed",
            value=1.15, unit="x",
            comparison=m.Comparison(is_relative=True, baseline_entity="tsmc_n3e", baseline_stated=True),
            completeness=m.Completeness.complete, citation=_cite("15% faster"),
        )
        store.persist_extraction(conn, foundry_doc, [node], [claim])
        conn.commit()
        row = conn.execute("SELECT value, unit, version_range FROM claim").fetchone()
        assert row["value"] == 1.15
        assert row["unit"] == "x"
        assert row["version_range"] is None
    finally:
        conn.close()


def test_cve_entity_requires_cve_id_and_optional_cwe():
    ok = m.Entity(
        entity_id="cve_21626", entity_type=m.EntityType.cve,
        vendor="NVD", name="CVE-2024-21626",
        cve=m.CveAttributes(cve_id="CVE-2024-21626", cwe="CWE-668"),
        attribute_citations={
            "cve.cwe": _cite("CWE-668"),
        },
    )
    assert ok.cve.cve_id == "CVE-2024-21626"
    with pytest.raises(ValidationError):
        m.Entity(
            entity_id="cve_bad", entity_type=m.EntityType.cve,
            vendor="NVD", name="x",
        )
    with pytest.raises(ValidationError):
        m.CveAttributes(cve_id="CVE-24-1")  # too short year/seq


def test_package_foundry_still_legal_without_package_attrs():
    """Semiconductor package (foundry) must not require PackageAttributes."""
    e = m.Entity(
        entity_id="pkg_fanout", entity_type=m.EntityType.package,
        vendor="TSMC", name="InFO",
        attribute_citations={},
    )
    assert e.package is None


def test_validate_advisory_claim_grounding():
    proposal = {
        "document": {
            "doc_id": "nvd_21626", "title": "CVE-2024-21626",
            "publisher": "NVD", "doc_type": "nvd_record", "source_tier": 2,
            "url": "https://nvd.nist.gov/vuln/detail/CVE-2024-21626",
        },
        "entities": [{
            "entity_id": "pkg_runc", "entity_type": "package",
            "vendor": "opencontainers", "name": "runc",
            "package": {"ecosystem": "go", "name": "github.com/opencontainers/runc"},
            "attribute_citations": {
                "package.ecosystem": {"quote_span": "ecosystem go", "location_type": "unknown"},
                "package.name": {"quote_span": "github.com/opencontainers/runc", "location_type": "unknown"},
            },
        }],
        "claims": [{
            "claim_id": "c1", "doc_id": "nvd_21626", "entity_id": "pkg_runc",
            "cve_id": "CVE-2024-21626", "claim_class": "affected_range",
            "metric": "affected_range",
            "version_range": {"intervals": [{"end": {"version": "1.1.12", "inclusive": False}}]},
            "source_record_kind": "nvd_cpe",
            "completeness": "complete",
            "citation": {"quote_span": "runc 1.1.11 and earlier", "location_type": "unknown"},
        }],
    }
    result, _rej = validate_proposal(proposal, "runc 1.1.11 and earlier. ecosystem go. github.com/opencontainers/runc")
    assert result.claims[0].version_range.intervals[0].end.version == "1.1.12"
    assert result.entities[0].package.ecosystem == "go"
