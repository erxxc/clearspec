"""GEI-9: version-range corroboration grouping.

Proves advisory grouping key, set comparison (not ±10%), cvss numeric ruler,
exploit_status enum agreement, marketing_only suspect exclusion, and never
auto-resolve. Zero network. Foundry ±10% path is covered by test_analyze.py.
"""

from __future__ import annotations

import inspect

from semianalyst.analyze import analyze_claims
from semianalyst.analyze import corroborate as corroborate_mod
from semianalyst.analyze.version_sets import compare_version_ranges
from semianalyst.store import ClaimView


def _cv(
    claim_id, *, claim_class, cve_id, entity_id="pkg_x", tier=3, publisher=None,
    value=None, unit="", version_range=None, exploit_status=None,
    workaround_text=None, completeness="complete", sparsity=None,
    metric=None,
) -> ClaimView:
    return ClaimView(
        claim_id=claim_id, doc_id=f"d_{claim_id}", entity_id=entity_id,
        metric=metric or claim_class, value=value, unit=unit or "",
        is_relative=False, baseline_entity=None, sparsity=sparsity,
        completeness=completeness, source_tier=tier,
        publisher=publisher if publisher is not None else f"pub_{claim_id}",
        claim_class=claim_class, source_record_kind=None, cve_id=cve_id,
        version_range=version_range, exploit_status=exploit_status,
        workaround_text=workaround_text,
    )


def _iv(start=None, start_incl=True, end=None, end_incl=True) -> dict:
    s = None if start is None else {"version": start, "inclusive": start_incl}
    e = None if end is None else {"version": end, "inclusive": end_incl}
    return {"intervals": [{"start": s, "end": e}]}


_INDEX = {"pkg_x": ["pkg_x"], "pkg_runc": ["pkg_runc"], "prod_openssh": ["prod_openssh"]}


# --- 1. Group key ---
def test_group_key_is_cve_package_claim_class():
    a = _cv("a", claim_class="affected_range", cve_id="CVE-2023-44487",
            entity_id="pkg_x", version_range=_iv(end="0.17.0", end_incl=False))
    b = _cv("b", claim_class="affected_range", cve_id="CVE-2023-39325",
            entity_id="pkg_x", version_range=_iv(end="1.20.10", end_incl=False),
            publisher="Other")
    # Same entity_id + claim_class but different cve_id → separate groups
    rep = analyze_claims([a, b], {"pkg_x": ["pkg_x"]})
    assert len(rep.assessments) == 2
    keys = {(x.cve_id, x.entity_id, x.claim_class) for x in rep.assessments}
    assert keys == {
        ("CVE-2023-44487", "pkg_x", "affected_range"),
        ("CVE-2023-39325", "pkg_x", "affected_range"),
    }
    assert a.advisory_group_key() == ("CVE-2023-44487", "pkg_x", "affected_range")
    assert a.advisory_group_key() != b.advisory_group_key()


def test_same_group_key_merges_publishers():
    nvd = _cv("nvd", claim_class="affected_range", cve_id="CVE-2024-21626",
              entity_id="pkg_runc", publisher="NVD",
              version_range=_iv(end="1.1.11", end_incl=True))
    ghsa = _cv("ghsa", claim_class="affected_range", cve_id="CVE-2024-21626",
               entity_id="pkg_runc", publisher="GitHub",
               version_range=_iv(start="1.0.0-rc93", end="1.1.11", end_incl=True))
    rep = analyze_claims([nvd, ghsa], {"pkg_runc": ["pkg_runc"]})
    assert len(rep.assessments) == 1
    assert rep.assessments[0].members == ["ghsa", "nvd"]


# --- 2. Range set comparison ---
def test_set_comparison_equal_corroborated():
    vr = _iv(start="1.0", end="2.0")
    a = _cv("a", claim_class="affected_range", cve_id="CVE-1",
            publisher="NVD", version_range=vr)
    b = _cv("b", claim_class="affected_range", cve_id="CVE-1",
            publisher="GitHub", version_range=vr)
    a_out = analyze_claims([a, b], _INDEX).assessments[0]
    assert a_out.set_relation == "equal"
    assert a_out.status == "corroborated"


def test_set_comparison_subset_contradicted():
    """runc: NVD unbounded ≤1.1.11 vs GHSA ≥rc93 ≤1.1.11 → subset → contradicted."""
    nvd = _cv("nvd", claim_class="affected_range", cve_id="CVE-2024-21626",
              entity_id="pkg_runc", publisher="NVD",
              version_range=_iv(end="1.1.11", end_incl=True))
    ghsa = _cv("ghsa", claim_class="affected_range", cve_id="CVE-2024-21626",
               entity_id="pkg_runc", publisher="GitHub",
               version_range=_iv(start="1.0.0-rc93", end="1.1.11", end_incl=True))
    assert compare_version_ranges(nvd.version_range, ghsa.version_range) == "subset"
    a = analyze_claims([nvd, ghsa], {"pkg_runc": ["pkg_runc"]}).assessments[0]
    assert a.status == "contradicted"
    assert a.set_relation == "subset"


def test_set_comparison_disjoint_contradicted():
    a = _cv("a", claim_class="patched_in", cve_id="CVE-X", publisher="NVD",
            version_range=_iv(start="1.0", end="1.5"))
    b = _cv("b", claim_class="patched_in", cve_id="CVE-X", publisher="Vendor",
            version_range=_iv(start="2.0", end="2.5"))
    assert compare_version_ranges(a.version_range, b.version_range) == "disjoint"
    out = analyze_claims([a, b], _INDEX).assessments[0]
    assert out.status == "contradicted"
    assert out.set_relation == "disjoint"


def test_set_comparison_overlap_contradicted():
    a = _cv("a", claim_class="patched_in", cve_id="CVE-2024-6387",
            entity_id="prod_openssh", publisher="NVD",
            version_range=_iv(start="8.6", end="9.8"))
    b = _cv("b", claim_class="patched_in", cve_id="CVE-2024-6387",
            entity_id="prod_openssh", publisher="OpenSSH",
            version_range=_iv(start="8.5p1", end="9.7p1"))
    rel = compare_version_ranges(a.version_range, b.version_range)
    assert rel in {"overlap", "subset", "disjoint"}
    assert rel != "equal"
    out = analyze_claims([a, b], {"prod_openssh": ["prod_openssh"]}).assessments[0]
    assert out.status == "contradicted"
    assert out.set_relation == rel


def test_ranges_do_not_use_numeric_tolerance():
    """Two ranges that would be 'close' as strings/numbers still use set math."""
    # ±10% on endpoints must NOT make these corroborated
    a = _cv("a", claim_class="affected_range", cve_id="CVE-Z", publisher="A",
            version_range=_iv(end="1.0"))
    b = _cv("b", claim_class="affected_range", cve_id="CVE-Z", publisher="B",
            version_range=_iv(end="1.05"))  # 5% apart numerically
    out = analyze_claims([a, b], _INDEX).assessments[0]
    assert out.set_relation != "equal"
    assert out.status == "contradicted"
    # Range branch must not consult the foundry numeric ruler; cvss may.
    src = inspect.getsource(corroborate_mod._assess_advisory)
    range_idx = src.find("if claim_class in _RANGE_CLASSES")
    cvss_idx = src.find('claim_class == "cvss"')
    assert 0 <= range_idx < cvss_idx
    assert "TOLERANCE_PCT" not in src[range_idx:cvss_idx]
    assert "compare_version_ranges" in inspect.getsource(corroborate_mod)


def test_empty_cve_id_does_not_collapse_groups():
    """Empty cve_id must not merge unrelated advisory range claims."""
    a = _cv("a", claim_class="affected_range", cve_id=None, publisher="A",
            version_range=_iv(end="1.0"))
    b = _cv("b", claim_class="affected_range", cve_id="", publisher="B",
            version_range=_iv(end="2.0"))
    rep = analyze_claims([a, b], _INDEX)
    assert len(rep.assessments) == 2
    assert {m for a in rep.assessments for m in a.members} == {"a", "b"}


def test_missing_version_range_in_group_is_not_agree():
    """SQL CHECK covers persist; in-memory missing range must not corroborate."""
    a = _cv("a", claim_class="affected_range", cve_id="CVE-M", publisher="A",
            version_range=_iv(end="1.0"))
    b = _cv("b", claim_class="affected_range", cve_id="CVE-M", publisher="B",
            version_range=None)
    out = analyze_claims([a, b], _INDEX).assessments[0]
    assert out.status == "contradicted"
    assert "missing_version_range" in out.flags
    assert set(out.members) == {"a", "b"}


# --- 3. cvss numeric + exploit_status enum ---
def test_cvss_reuses_numeric_ruler():
    a = _cv("a", claim_class="cvss", cve_id="CVE-1", publisher="NVD", value=9.8, unit="score")
    b = _cv("b", claim_class="cvss", cve_id="CVE-1", publisher="Vendor", value=9.0, unit="score")
    # (9.8-9.0)/9.8 = 8.2% <= 10 → agree → corroborated
    out = analyze_claims([a, b], _INDEX).assessments[0]
    assert out.status == "corroborated"
    assert out.set_relation is None

    c = _cv("c", claim_class="cvss", cve_id="CVE-2", publisher="NVD", value=9.8, unit="score",
            entity_id="pkg_y")
    d = _cv("d", claim_class="cvss", cve_id="CVE-2", publisher="Vendor", value=7.0, unit="score",
            entity_id="pkg_y")
    out2 = analyze_claims([c, d], {"pkg_y": ["pkg_y"]}).assessments[0]
    assert out2.status == "contradicted"


def test_exploit_status_enum_agreement():
    a = _cv("a", claim_class="exploit_status", cve_id="CVE-1", publisher="CISA",
            exploit_status="known_exploited")
    b = _cv("b", claim_class="exploit_status", cve_id="CVE-1", publisher="NVD",
            exploit_status="known_exploited")
    assert analyze_claims([a, b], _INDEX).assessments[0].status == "corroborated"

    c = _cv("c", claim_class="exploit_status", cve_id="CVE-2", publisher="CISA",
            exploit_status="known_exploited", entity_id="pkg_y")
    d = _cv("d", claim_class="exploit_status", cve_id="CVE-2", publisher="NVD",
            exploit_status="no_known_exploit", entity_id="pkg_y")
    out = analyze_claims([c, d], {"pkg_y": ["pkg_y"]}).assessments[0]
    assert out.status == "contradicted"
    assert "enum_disagree" in out.flags


# --- 4. marketing_only suspect exclusion ---
def test_marketing_only_cannot_corroborate_clean_catalog():
    vr = _iv(end="1.1.11", end_incl=True)
    clean = _cv("nvd", claim_class="affected_range", cve_id="CVE-M",
                publisher="NVD", version_range=vr)
    mkt = _cv("mkt", claim_class="affected_range", cve_id="CVE-M",
              publisher="Marketer", version_range=vr, completeness="marketing_only")
    out = analyze_claims([clean, mkt], _INDEX).assessments[0]
    assert out.status == "weakly_corroborated"
    assert "marketing_only" in out.flags
    assert out.status != "corroborated"


# --- 6. Never auto-resolve ---
def test_never_auto_resolve_both_claims_persist_in_members():
    nvd = _cv("nvd", claim_class="affected_range", cve_id="CVE-2024-21626",
              entity_id="pkg_runc", publisher="NVD",
              version_range=_iv(end="1.1.11", end_incl=True))
    ghsa = _cv("ghsa", claim_class="affected_range", cve_id="CVE-2024-21626",
               entity_id="pkg_runc", publisher="GitHub",
               version_range=_iv(start="1.0.0-rc93", end="1.1.11", end_incl=True))
    out = analyze_claims([nvd, ghsa], {"pkg_runc": ["pkg_runc"]}).assessments[0]
    assert set(out.members) == {"nvd", "ghsa"}
    # No helper picks a winning kind/range and drops the other
    src = inspect.getsource(corroborate_mod)
    assert "winning" not in src.lower() or "never" in src.lower()
    assert "source_record_kind" not in inspect.getsource(corroborate_mod._assess_advisory)
    # favored_tier is display-only
    assert out.favored_tier is not None
    assert out.status == "contradicted"


def test_no_function_drops_losing_claim():
    names = [n for n, _ in inspect.getmembers(corroborate_mod, inspect.isfunction)]
    forbidden = {"pick_winner", "resolve_range", "choose_kind", "auto_resolve"}
    assert not (forbidden & set(names))
