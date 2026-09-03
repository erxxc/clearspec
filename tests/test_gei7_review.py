"""GEI-7 review must-fixes: class-conditional SQL CHECKs and ingest-attested kind."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from semianalyst import store
from semianalyst.extract.validate import validate_proposal
from semianalyst.store import models as m


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


_ADVISORY_SRC = (
    "runc 1.1.11 and earlier. ecosystem go. github.com/opencontainers/runc"
)


def _advisory_proposal(kind: str = "nvd_cpe") -> dict:
    return {
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
            "version_range": {"intervals": [{"end": {"version": "1.1.11", "inclusive": True}}]},
            "source_record_kind": kind,
            "completeness": "complete",
            "citation": {"quote_span": "runc 1.1.11 and earlier", "location_type": "unknown"},
        }],
    }


def test_sql_affected_range_null_version_range_fails(tmp_config):
    """DB layer: affected_range with version_range NULL must fail even if the
    range is stuffed into metric (the display-string failure GEI-6 forbade).
    """
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
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO claim (claim_id, doc_id, entity_id, claim_class, metric, "
                "completeness, cite_quote_span, cite_location_type, version_range, "
                "source_record_kind) VALUES "
                "('bad_range','d1','pkg_runc','affected_range','< 1.1.12',"
                "'complete','span','unknown', NULL, 'nvd_cpe')"
            )
            conn.commit()
    finally:
        conn.close()


def test_sql_foundry_null_value_fails(tmp_config):
    """DB layer: foundry INSERT with value NULL must fail (0004 invariant)."""
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        node = m.Entity(
            entity_id="tsmc_n2", entity_type=m.EntityType.process_node,
            vendor="TSMC", name="N2",
        )
        foundry_doc = m.Document(
            doc_id="tsmc_n2_2025", title="TSMC N2", publisher="TSMC",
            doc_type=m.DocType.foundry_announcement, source_tier=m.SourceTier.foundry,
            url="https://example.com/n2", file_sha256="a" * 64,
            ingest_date=dt.date(2025, 4, 24),
        )
        ok = m.Claim(
            claim_id="c1", doc_id="tsmc_n2_2025", entity_id="tsmc_n2",
            claim_class=m.ClaimClass.performance, metric="logic_speed",
            value=1.15, unit="x",
            completeness=m.Completeness.complete, citation=_cite("15% faster"),
        )
        store.persist_extraction(conn, foundry_doc, [node], [ok])
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO claim (claim_id, doc_id, entity_id, claim_class, metric, "
                "value, unit, completeness, cite_quote_span, cite_location_type) VALUES "
                "('bad_f','tsmc_n2_2025','tsmc_n2','performance','logic_speed',"
                "NULL,'x','complete','span','unknown')"
            )
            conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("spoofed", ["ghsa_reviewed", "cisa_kev", "nvd_cna"])
def test_proposal_self_attested_kind_is_stripped_and_not_persisted(tmp_config, spoofed):
    """A proposal that self-attests a high-weight kind must not persist it."""
    result, rej = validate_proposal(_advisory_proposal(kind=spoofed), _ADVISORY_SRC)
    assert result.claims
    assert result.claims[0].source_record_kind is None
    assert any(r.kind == "claim_kind" for r in rej)
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.persist_extraction(
                conn, _doc("nvd_21626"), result.entities, result.claims)
            conn.commit()
    finally:
        conn.close()


def test_ingest_stamped_kind_survives_self_attest(tmp_config):
    """Ingest stamp (CNA-vs-CPE parser) overwrites model self-attest and persists."""
    result, _ = validate_proposal(_advisory_proposal(kind="cisa_kev"), _ADVISORY_SRC)
    assert result.claims[0].source_record_kind is None
    stamped = store.attested_kind("nvd_record", "cpe")
    assert stamped == m.SourceRecordKind.nvd_cpe
    assert stamped != m.SourceRecordKind.cisa_kev
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        store.persist_extraction(
            conn, _doc("nvd_21626"), result.entities, result.claims,
            source_record_kind=stamped,
        )
        conn.commit()
        row = conn.execute("SELECT source_record_kind FROM claim").fetchone()
        assert row["source_record_kind"] == "nvd_cpe"
    finally:
        conn.close()


def test_cna_and_cpe_attestation_roles_are_distinct():
    assert store.attested_kind("nvd_record", "cna") == m.SourceRecordKind.nvd_cna
    assert store.attested_kind("nvd_record", "cpe") == m.SourceRecordKind.nvd_cpe
    assert store.attested_kind("nvd_record", "cna") != store.attested_kind("nvd_record", "cpe")


def test_identity_material_cna_cpe_same_url_distinct():
    url = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-23897"
    cna = store.identity_material(url, "nvd_cna")
    cpe = store.identity_material(url, "nvd_cpe")
    assert cna != cpe
    assert store.identity_material(url) == url.encode()  # foundry unchanged


def test_persist_stamp_overwrites_claim_kind(tmp_config):
    """Ingest stamp wins even if a Claim object still carries a model kind."""
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        spoofed = _range_claim(
            "c1", "nvd_21626", "pkg_runc", "CVE-2024-21626",
            m.SourceRecordKind.cisa_kev, _interval(end="1.1.11", end_incl=True),
            "runc 1.1.11 and earlier",
        )
        store.persist_extraction(
            conn, _doc("nvd_21626"), [_pkg_runc()], [spoofed],
            source_record_kind=store.attested_kind("nvd_record", "cpe"),
        )
        conn.commit()
        assert conn.execute("SELECT source_record_kind FROM claim").fetchone()[0] == "nvd_cpe"
    finally:
        conn.close()
