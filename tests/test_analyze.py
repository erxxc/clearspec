"""analyze v1 — the MVP acceptance golden + honest-domain unit cases.

The acceptance test loads three curated sources, persists them (with entity
reconciliation), runs analyze, and asserts the corroboration/divergence verdict.
Deterministic, offline — no model. The unit tests exercise the algorithm's honest
branches directly (these bite honest data; hostile-input guards are deferred).
"""

from __future__ import annotations

import json
from pathlib import Path

from semianalyst import store
from semianalyst.analyze import analyze_claims, run_analysis
from semianalyst.store import ClaimView, models as m

FIXTURE = Path(__file__).parent / "fixtures" / "analyze" / "tsmc_n2_corroboration"
SOURCES = ["source_foundry.json", "source_conf.json", "source_vendor.json"]


def _load(conn, path: Path) -> None:
    data = json.loads(path.read_text())
    doc = m.Document(**data["document"])
    entities = [m.Entity(**e) for e in data["entities"]]
    claims = [m.Claim(**c) for c in data["claims"]]
    store.persist_extraction(conn, doc, entities, claims)


def test_acceptance_golden(tmp_config):
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        for name in SOURCES:
            _load(conn, FIXTURE / name)
        conn.commit()
    finally:
        conn.close()

    report = run_analysis(tmp_config)
    expected = {k: v for k, v in json.loads((FIXTURE / "expected_analysis.json").read_text()).items()
                if not k.startswith("_")}
    assert report.to_dict() == expected


# --------------------------------------------------------------------------
# Unit cases — construct ClaimViews directly, no store.
# --------------------------------------------------------------------------
def _cv(claim_id, metric, value, tier, *, is_relative=True, baseline="b",
        sparsity=None, completeness="complete", unit="x", entity_id="e",
        publisher=None) -> ClaimView:
    # Default publisher is DISTINCT per claim: these unit cases exercise
    # tolerance/suspect logic, not the H1 publisher floor — H1 tests set a
    # shared publisher explicitly.
    return ClaimView(claim_id=claim_id, doc_id="d", entity_id=entity_id, metric=metric,
                     value=value, unit=unit, is_relative=is_relative, baseline_entity=baseline,
                     sparsity=sparsity, completeness=completeness, source_tier=tier,
                     publisher=publisher if publisher is not None else f"pub_{claim_id}")


_INDEX = {"e": ["e"], "b": ["b"]}


def test_two_clean_agree_is_corroborated():
    rep = analyze_claims([_cv("a", "m", 1.15, 2), _cv("z", "m", 1.18, 1)], _INDEX)
    assert rep.assessments[0].status == "corroborated"
    assert rep.assessments[0].confidence == "high"


def test_clean_plus_sparsity_agree_is_weakly_corroborated():
    """The enum-gap case: a clean number + a sparsity number agreeing within
    tolerance is NOT corroborated (only 1 non-suspect) — it's weakly_corroborated."""
    rep = analyze_claims([_cv("a", "m", 1.20, 2), _cv("z", "m", 1.25, 3, sparsity=True)], _INDEX)
    assert rep.assessments[0].status == "weakly_corroborated"
    assert "sparsity" in rep.assessments[0].flags


def test_clean_plus_marketing_only_agree_is_weakly_corroborated():
    """marketing_only is a suspect completeness (schema invariant) — the SECOND
    _suspect() door. A clean number + a marketing_only number agreeing within
    tolerance is weakly_corroborated, never corroborated: the marketing claim
    can't independently corroborate the clean one. Mirrors the sparsity case."""
    rep = analyze_claims([
        _cv("a", "m", 1.20, 2),
        _cv("z", "m", 1.25, 3, completeness="marketing_only"),
    ], _INDEX)
    assert rep.assessments[0].status == "weakly_corroborated"
    assert "marketing_only" in rep.assessments[0].flags


def test_spread_beyond_tolerance_is_contradicted_favoring_higher_tier():
    rep = analyze_claims([_cv("a", "m", 1.3, 2), _cv("z", "m", 1.8, 3, sparsity=True)], _INDEX)
    a = rep.assessments[0]
    assert a.status == "contradicted" and a.favored_tier == 2


def test_favored_tier_is_tier_blind_sparsity_does_not_override_tier():
    """favored_tier reports the lowest (highest-trust) tier present in a
    contradiction WITHOUT excluding suspect members. A tier-1 conference claim
    that is suspect (sparsity) still wins favored_tier over a tier-3 clean vendor
    claim — a sparsity flag does NOT promote the vendor number. (Whether sparsity
    SHOULD override tier is deferred question K; today it stays tier-blind,
    matching the reconciler. The excluding variant would have returned 3 here.)"""
    rep = analyze_claims([
        _cv("a", "m", 1.3, 1, sparsity=True),   # tier-1, but suspect
        _cv("z", "m", 1.8, 3),                   # tier-3, clean
    ], _INDEX)
    a = rep.assessments[0]
    assert a.status == "contradicted"
    assert a.favored_tier == 1


def test_zero_valued_group_is_not_false_corroborated():
    """Regression: a group like [0.0, 40.0] must NOT report zero spread /
    'corroborated'. The old (hi-lo)/lo guard returned 0.0 whenever the min was 0,
    asserting high-confidence agreement between numbers that agree on nothing."""
    rep = analyze_claims([_cv("a", "m", 0.0, 2), _cv("z", "m", 40.0, 1)], _INDEX)
    a = rep.assessments[0]
    assert a.status == "contradicted"
    assert a.spread_pct == 100.0
    two_zeros = analyze_claims([_cv("a", "m", 0.0, 2), _cv("z", "m", 0.0, 1)], _INDEX)
    assert two_zeros.assessments[0].status == "corroborated"   # genuine agreement at 0
    assert two_zeros.assessments[0].spread_pct == 0.0


def test_is_relative_is_load_bearing_in_group_key():
    """Two claims identical in (entity, metric, baseline, unit) and value, differing
    ONLY in is_relative, must NOT be compared: a ratio and an absolute-with-leftover-
    baseline are different claims about the world (nothing forces baseline=None when
    is_relative=False). Without is_relative in the key these collapse into one
    'corroborated' group; with it, two uncorroborated singletons. baseline and unit
    are held identical so they cannot mask whether is_relative is doing the work."""
    rep = analyze_claims([
        _cv("rel", "speed", 1.15, 2, is_relative=True, baseline="b", unit="x"),
        _cv("abs", "speed", 1.15, 2, is_relative=False, baseline="b", unit="x"),
    ], _INDEX)
    assert len(rep.assessments) == 2
    assert {a.status for a in rep.assessments} == {"uncorroborated"}


def test_dangling_baseline_is_flagged():
    rep = analyze_claims([_cv("a", "m", 3.0, 3, baseline="ghost")], {"e": ["e"]})
    assert "unresolved_baseline" in rep.assessments[0].flags


def test_tolerance_boundary():
    # spread is now a % of the larger-magnitude endpoint: (1.10-1.0)/1.10 = 9.1% <= 10
    within = analyze_claims([_cv("a", "m", 1.0, 2), _cv("z", "m", 1.10, 1)], _INDEX)
    assert within.assessments[0].status == "corroborated"
    # (1.12-1.0)/1.12 = 10.7% > 10
    beyond = analyze_claims([_cv("a", "m", 1.0, 2), _cv("z", "m", 1.12, 1)], _INDEX)
    assert beyond.assessments[0].status == "contradicted"


# --------------------------------------------------------------------------
# WS-2a (2026-08-18 gate): H1 publisher floor, key normalization, advisory
# flags, conflict surfacing, display Cf-stripping.
# --------------------------------------------------------------------------
def test_single_publisher_agreement_demotes_to_weakly():
    """H1: one publisher agreeing with itself is one voice, however many PDFs."""
    rep = analyze_claims([_cv("a", "m", 1.15, 3, publisher="VendorX"),
                          _cv("z", "m", 1.16, 3, publisher="VendorX")], _INDEX)
    a = rep.assessments[0]
    assert a.status == "weakly_corroborated"
    assert "single_publisher" in a.flags


def test_publisher_normalization_counts_variants_as_one():
    """Casing/whitespace publisher variants are ONE publisher for the floor."""
    rep = analyze_claims([_cv("a", "m", 1.15, 3, publisher="VendorX"),
                          _cv("z", "m", 1.16, 3, publisher="  vendorx ")], _INDEX)
    assert rep.assessments[0].status == "weakly_corroborated"


def test_distinct_publishers_corroborate():
    rep = analyze_claims([_cv("a", "m", 1.15, 3, publisher="VendorX"),
                          _cv("z", "m", 1.16, 3, publisher="FoundryY")], _INDEX)
    assert rep.assessments[0].status == "corroborated"


def test_metric_normalization_merges_casing_variants_into_one_group():
    """The group key is attacker-influenceable free text: 'Logic Speed' and
    'logic  speed' must land in ONE group (evasion via a casing variant)."""
    rep = analyze_claims([_cv("a", "Logic Speed", 1.15, 2),
                          _cv("z", "logic  speed", 1.16, 1)], _INDEX)
    assert len(rep.assessments) == 1
    assert rep.assessments[0].status == "corroborated"


def test_possible_split_metric_advisory_fires_on_near_identical_metrics():
    rep = analyze_claims([_cv("a", "logic_speed", 1.15, 2),
                          _cv("z", "logic_speeds", 2.4, 3)], _INDEX)
    assert len(rep.assessments) == 2
    for a in rep.assessments:
        assert "possible_split_metric" in a.flags


def test_possible_split_metric_does_not_fire_on_distinct_metrics():
    rep = analyze_claims([_cv("a", "logic_speed", 1.15, 2),
                          _cv("z", "power_draw", 2.4, 3)], _INDEX)
    for a in rep.assessments:
        assert "possible_split_metric" not in a.flags


def test_possible_slug_collision_advisory():
    """J: two stored entities sharing (entity_type, vendor) + a surface form."""
    detail = [
        {"entity_id": "e", "entity_type": "process_node", "vendor": "TSMC",
         "name": "N2", "aliases": ["N2", "2nm"]},
        {"entity_id": "e2", "entity_type": "process_node", "vendor": "tsmc",
         "name": "N2P", "aliases": ["N2P", "2nm"]},
    ]
    rep = analyze_claims([_cv("a", "m", 1.15, 2), _cv("z", "m", 1.16, 1)],
                         _INDEX, entities_detail=detail)
    assert "possible_slug_collision" in rep.assessments[0].flags

    disjoint = [dict(detail[0]), {"entity_id": "e2", "entity_type": "process_node",
                "vendor": "tsmc", "name": "N3", "aliases": ["N3"]}]
    rep = analyze_claims([_cv("a", "m", 1.15, 2)], _INDEX, entities_detail=disjoint)
    assert "possible_slug_collision" not in rep.assessments[0].flags


def test_identity_conflict_flag_and_report_serialization():
    """A persisted conflict surfaces as a flag on the entity's assessments and
    (only when present) as conflicts/conflict_counts in to_dict — a conflict-free
    report keeps the v3 dict shape for fixture stability."""
    conflict = m.Conflict(kind="identity_field", entity_id="e", doc_id="d2",
                          field="vendor", stored_value="V", offered_value="W",
                          created_at="2026-08-18T00:00:00+00:00")
    rep = analyze_claims([_cv("a", "m", 1.15, 2)], _INDEX,
                         conflicts=[conflict], conflict_counts={"e": 1})
    assert "identity_conflict" in rep.assessments[0].flags
    d = rep.to_dict()
    assert d["conflict_counts"] == {"e": 1}
    assert d["conflicts"][0]["offered_value"] == "W"

    clean = analyze_claims([_cv("a", "m", 1.15, 2)], _INDEX)
    assert "conflicts" not in clean.to_dict()
    assert "identity_conflict" not in clean.assessments[0].flags


def test_ansi_safe_strips_unicode_format_chars():
    """§2.8: bidi/zero-width/BOM (category Cf) are stripped; normal Unicode —
    including symbols honest specs use — survives."""
    from semianalyst.cli import _ansi_safe
    hostile = "safe‮ EVIL ​﻿⁦also⁩"
    cleaned = _ansi_safe(hostile)
    for cp in ("‮", "​", "﻿", "⁦", "⁩"):
        assert cp not in cleaned
    assert "EVIL" in cleaned and "also" in cleaned
    assert _ansi_safe("5 nm² at 1 µm pitch") == "5 nm² at 1 µm pitch"
    # Combined ANSI + Cf payload in one string (the offered_value shape).
    assert _ansi_safe("\x1b[31m‭X\x1b[0m") == "X"
