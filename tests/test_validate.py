"""Deterministic, offline coverage of the validation/normalization pipeline.

Unit tests of extract/validate.py against constructed proposals — NOT a substitute
for the live golden. Every rule the plan promised, plus every GATE-2 fix, is
exercised here so nothing ships untested.
"""

from __future__ import annotations

import json
from pathlib import Path

from semianalyst.extract import build_result, validate_proposal
from semianalyst.extract.pdf import pdf_to_text

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES_DIR / "tsmc_n2_2025"


def _source() -> str:
    return pdf_to_text((GOLDEN / "raw.pdf").read_bytes())


def _expected() -> dict:
    data = json.loads((GOLDEN / "expected.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _entity(eid: str = "e", vendor: str = "V", name: str = "N") -> dict:
    return {"entity_id": eid, "entity_type": "chip", "vendor": vendor, "name": name,
            "aliases": [], "node": None, "chip": None, "attribute_citations": {}}


def _claim(**over) -> dict:
    base = {
        "claim_id": "c", "doc_id": "d", "entity_id": "e", "claim_class": "performance",
        "metric": "m", "value": 1.0, "unit": "x",
        "comparison": {"is_relative": True, "baseline_entity": None, "baseline_stated": False},
        "conditions": {"stated_caveats": []}, "completeness": "complete",
        "citation": {"quote_span": "GROUNDED", "location_type": "body"},
        "corroboration": {"status": "uncorroborated", "related_claim_ids": []},
    }
    base.update(over)
    return base


def _golden_proposal() -> dict:
    """A plausible model proposal for the golden doc. location_type='body' (validate
    must force 'unknown') and hvm 'December 2025' (must normalize to 2025-12-01)."""
    return {
        "entities": [
            {
                "entity_id": "tsmc_n2", "entity_type": "process_node", "vendor": "TSMC",
                "name": "N2", "aliases": ["N2"],
                "node": {"density_mtx_mm2": None, "transistor_type": "gaa_nanosheet",
                         "backside_power": False, "hvm_date_claimed": "December 2025",
                         "hvm_date_actual": None},
                "chip": None,
                "attribute_citations": {
                    "node.transistor_type": {"page": 1, "location_type": "body",
                        "quote_span": "N2 is TSMC's first gate-all-around (GAA) nanosheet process node."},
                    "node.backside_power": {"page": 1, "location_type": "body",
                        "quote_span": "N2 does not use backside power delivery."},
                    "node.hvm_date_claimed": {"page": 1, "location_type": "body",
                        "quote_span": "N2 enters high-volume manufacturing in December 2025."},
                },
            },
            {
                "entity_id": "tsmc_n3e", "entity_type": "process_node", "vendor": "TSMC",
                "name": "N3E", "aliases": ["N3E"],
                "node": {"density_mtx_mm2": None, "transistor_type": "finfet",
                         "backside_power": False, "hvm_date_claimed": None,
                         "hvm_date_actual": None},
                "chip": None,
                "attribute_citations": {
                    "node.transistor_type": {"page": 1, "location_type": "body",
                        "quote_span": "The prior-generation TSMC N3E node uses FinFET transistors."},
                    "node.backside_power": {"page": 1, "location_type": "body",
                        "quote_span": "N3E does not use backside power delivery."},
                },
            },
        ],
        "claims": [
            {
                "claim_id": "tsmc_n2_logic_speed", "doc_id": "tsmc_n2_2025",
                "entity_id": "tsmc_n2", "claim_class": "performance", "metric": "logic_speed",
                "value": 1.15, "unit": "x",
                "comparison": {"is_relative": True, "baseline_entity": "tsmc_n3e", "baseline_stated": True},
                "conditions": {"workload": None, "precision": None, "sparsity": None,
                               "thermal_config": None, "stated_caveats": ["at iso-power"]},
                "completeness": "complete",
                "citation": {"page": 1, "location_type": "body",
                             "quote_span": "TSMC N2 delivers 1.15x logic speed at iso-power versus N3E."},
                "corroboration": {"status": "uncorroborated", "related_claim_ids": []},
            }
        ],
    }


def test_golden_proposal_validates_to_expected():
    """The whole pipeline, deterministically: proposal -> grounded == expected.json."""
    result = build_result(_golden_proposal(), _source())
    assert result.model_dump(mode="json") == _expected()


def test_ungrounded_claim_is_dropped():
    p = {"entities": [_entity("e")], "claims": [_claim(
        citation={"quote_span": "a sentence absent from the source", "location_type": "body"})]}
    result, rej = validate_proposal(p, "the real source text")
    assert result.claims == []
    assert any(r.kind == "claim" and "not found" in r.reason for r in rej)


def test_ungrounded_entity_attribute_is_nulled():
    src = "N2 exists."
    p = {"entities": [{"entity_id": "tsmc_n2", "entity_type": "process_node", "vendor": "TSMC",
        "name": "N2", "aliases": [], "node": {"transistor_type": "cfet"}, "chip": None,
        "attribute_citations": {"node.transistor_type": {
            "quote_span": "N2 uses CFET transistors", "location_type": "body"}}}], "claims": []}
    result, rej = validate_proposal(p, src)
    assert result.entities[0].node.transistor_type is None
    assert "node.transistor_type" not in result.entities[0].attribute_citations
    assert any(r.kind == "entity_attribute" for r in rej)


def test_relative_claim_with_absolute_unit_is_dropped():
    src = "Chip X hits 5 TB/s versus Y."
    p = {"entities": [_entity("e")], "claims": [_claim(unit="TB/s", value=5,
        comparison={"is_relative": True, "baseline_entity": "y", "baseline_stated": True},
        citation={"quote_span": "Chip X hits 5 TB/s versus Y.", "location_type": "body"})]}
    result, rej = validate_proposal(p, src)
    assert result.claims == []
    assert any("absolutized" in r.reason for r in rej)


def test_ratio_unit_without_is_relative_is_dropped():
    src = "N2 is 1.15x versus N3E."
    p = {"entities": [_entity("e")], "claims": [_claim(value=1.15, unit="x",
        comparison={"is_relative": False, "baseline_entity": None, "baseline_stated": False},
        citation={"quote_span": "N2 is 1.15x versus N3E.", "location_type": "body"})]}
    result, rej = validate_proposal(p, src)
    assert result.claims == []
    assert any("undeclared relativity" in r.reason for r in rej)


def test_absolute_percentage_survives():
    """A 65% yield is an absolute rate, not a comparison — it must NOT be dropped."""
    src = "N2 yield is 65% at maturity."
    p = {"entities": [_entity("tsmc_n2", "TSMC", "N2")],
         "claims": [_claim(entity_id="tsmc_n2", claim_class="yield", metric="yield_rate",
             value=65, unit="%",
             comparison={"is_relative": False, "baseline_entity": None, "baseline_stated": False},
             citation={"quote_span": "N2 yield is 65% at maturity.", "location_type": "body"})]}
    result, _ = validate_proposal(p, src)
    assert len(result.claims) == 1
    assert result.claims[0].unit == "%" and result.claims[0].value == 65


def test_relative_percentage_survives():
    src = "N2 is 30% lower power than N3E."
    p = {"entities": [_entity("tsmc_n2", "TSMC", "N2"), _entity("tsmc_n3e", "TSMC", "N3E")],
         "claims": [_claim(entity_id="tsmc_n2", claim_class="power", metric="power_reduction",
             value=30, unit="%",
             comparison={"is_relative": True, "baseline_entity": "tsmc_n3e", "baseline_stated": True},
             citation={"quote_span": "N2 is 30% lower power than N3E.", "location_type": "body"})]}
    result, _ = validate_proposal(p, src)
    assert len(result.claims) == 1
    assert result.claims[0].comparison.is_relative and result.claims[0].unit == "%"


def test_unit_normalization_to_canonical():
    src = "Bandwidth is 2 TB/s in this design."
    p = {"entities": [_entity("e")], "claims": [_claim(unit="TB/s", value=2,
        comparison={"is_relative": False, "baseline_entity": None, "baseline_stated": False},
        citation={"quote_span": "Bandwidth is 2 TB/s in this design.", "location_type": "body"})]}
    result, _ = validate_proposal(p, src)
    assert len(result.claims) == 1
    assert result.claims[0].value == 2000.0 and result.claims[0].unit == "GB/s"


def test_unit_normalization_power_kw():
    src = "TDP is 2 kW under load."
    p = {"entities": [_entity("chipx", "V", "X")],
         "claims": [_claim(entity_id="chipx", claim_class="power", metric="tdp", value=2, unit="kW",
             comparison={"is_relative": False, "baseline_entity": None, "baseline_stated": False},
             citation={"quote_span": "TDP is 2 kW under load.", "location_type": "body"})]}
    result, _ = validate_proposal(p, src)
    assert result.claims[0].value == 2000.0 and result.claims[0].unit == "W"


def test_claim_referencing_unknown_entity_is_dropped():
    """A hostile doc can't attach a claim to an entity it didn't extract."""
    src = "Ghost claims 3x."
    p = {"entities": [_entity("real", "V", "R")],
         "claims": [_claim(claim_id="ghost", entity_id="not_extracted", value=3, unit="x",
             comparison={"is_relative": True, "baseline_entity": None, "baseline_stated": False},
             citation={"quote_span": "Ghost claims 3x.", "location_type": "body"})]}
    result, rej = validate_proposal(p, src)
    assert result.claims == []
    assert any(r.kind == "claim" and "absent from this document" in r.reason for r in rej)


def test_completeness_downgraded_when_baseline_missing():
    """The model's completeness label is not trusted: relative + no baseline -> missing_baseline."""
    src = "N2 is 1.15x faster."
    p = {"entities": [_entity("tsmc_n2", "TSMC", "N2")],
         "claims": [_claim(entity_id="tsmc_n2", value=1.15, unit="x", completeness="complete",
             comparison={"is_relative": True, "baseline_entity": None, "baseline_stated": False},
             citation={"quote_span": "N2 is 1.15x faster.", "location_type": "body"})]}
    result, _ = validate_proposal(p, src)
    assert result.claims[0].completeness.value == "missing_baseline"


def test_marketing_only_tagging_cross_vendor_sparsity():
    src = "Ours is 2x versus NVDA with sparsity on."
    p = {"entities": [
        {"entity_id": "amd_x", "entity_type": "chip", "vendor": "AMD", "name": "X",
         "aliases": [], "node": None, "chip": None, "attribute_citations": {}},
        {"entity_id": "nvda_y", "entity_type": "chip", "vendor": "NVIDIA", "name": "Y",
         "aliases": [], "node": None, "chip": None, "attribute_citations": {}}],
        "claims": [_claim(entity_id="amd_x", value=2, unit="x",
            comparison={"is_relative": True, "baseline_entity": "nvda_y", "baseline_stated": True},
            conditions={"sparsity": True, "stated_caveats": []},
            citation={"quote_span": "Ours is 2x versus NVDA with sparsity on.", "location_type": "body"})]}
    result, _ = validate_proposal(p, src)
    assert result.claims[0].completeness.value == "marketing_only"


def test_sparsity_with_unresolved_baseline_is_not_marketing_only():
    """The cross-vendor marketing_only test needs BOTH vendors known. A same-vendor
    sparsity claim whose baseline isn't declared (None vendor) must NOT be tagged
    marketing_only — that misfire was the bug the analyze gate surfaced."""
    src = "N2 is 2x versus N3E with sparsity on."
    p = {"entities": [_entity("tsmc_n2", "TSMC", "N2")],  # N3E baseline NOT declared here
         "claims": [_claim(entity_id="tsmc_n2", value=2, unit="x",
             comparison={"is_relative": True, "baseline_entity": "tsmc_n3e", "baseline_stated": True},
             conditions={"sparsity": True, "stated_caveats": ["with sparsity on"]},
             completeness="complete",
             citation={"quote_span": "N2 is 2x versus N3E with sparsity on.", "location_type": "body"})]}
    result, _ = validate_proposal(p, src)
    assert result.claims[0].completeness.value != "marketing_only"


def test_shape_invalid_claim_is_dropped_not_fatal():
    """An off-type field (real models emit sparsity='enabled') drops that claim,
    never the whole extraction — the other grounded claims survive."""
    src = "X is 2x versus Y. Z is 9.9x with sparsity."
    p = {"entities": [_entity("e")], "claims": [
        _claim(claim_id="good", value=2, unit="x",
               comparison={"is_relative": True, "baseline_entity": None, "baseline_stated": True},
               citation={"quote_span": "X is 2x versus Y.", "location_type": "body"}),
        _claim(claim_id="bad", value=9.9, unit="x",
               comparison={"is_relative": True, "baseline_entity": None, "baseline_stated": False},
               conditions={"sparsity": "enabled", "stated_caveats": []},  # off-type -> shape invalid
               citation={"quote_span": "Z is 9.9x with sparsity.", "location_type": "body"})]}
    result, rej = validate_proposal(p, src)
    assert [c.claim_id for c in result.claims] == ["good"]
    assert any(r.kind == "claim" and r.target == "bad" and "shape invalid" in r.reason for r in rej)


def test_entity_dedup_merges_by_vendor_and_name():
    src = "N2 stuff."
    p = {"entities": [
        {"entity_id": "tsmc_n2", "entity_type": "process_node", "vendor": "TSMC", "name": "N2",
         "aliases": ["N2"], "node": None, "chip": None, "attribute_citations": {}},
        {"entity_id": "tsmc_n2_dup", "entity_type": "process_node", "vendor": "TSMC", "name": "n2",
         "aliases": ["2nm"], "node": None, "chip": None, "attribute_citations": {}}],
        "claims": []}
    result, rej = validate_proposal(p, src)
    assert len(result.entities) == 1
    assert set(result.entities[0].aliases) == {"N2", "2nm"}
    assert any(r.kind == "entity_merge" for r in rej)


def test_entity_merge_reconciles_attribute_values():
    """Merge must move the grounded VALUE, not just the citation — no orphaned citations."""
    src = "N2 uses GAA nanosheet transistors."
    p = {"entities": [
        {"entity_id": "tsmc_n2", "entity_type": "process_node", "vendor": "TSMC", "name": "N2",
         "aliases": ["N2"], "node": {"transistor_type": None}, "chip": None, "attribute_citations": {}},
        {"entity_id": "tsmc_n2_b", "entity_type": "process_node", "vendor": "TSMC", "name": "N2",
         "aliases": ["2nm"], "node": {"transistor_type": "gaa_nanosheet"}, "chip": None,
         "attribute_citations": {"node.transistor_type": {
             "quote_span": "N2 uses GAA nanosheet transistors.", "location_type": "body"}}}],
        "claims": []}
    result, _ = validate_proposal(p, src)
    assert len(result.entities) == 1
    ent = result.entities[0]
    assert ent.node.transistor_type is not None and ent.node.transistor_type.value == "gaa_nanosheet"
    assert "node.transistor_type" in ent.attribute_citations  # citation matches the value it grounds
    assert set(ent.aliases) == {"N2", "2nm"}


def test_entity_name_is_pinned_into_aliases():
    """Models repeat the canonical name in `aliases` inconsistently (the live-golden
    flake, 2026-08-18) — validate pins it so the output is deterministic."""
    without = _entity()  # aliases: []
    result, _ = validate_proposal({"entities": [without], "claims": []}, "SRC")
    assert result.entities[0].aliases == ["N"]

    with_it = _entity()
    with_it["aliases"] = ["N", "Marketing Name"]
    result, _ = validate_proposal({"entities": [with_it], "claims": []}, "SRC")
    assert result.entities[0].aliases == ["N", "Marketing Name"]  # present once, order kept


def test_merged_dup_name_variant_does_not_pollute_aliases():
    """Pinning applies to SURVIVING entities only: a case-variant dup's `name` is
    not injected into the merged alias set."""
    p = {"entities": [
        {"entity_id": "tsmc_n2", "entity_type": "process_node", "vendor": "TSMC", "name": "N2",
         "aliases": [], "node": None, "chip": None, "attribute_citations": {}},
        {"entity_id": "tsmc_n2_dup", "entity_type": "process_node", "vendor": "TSMC", "name": "n2",
         "aliases": ["2nm"], "node": None, "chip": None, "attribute_citations": {}}],
        "claims": []}
    result, _ = validate_proposal(p, "N2 stuff.")
    assert len(result.entities) == 1
    assert result.entities[0].aliases == ["N2", "2nm"]  # name pinned first; no "n2"


def test_stray_attribute_citation_is_dropped_and_logged():
    """A citation for an exempt/unknown attribute path is dropped WITH a rejection."""
    src = "N2 exists."
    p = {"entities": [{"entity_id": "tsmc_n2", "entity_type": "process_node", "vendor": "TSMC",
        "name": "N2", "aliases": [], "node": None, "chip": None,
        "attribute_citations": {"node.hvm_date_actual": {  # exempt path
            "quote_span": "whatever", "location_type": "body"}}}], "claims": []}
    result, rej = validate_proposal(p, src)
    assert result.entities[0].attribute_citations == {}
    assert any(r.kind == "entity_attribute" and "unknown or exempt" in r.reason for r in rej)
