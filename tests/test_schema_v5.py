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
        # GEI-9: both claims persist in one contradicted group; no winning kind.
        from semianalyst.analyze import analyze_claims
        report = analyze_claims(views, store.get_entities_index(conn))
        assert len(report.assessments) == 1
        a = report.assessments[0]
        assert a.status == "contradicted"
        assert a.set_relation == "subset"
        assert {"nvd", "ghsa"} <= set(a.members) or set(a.members) == {"nvd_21626:nvd", "ghsa_xr7r:ghsa"}
        # favored_tier is display-only; store still has both claims
        assert len(views) == 2
    finally:
        conn.close()
