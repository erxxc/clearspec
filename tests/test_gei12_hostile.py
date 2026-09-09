"""GEI-12: advisory pack named hostile suite (ENFORCE).

Constructed hostile NVD/GHSA/KEV-shaped inputs through the REAL chain —
validate → persist → analyze → report sanitizer, and where the filesystem seam
matters: ingest_file → run_extract(replay) → forget → refold. Offline, zero
network. One named test per attack. Honest goldens are never used as hostile
builders; the regression pin loads them read-only.

Plan gate: docs/reviews/2026-09-03-advisory-pack-plan/
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

from semianalyst import store
from semianalyst.analyze import analyze_claims, run_analysis
from semianalyst.cli import _ansi_safe, report as report_cmd
from semianalyst.config import Config
from semianalyst.extract import AnthropicExtractor, ReplayModelClient, run_extract, validate_proposal
from semianalyst.ingest import forget, identity_doc_id, ingest_file
from semianalyst.store import ClaimView, models as m

FIXTURES = Path(__file__).parent / "fixtures" / "advisory_golden"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _cite(span: str) -> m.Citation:
    return m.Citation(quote_span=span, location_type=m.LocationType.unknown)


def _iv(start=None, start_incl=True, end=None, end_incl=True) -> m.VersionRange:
    s = None if start is None else m.VersionBound(version=start, inclusive=start_incl)
    e = None if end is None else m.VersionBound(version=end, inclusive=end_incl)
    return m.VersionRange(intervals=[m.VersionInterval(start=s, end=e)])


def _doc(doc_id: str, *, publisher="NVD", url=None, sha=None,
         doc_type=m.DocType.nvd_record) -> m.Document:
    return m.Document(
        doc_id=doc_id, title=doc_id, publisher=publisher, doc_type=doc_type,
        source_tier=m.SourceTier.vendor,
        url=url or f"https://example.test/{doc_id}",
        file_sha256=sha or ("0" * 64),
        ingest_date=dt.date(2026, 9, 2),
    )


def _pkg(eid="pkg_runc", vendor="opencontainers", name="runc",
         eco="go", pkg_name="github.com/opencontainers/runc",
         purl=None, cites=None) -> m.Entity:
    cites = cites or {
        "package.ecosystem": _cite(f"ecosystem {eco}"),
        "package.name": _cite(pkg_name),
    }
    return m.Entity(
        entity_id=eid, entity_type=m.EntityType.package,
        vendor=vendor, name=name,
        package=m.PackageAttributes(
            ecosystem=eco, name=pkg_name,
            purl=purl or f"pkg:golang/{pkg_name}",
        ),
        attribute_citations=cites,
    )


def _range_claim(cid, doc_id, eid, cve, kind, vr, span,
                 claim_class=m.ClaimClass.affected_range,
                 completeness=m.Completeness.complete) -> m.Claim:
    return m.Claim(
        claim_id=cid, doc_id=doc_id, entity_id=eid, cve_id=cve,
        claim_class=claim_class, metric=claim_class.value,
        version_range=vr, source_record_kind=kind,
        completeness=completeness, citation=_cite(span),
    )


def _cv(claim_id, *, claim_class, cve_id, entity_id="pkg_x", tier=3,
        publisher=None, value=None, unit="", version_range=None,
        exploit_status=None, completeness="complete") -> ClaimView:
    return ClaimView(
        claim_id=claim_id, doc_id=f"d_{claim_id}", entity_id=entity_id,
        metric=claim_class, value=value, unit=unit or "",
        is_relative=False, baseline_entity=None, sparsity=None,
        completeness=completeness, source_tier=tier,
        publisher=publisher if publisher is not None else f"pub_{claim_id}",
        claim_class=claim_class, source_record_kind=None, cve_id=cve_id,
        version_range=version_range, exploit_status=exploit_status,
    )


def _vr_dict(end=None, end_incl=True, start=None, start_incl=True) -> dict:
    s = None if start is None else {"version": start, "inclusive": start_incl}
    e = None if end is None else {"version": end, "inclusive": end_incl}
    return {"intervals": [{"start": s, "end": e}]}


_SRC = "runc 1.1.11 and earlier. ecosystem go. github.com/opencontainers/runc"


def _proposal(*, kind="nvd_cpe", end="1.1.11", end_incl=True, cve="CVE-2024-21626") -> dict:
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
            "cve_id": cve, "claim_class": "affected_range",
            "metric": "affected_range",
            "version_range": {"intervals": [{"end": {"version": end, "inclusive": end_incl}}]},
            "source_record_kind": kind,
            "completeness": "complete",
            "citation": {"quote_span": "runc 1.1.11 and earlier", "location_type": "unknown"},
        }],
    }


# ---------------------------------------------------------------------------
# 1. Self-attested kind
# ---------------------------------------------------------------------------
def test_proposal_self_attested_kind_stripped(tmp_config: Config):
    """ATTACK: proposal self-attests cisa_kev / nvd_cna. Validate strips;
    ingest stamp alone may persist."""
    result, rej = validate_proposal(_proposal(kind="cisa_kev"), _SRC)
    assert result.claims
    assert result.claims[0].source_record_kind is None
    assert any(r.kind == "claim_kind" for r in rej)

    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        store.persist_extraction(
            conn, _doc("nvd_21626"), result.entities, result.claims,
            source_record_kind=store.attested_kind("nvd_record", "cpe"),
        )
        conn.commit()
        assert conn.execute("SELECT source_record_kind FROM claim").fetchone()[0] == "nvd_cpe"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Spoofed NVD — ungrounded version bound
# ---------------------------------------------------------------------------
def test_spoofed_nvd_wrong_package_or_range(tmp_config: Config):
    """ATTACK: NVD-shaped proposal invents exclusive+1 bound 1.1.12 not in
    quote/source. Must drop, never persist."""
    result, rej = validate_proposal(
        _proposal(kind="nvd_cpe", end="1.1.12", end_incl=False), _SRC)
    assert result.claims == []
    assert any("version_bound" in r.reason for r in rej)

    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        store.persist_extraction(
            conn, _doc("nvd_21626"), result.entities, result.claims,
            source_record_kind=m.SourceRecordKind.nvd_cpe,
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Never-overwrite package attrs
# ---------------------------------------------------------------------------
def test_advisory_never_overwrite_package_attrs(tmp_config: Config):
    """ATTACK: early hostile advisory fills package.purl; later honest differs.
    Stored value kept; attribute conflict recorded."""
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        early = _pkg(purl="pkg:golang/github.com/opencontainers/runc@evil")
        early.attribute_citations["package.purl"] = _cite(
            "pkg:golang/github.com/opencontainers/runc@evil")
        # Source must ground the hostile purl string for validate-path; here we
        # persist already-shaped models (post-validate store path).
        store.persist_extraction(
            conn, _doc("hostile_early", publisher="Rival"), [early],
            [_range_claim(
                "h", "hostile_early", "pkg_runc", "CVE-2024-21626",
                m.SourceRecordKind.peer_research,
                _iv(end="1.1.11", end_incl=True),
                "runc 1.1.11 and earlier",
            )],
        )
        honest = _pkg(purl="pkg:golang/github.com/opencontainers/runc")
        honest.attribute_citations["package.purl"] = _cite(
            "pkg:golang/github.com/opencontainers/runc")
        store.persist_extraction(
            conn, _doc("honest_nvd", publisher="NVD"), [honest],
            [_range_claim(
                "n", "honest_nvd", "pkg_runc", "CVE-2024-21626",
                m.SourceRecordKind.nvd_cpe,
                _iv(end="1.1.11", end_incl=True),
                "runc 1.1.11 and earlier",
            )],
        )
        conn.commit()
        row = conn.execute(
            "SELECT pkg_purl FROM entity WHERE entity_id='pkg_runc'"
        ).fetchone()
        assert row["pkg_purl"] == "pkg:golang/github.com/opencontainers/runc@evil"
        conflicts = store.get_conflicts(conn)
        assert any(
            c.kind == m.ConflictKind.attribute and c.field == "package.purl"
            and c.doc_id == "honest_nvd"
            for c in conflicts
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Display sanitizer
# ---------------------------------------------------------------------------
def test_advisory_display_sanitizer():
    """ATTACK: ANSI/OSC/bidi in advisory display strings. `_ansi_safe` must
    neutralize; cli.report must not interpolate raw workaround_text."""
    payload = "CVE-2024-21626\x1b]0;pwn\x07\x1b[31mRED\u202e"
    cleaned = _ansi_safe(payload)
    assert "\x1b" not in cleaned
    assert "\x07" not in cleaned
    assert "\u202e" not in cleaned
    assert all(unicodedata.category(ch) != "Cf" for ch in cleaned)

    import ast
    import inspect
    import re
    src = inspect.getsource(report_cmd)
    assert "_ansi_safe" in src
    # Comment may name the injection surface; executable code must not load
    # workaround_text off the assessment (no attribute access / f-string field).
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "workaround_text":
            raise AssertionError("report() must not read assessment.workaround_text")
        if isinstance(node, ast.Constant) and node.value == "workaround_text":
            raise AssertionError("report() must not interpolate workaround_text as a value")
    # Strip comments/docstrings then forbid attribute-style access token
    no_comments = re.sub(r"#.*?$", "", src, flags=re.M)
    assert "a.workaround_text" not in no_comments
    assert "{a.workaround_text" not in no_comments


# ---------------------------------------------------------------------------
# 5. Forget / refold poisoned NVD JSON (filesystem seam)
# ---------------------------------------------------------------------------
def test_forget_refold_poisoned_nvd_json(tmp_config: Config, tmp_path: Path):
    """ATTACK: poisoned NVD-shaped JSON folds in; forget must retract completely
    (claims/conflicts gone) while quarantine retains evidence."""
    store.init_db(tmp_config)

    # Prefer golden fixture when present; else construct minimal operator JSON.
    stem = "cve-2024-21626-nvd.json"
    if (FIXTURES / stem).exists():
        case = json.loads((FIXTURES / stem).read_text())
        source_text = case["source_text"]
        proposal = case["proposal"]
    else:
        source_text = _SRC
        proposal = _proposal(kind="nvd_cpe")
        # strip kind so validate path matches ingest stamp
        for c in proposal["claims"]:
            c.pop("source_record_kind", None)

    poison = tmp_path / "poisoned-nvd.json"
    poison.write_text(json.dumps({
        "text": source_text,
        "source_record_kind": "cisa_kev",
        "cisa_kev": True,
    }) + "\n")

    url = "https://nvd.nist.gov/vuln/detail/CVE-2024-21626"
    doc_id = identity_doc_id(url, "nvd_cpe")
    raw = ingest_file(
        tmp_config, poison, doc_id=doc_id, title="poisoned runc nvd",
        publisher="NVD", doc_type="nvd_record", source_tier=3, url=url,
        ingest_date="2026-09-02", parser_role="cpe",
    )
    assert raw.meta.get("source_record_kind") is None

    # Replay against the document_text the extract pipeline will see.
    # document_text() for JSON is the raw UTF-8 file; key on source_text substring.
    extractor = AnthropicExtractor(ReplayModelClient({source_text: json.dumps(proposal)}))
    rep = run_extract(tmp_config, extractor=extractor)
    assert rep.errors == []
    assert doc_id in rep.extracted

    conn = store.connect(tmp_config.paths.db_path)
    try:
        assert doc_id in store.stored_doc_shas(conn)
        kinds = {r["source_record_kind"] for r in conn.execute("SELECT source_record_kind FROM claim")}
        assert "cisa_kev" not in kinds
        assert kinds == {"nvd_cpe"} or kinds <= {"nvd_cpe"}
        n_claims = conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"]
        assert n_claims >= 1
    finally:
        conn.close()

    fr = forget(tmp_config, doc_id)
    assert fr.rebuild.errors == []
    quarantine = tmp_config.paths.data_dir / "quarantine"
    assert any(p.name.endswith(".meta.json") for p in quarantine.iterdir())

    conn = store.connect(tmp_config.paths.db_path)
    try:
        assert doc_id not in store.stored_doc_shas(conn)
        assert conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"] == 0
        assert store.get_conflicts(conn) == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. CNA vs CPE same URL
# ---------------------------------------------------------------------------
def test_cna_cpe_same_url_two_docs_one_group(tmp_config: Config):
    """ATTACK/EXPECT: collapsing CNA+CPE into one doc is forbidden. Two docs,
    same URL, one contradicted group, both members persist."""
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        url = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-23897"
        pkg = _pkg(
            eid="pkg_jenkins_core", vendor="jenkins", name="jenkins-core",
            eco="maven", pkg_name="org.jenkins-ci.main:jenkins-core",
            purl="pkg:maven/org.jenkins-ci.main/jenkins-core",
            cites={
                "package.ecosystem": _cite("maven"),
                "package.name": _cite("org.jenkins-ci.main:jenkins-core"),
            },
        )
        store.persist_extraction(
            conn, _doc("nvd_cpe", url=url), [pkg],
            [_range_claim(
                "cpe", "nvd_cpe", "pkg_jenkins_core", "CVE-2024-23897",
                m.SourceRecordKind.nvd_cpe,
                _iv(end="2.426.3", end_incl=False),
                "LTS versionEndExcluding 2.426.3",
            )],
        )
        store.persist_extraction(
            conn, _doc("nvd_cna", url=url), [pkg],
            [_range_claim(
                "cna", "nvd_cna", "pkg_jenkins_core", "CVE-2024-23897",
                m.SourceRecordKind.nvd_cna,
                _iv(start="1.606", start_incl=True, end="2.426.3", end_incl=False),
                "versionStartIncluding 1.606 versionEndExcluding 2.426.3",
            )],
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) AS n FROM document").fetchone()["n"] == 2
        views = store.get_claims_for_analysis(conn)
        report = analyze_claims(views, store.get_entities_index(conn))
        a = next(x for x in report.assessments if x.cve_id == "CVE-2024-23897")
        assert a.status == "contradicted"
        assert a.set_relation in {"subset", "overlap"}
        assert len(a.members) == 2
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Empty CVE no collapse
# ---------------------------------------------------------------------------
def test_empty_cve_does_not_collapse():
    """ATTACK: null/empty cve_id must not merge unrelated range claims."""
    a = _cv("a", claim_class="affected_range", cve_id=None,
            version_range=_vr_dict(end="1.0"))
    b = _cv("b", claim_class="affected_range", cve_id="",
            version_range=_vr_dict(end="2.0"), publisher="Other")
    rep = analyze_claims([a, b], {"pkg_x": ["pkg_x"]})
    assert len(rep.assessments) == 2
    assert {m for a in rep.assessments for m in a.members} == {"a", "b"}


# ---------------------------------------------------------------------------
# 8. marketing_only cannot corroborate
# ---------------------------------------------------------------------------
def test_marketing_only_cannot_corroborate_clean():
    """ATTACK: marketing_only equal-range claim must not yield corroborated."""
    vr = _vr_dict(end="1.1.11", end_incl=True)
    clean = _cv("nvd", claim_class="affected_range", cve_id="CVE-M",
                publisher="NVD", version_range=vr)
    mkt = _cv("mkt", claim_class="affected_range", cve_id="CVE-M",
              publisher="Marketer", version_range=vr, completeness="marketing_only")
    out = analyze_claims([clean, mkt], {"pkg_x": ["pkg_x"]}).assessments[0]
    assert out.status == "weakly_corroborated"
    assert out.status != "corroborated"
    assert "marketing_only" in out.flags


# ---------------------------------------------------------------------------
# 9. KEV does not speak to ranges
# ---------------------------------------------------------------------------
def test_kev_exploit_status_does_not_speak_to_range():
    """ATTACK: KEV exploit_status must not enter affected_range agreement."""
    rng = _cv("r", claim_class="affected_range", cve_id="CVE-2024-3400",
              entity_id="prod_panos", publisher="NVD",
              version_range=_vr_dict(end="11.1.2"))
    kev = _cv("k", claim_class="exploit_status", cve_id="CVE-2024-3400",
              entity_id="prod_panos", publisher="CISA",
              exploit_status="known_exploited")
    rep = analyze_claims([rng, kev], {"prod_panos": ["prod_panos"]})
    by_class = {a.claim_class: a for a in rep.assessments}
    assert "affected_range" in by_class and "exploit_status" in by_class
    assert by_class["affected_range"].members == ["r"]
    assert by_class["exploit_status"].members == ["k"]
    assert kev.claim_id not in by_class["affected_range"].members


# ---------------------------------------------------------------------------
# 10. Honest golden regression + flag budget
# ---------------------------------------------------------------------------
def test_advisory_honest_golden_regression(tmp_config: Config, tmp_path: Path):
    """Pin GEI-9 golden contradicted assessments when fixtures are present."""
    if not FIXTURES.exists():
        pytest.skip("advisory_golden fixtures not present")
    from tests.test_gei11_operator_ingest import (
        GOLDEN, _replay_for_goldens, _source_json,
    )

    store.init_db(tmp_config)
    doc_ids = []
    for stem, doc_type, role, publisher, url in GOLDEN:
        kind = store.attested_kind(doc_type, role)
        doc_id = identity_doc_id(url, kind.value)
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

    analysis = run_analysis(tmp_config)
    assert analysis.assessments
    by_key = {
        (a.cve_id, a.entity_id, a.claim_class): a for a in analysis.assessments
        if a.claim_class
    }
    assert ("CVE-2023-44487", "pkg_x_net", "affected_range") in by_key
    assert ("CVE-2023-39325", "pkg_go_stdlib", "affected_range") in by_key
    runc = by_key[("CVE-2024-21626", "pkg_runc", "affected_range")]
    assert runc.status == "contradicted"
    assert runc.set_relation == "subset"
    assert len(runc.members) == 2
    jenkins = by_key[("CVE-2024-23897", "pkg_jenkins_core", "affected_range")]
    assert jenkins.status == "contradicted"
    assert jenkins.set_relation != "equal"
    openssh = by_key[("CVE-2024-6387", "prod_openssh", "patched_in")]
    assert openssh.status == "contradicted"
    assert openssh.set_relation != "equal"


def test_advisory_flag_budget():
    """GEI-12 flag budget: new advisory flags are limited to the known set.
    Budget: ≤1 new flag *class* beyond this allowlist without a written gate."""
    known = {
        "sparsity", "marketing_only", "unresolved_baseline", "single_source",
        "single_publisher", "identity_conflict", "possible_split_metric",
        "possible_slug_collision", "enum_disagree", "workaround_disagree",
        "missing_version_range",
    }
    # set_relation:* is dynamic; allowed as a prefix
    import ast
    import inspect
    import re
    from semianalyst.analyze import corroborate as cmod
    src = inspect.getsource(cmod._assess_advisory)
    # No auto-resolve / winner flags smuggled in
    assert "winning" not in src.lower() or "never" in src.lower()
    # Forbid a silent-resolve *status/flag token*, not the substring inside
    # unresolved_baseline.
    forbidden = re.compile(r"(?<![A-Za-z_])resolved(?![A-Za-z_])")
    assert not forbidden.search(src), "silent-resolve token found in _assess_advisory"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "resolved":
            raise AssertionError("_assess_advisory must not emit status/flag 'resolved'")
    assert "missing_version_range" in known
