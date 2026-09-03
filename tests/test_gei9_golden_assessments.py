"""GEI-9: golden ingest→extract→report produces non-empty contradicted assessments.

Zero network. Reuses GEI-11 golden fixtures. Conflict is the product — never
auto-resolve; never ±10% on ranges.
"""
from __future__ import annotations

from semianalyst import store
from semianalyst.analyze import run_analysis
from semianalyst.extract import AnthropicExtractor, run_extract
from semianalyst.ingest import identity_doc_id, ingest_file

from tests.test_gei11_operator_ingest import (
    GOLDEN,
    _replay_for_goldens,
    _source_json,
)


def test_golden_ingest_produces_contradicted_range_assessments(tmp_config, tmp_path):
    """ingest-file -> extract (replay) -> report: assessments non-empty."""
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
    assert set(extracted.extracted) == set(doc_ids)

    analysis = run_analysis(tmp_config)
    assert analysis.assessments, "golden ingest path must produce advisory assessments"
    by_key = {
        (a.cve_id, a.entity_id, a.claim_class): a for a in analysis.assessments
        if a.claim_class
    }
    # Different CVE ids stay separate groups (44487 vs 39325).
    assert ("CVE-2023-44487", "pkg_x_net", "affected_range") in by_key
    assert ("CVE-2023-39325", "pkg_go_stdlib", "affected_range") in by_key

    runc = by_key[("CVE-2024-21626", "pkg_runc", "affected_range")]
    assert runc.status == "contradicted"
    assert runc.set_relation == "subset"
    assert len(runc.members) == 2  # both NVD + GHSA persist; never auto-resolve

    jenkins = by_key[("CVE-2024-23897", "pkg_jenkins_core", "affected_range")]
    assert jenkins.status == "contradicted"
    assert jenkins.set_relation in {"subset", "overlap"}
    assert jenkins.set_relation != "equal"
    assert len(jenkins.members) == 2

    openssh = by_key[("CVE-2024-6387", "prod_openssh", "patched_in")]
    assert openssh.status == "contradicted"
    assert openssh.set_relation in {"overlap", "disjoint", "subset"}
    assert openssh.set_relation != "equal"
    assert len(openssh.members) == 2
