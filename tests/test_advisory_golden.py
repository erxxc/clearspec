"""GEI-8 offline golden: operator-fed JSON proposals for GEI-10 conflicts.

No network. Does not live-fetch NVD/GHSA. Each fixture is a proposal that
extract_advisory_v1 would emit; validate_proposal / build_result is the gate.
A plain pytest must not claim live coverage — there is no un-gated live test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from semianalyst.extract import PromptVersion, build_result, validate_proposal
from semianalyst.store import models as m

FIXTURES = Path(__file__).parent / "fixtures" / "advisory_golden"
CASES = sorted(FIXTURES.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_advisory_offline_golden_validates(path: Path):
    case = _load(path)
    result, rej = validate_proposal(case["proposal"], case["source_text"])
    expect = case["expect"]
    kept_ids = [c.claim_id for c in result.claims]
    assert kept_ids == expect["claim_ids"], rej
    ends = []
    starts = []
    for claim in result.claims:
        assert claim.source_record_kind is None  # ingest-attested, not model-emitted
        if expect.get("claim_class"):
            assert claim.claim_class.value == expect["claim_class"]
        if expect.get("cve_id"):
            assert claim.cve_id == expect["cve_id"]
        vr = claim.version_range
        assert vr is not None
        if expect.get("interval_count"):
            assert len(vr.intervals) == expect["interval_count"]
        if expect.get("unbounded_start"):
            assert vr.intervals[0].start is None
        for interval in vr.intervals:
            if interval.start is not None:
                starts.append(interval.start.version)
            if interval.end is not None:
                ends.append(interval.end.version)
    if "end_versions" in expect:
        assert ends == expect["end_versions"]
    if "start_versions" in expect:
        assert starts == expect["start_versions"]
    # build_result is the persist-facing path
    built = build_result(case["proposal"], case["source_text"])
    assert [c.claim_id for c in built.claims] == expect["claim_ids"]


def test_advisory_prompt_is_listed_and_immutable_header():
    pv = PromptVersion.load("extract_advisory_v1")
    assert "extract_advisory_v1" in PromptVersion.list_available()
    assert "IMMUTABLE" in pv.text or "PROMPT VERSIONING" in pv.text
    assert "quote_span" in pv.text


def test_gei10_runc_subset_conflict_survives_validate():
    """NVD unbounded 1.1.11 vs GHSA >= rc93: both claims validate. No winner."""
    nvd = _load(FIXTURES / "cve-2024-21626-nvd.json")
    ghsa = _load(FIXTURES / "cve-2024-21626-ghsa.json")
    nvd_r, _ = validate_proposal(nvd["proposal"], nvd["source_text"])
    ghsa_r, _ = validate_proposal(ghsa["proposal"], ghsa["source_text"])
    nvd_end = nvd_r.claims[0].version_range.intervals[0]
    ghsa_iv = ghsa_r.claims[0].version_range.intervals[0]
    assert nvd_end.start is None
    assert nvd_end.end.version == "1.1.11"
    assert ghsa_iv.start.version == "1.0.0-rc93"
    assert nvd_r.claims[0].advisory_group_key() == ghsa_r.claims[0].advisory_group_key()
    # grouping is GEI-9; we only show the keys match so the fight is representable
    assert nvd_r.claims[0].advisory_group_key() == (
        "CVE-2024-21626", "pkg_runc", "affected_range"
    )


def test_gei10_jenkins_cna_vs_cpe_same_url_two_proposals():
    cpe = _load(FIXTURES / "cve-2024-23897-cpe.json")
    cna = _load(FIXTURES / "cve-2024-23897-cna.json")
    cpe_r, _ = validate_proposal(cpe["proposal"], cpe["source_text"])
    cna_r, _ = validate_proposal(cna["proposal"], cna["source_text"])
    assert cpe_r.claims[0].version_range.intervals[0].start is None
    assert cna_r.claims[0].version_range.intervals[0].start.version == "1.606"
    assert cpe_r.claims[0].advisory_group_key() == cna_r.claims[0].advisory_group_key()


def test_gei10_cve_id_split_44487_vs_39325():
    xnet = _load(FIXTURES / "cve-2023-44487-xnet.json")
    std = _load(FIXTURES / "cve-2023-39325-stdlib.json")
    a, _ = validate_proposal(xnet["proposal"], xnet["source_text"])
    b, _ = validate_proposal(std["proposal"], std["source_text"])
    assert a.claims[0].cve_id == "CVE-2023-44487"
    assert b.claims[0].cve_id == "CVE-2023-39325"
    assert a.claims[0].advisory_group_key() != b.claims[0].advisory_group_key()


def test_gei10_openssh_disjoint_patched_in():
    nvd = _load(FIXTURES / "cve-2024-6387-nvd.json")
    vendor = _load(FIXTURES / "cve-2024-6387-vendor.json")
    n, _ = validate_proposal(nvd["proposal"], nvd["source_text"])
    v, _ = validate_proposal(vendor["proposal"], vendor["source_text"])
    assert n.claims[0].version_range.intervals[0].end.version == "9.8"
    assert v.claims[0].version_range.intervals[0].end.version == "9.7p1"
    assert n.claims[0].claim_class is m.ClaimClass.patched_in
    assert v.claims[0].claim_class is m.ClaimClass.patched_in
