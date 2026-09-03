"""analyze — cross-source corroboration and divergence (v1 + WS-2a + GEI-9).

Foundry claims keep the ±10% numeric ruler (metric/unit/publisher grouping).
Advisory claims group by (cve_id, package_or_product, claim_class) and use:
  * affected_range / patched_in — structured set comparison (never ±10%)
  * cvss — reuse numeric ruler
  * exploit_status — enum agreement
  * workaround — exact workaround_text agreement

Never auto-resolve: no path picks a winning source_record_kind or range.
favored_tier is display-only on contradicted groups. Suspect exclusion still
applies (marketing_only / sparsity cannot corroborate a clean catalog row).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..config import Config, load_config
from ..textnorm import fold
from ..store import (
    ClaimView,
    conflict_counts_by_entity,
    connect,
    get_claims_for_analysis,
    get_conflicts,
    get_entities_for_analysis,
    get_entities_index,
    models,
)
from .version_sets import compare_version_ranges, version_range_as_dict

TOLERANCE_PCT = 10.0
_SPLIT_METRIC_RATIO = 0.85

_CONFIDENCE = {
    "corroborated": "high",
    "weakly_corroborated": "medium",
    "contradicted": "low",
    "uncorroborated": "none",
}

_ADVISORY_CLASSES = {
    "affected_range", "patched_in", "cvss", "exploit_status", "workaround",
}
_RANGE_CLASSES = {"affected_range", "patched_in"}

_norm_key = fold


@dataclass
class Assessment:
    entity_id: str
    metric: str
    baseline_entity: str | None
    status: str
    members: list[str]
    value_range: list[float]
    spread_pct: float
    tiers: list[int]
    confidence: str
    flags: list[str]
    favored_tier: int | None = None
    # GEI-9 advisory display fields (optional; foundry assessments omit them)
    claim_class: str | None = None
    cve_id: str | None = None
    set_relation: str | None = None

    def to_dict(self) -> dict:
        d = {
            "entity_id": self.entity_id, "metric": self.metric,
            "baseline_entity": self.baseline_entity, "status": self.status,
            "members": self.members, "value_range": self.value_range,
            "spread_pct": self.spread_pct, "tiers": self.tiers,
            "confidence": self.confidence, "flags": self.flags,
        }
        if self.favored_tier is not None:
            d["favored_tier"] = self.favored_tier
        if self.claim_class is not None:
            d["claim_class"] = self.claim_class
        if self.cve_id is not None:
            d["cve_id"] = self.cve_id
        if self.set_relation is not None:
            d["set_relation"] = self.set_relation
        return d


@dataclass
class AnalysisReport:
    entities_reconciled: dict[str, dict]
    assessments: list[Assessment]
    conflicts: list[models.Conflict] = field(default_factory=list)
    conflict_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "entities_reconciled": self.entities_reconciled,
            "assessments": [a.to_dict() for a in self.assessments],
        }
        if self.conflicts:
            d["conflicts"] = [c.model_dump(mode="json") for c in self.conflicts]
            d["conflict_counts"] = dict(self.conflict_counts)
        return d


def _suspect(claim: ClaimView) -> bool:
    return claim.sparsity is True or claim.completeness == "marketing_only"


def _publisher_floor_status(
    members: list[ClaimView], flags: list[str],
) -> str:
    """Shared corroboration floor: ≥2 non-suspect distinct publishers.

    marketing_only / sparsity cannot corroborate a clean row (suspect
    exclusion). Single publisher → weakly_corroborated.
    """
    non_suspect = [c for c in members if not _suspect(c)]
    if len(non_suspect) >= 2:
        if len({_norm_key(c.publisher) for c in non_suspect}) >= 2:
            return "corroborated"
        flags.append("single_publisher")
        return "weakly_corroborated"
    return "weakly_corroborated"


def _assess(group: list[ClaimView], entity_ids: set[str]) -> Assessment:
    """Foundry numeric ±10% ruler (unchanged)."""
    members = sorted(group, key=lambda c: c.claim_id)
    values = [c.value for c in members if c.value is not None]
    if not values:
        lo, hi, spread = 0.0, 0.0, 0.0
    else:
        lo, hi = min(values), max(values)
        denom = max(abs(lo), abs(hi))
        spread = 0.0 if denom == 0 else round((hi - lo) / denom * 100, 1)
    tiers = sorted({c.source_tier for c in members})
    baseline = members[0].baseline_entity

    flags: list[str] = []
    if any(c.sparsity is True for c in members):
        flags.append("sparsity")
    if any(c.completeness == "marketing_only" for c in members):
        flags.append("marketing_only")
    if baseline is not None and baseline not in entity_ids:
        flags.append("unresolved_baseline")
    if len(members) == 1:
        flags.append("single_source")

    if len(members) == 1:
        status = "uncorroborated"
    elif spread > TOLERANCE_PCT:
        status = "contradicted"
    else:
        status = _publisher_floor_status(members, flags)

    favored_tier = None
    if status == "contradicted":
        favored_tier = min(c.source_tier for c in members)

    return Assessment(
        entity_id=members[0].entity_id, metric=members[0].metric,
        baseline_entity=baseline, status=status,
        members=[c.claim_id for c in members],
        value_range=[lo, hi] if values else [0.0, 0.0], spread_pct=spread,
        tiers=tiers, confidence=_CONFIDENCE[status], flags=sorted(set(flags)),
        favored_tier=favored_tier,
    )


def _pairwise_set_relation(group: list[ClaimView]) -> str | None:
    """Aggregate set relation across all range pairs in the group.

    equal if every pair is equal; otherwise the strongest disagreement
    among {disjoint, overlap, subset} (disjoint > overlap > subset).
    """
    ranked = {"equal": 0, "subset": 1, "overlap": 2, "disjoint": 3}
    worst = "equal"
    ranged = [c for c in group if c.version_range is not None]
    if len(ranged) < 2:
        return None
    for i in range(len(ranged)):
        for j in range(i + 1, len(ranged)):
            rel = compare_version_ranges(
                version_range_as_dict(ranged[i].version_range),
                version_range_as_dict(ranged[j].version_range),
            )
            if ranked[rel] > ranked[worst]:
                worst = rel
    return worst


def _values_agree_numeric(group: list[ClaimView]) -> tuple[bool, float, list[float]]:
    values = [c.value for c in group if c.value is not None]
    if not values:
        return True, 0.0, [0.0, 0.0]
    lo, hi = min(values), max(values)
    denom = max(abs(lo), abs(hi))
    spread = 0.0 if denom == 0 else round((hi - lo) / denom * 100, 1)
    return spread <= TOLERANCE_PCT, spread, [lo, hi]


def _enums_agree(group: list[ClaimView]) -> bool:
    statuses = {c.exploit_status for c in group if c.exploit_status is not None}
    return len(statuses) <= 1


def _workarounds_agree(group: list[ClaimView]) -> bool:
    texts = {c.workaround_text for c in group if c.workaround_text is not None}
    return len(texts) <= 1


def _assess_advisory(group: list[ClaimView], entity_ids: set[str]) -> Assessment:
    """Advisory grouping assessment. Never picks a winning kind/range."""
    members = sorted(group, key=lambda c: c.claim_id)
    claim_class = members[0].claim_class
    cve_id = members[0].cve_id
    tiers = sorted({c.source_tier for c in members})
    baseline = members[0].baseline_entity

    flags: list[str] = []
    if any(c.sparsity is True for c in members):
        flags.append("sparsity")
    if any(c.completeness == "marketing_only" for c in members):
        flags.append("marketing_only")
    if baseline is not None and baseline not in entity_ids:
        flags.append("unresolved_baseline")
    if len(members) == 1:
        flags.append("single_source")

    set_relation: str | None = None
    value_range = [0.0, 0.0]
    spread = 0.0
    agree = True

    if claim_class in _RANGE_CLASSES:
        set_relation = _pairwise_set_relation(members)
        if set_relation is None:
            agree = True  # single ranged claim or no ranges
        else:
            agree = set_relation == "equal"
            if set_relation != "equal":
                flags.append(f"set_relation:{set_relation}")
    elif claim_class == "cvss":
        agree, spread, value_range = _values_agree_numeric(members)
    elif claim_class == "exploit_status":
        agree = _enums_agree(members)
        if not agree:
            flags.append("enum_disagree")
    elif claim_class == "workaround":
        agree = _workarounds_agree(members)
        if not agree:
            flags.append("workaround_disagree")

    if len(members) == 1:
        status = "uncorroborated"
    elif not agree:
        status = "contradicted"
    else:
        status = _publisher_floor_status(members, flags)

    favored_tier = None
    if status == "contradicted":
        # Display order only — both claims remain in members / the store.
        favored_tier = min(c.source_tier for c in members)

    # metric for advisory: claim_class (human-facing); foundry keeps metric text
    return Assessment(
        entity_id=members[0].entity_id,
        metric=claim_class or members[0].metric,
        baseline_entity=baseline,
        status=status,
        members=[c.claim_id for c in members],
        value_range=value_range,
        spread_pct=spread,
        tiers=tiers,
        confidence=_CONFIDENCE[status],
        flags=sorted(set(flags)),
        favored_tier=favored_tier,
        claim_class=claim_class or None,
        cve_id=cve_id,
        set_relation=set_relation,
    )


def _add_flag(a: Assessment, flag: str) -> None:
    if flag not in a.flags:
        a.flags = sorted([*a.flags, flag])


def _slug_collisions(entities: list[dict]) -> set[str]:
    colliding: set[str] = set()
    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            a, b = entities[i], entities[j]
            if a["entity_type"] != b["entity_type"]:
                continue
            if _norm_key(a["vendor"]) != _norm_key(b["vendor"]):
                continue
            forms_a = {_norm_key(a["name"]), *(_norm_key(x) for x in a["aliases"])}
            forms_b = {_norm_key(b["name"]), *(_norm_key(x) for x in b["aliases"])}
            if forms_a & forms_b:
                colliding.add(a["entity_id"])
                colliding.add(b["entity_id"])
    return colliding


def analyze_claims(
    claims: list[ClaimView],
    entities_index: dict[str, list[str]],
    *,
    entities_detail: list[dict] | None = None,
    conflicts: list[models.Conflict] | None = None,
    conflict_counts: dict[str, int] | None = None,
) -> AnalysisReport:
    entity_ids = set(entities_index)
    foundry_groups: dict[tuple, list[ClaimView]] = defaultdict(list)
    advisory_groups: dict[tuple, list[ClaimView]] = defaultdict(list)

    for claim in claims:
        if claim.claim_class in _ADVISORY_CLASSES:
            # (cve_id, package_or_product, claim_class) — entity_id is the package/product
            key = claim.advisory_group_key()
            advisory_groups[key].append(claim)
        else:
            foundry_groups[(
                claim.entity_id, _norm_key(claim.metric), claim.is_relative,
                claim.baseline_entity, _norm_key(claim.unit),
            )].append(claim)

    keyed: list[tuple[tuple, Assessment]] = []
    for key, g in foundry_groups.items():
        keyed.append((key, _assess(g, entity_ids)))
    for key, g in advisory_groups.items():
        keyed.append((("advisory",) + key, _assess_advisory(g, entity_ids)))

    # Foundry-only: possible_split_metric advisory across near-identical metrics
    by_rest: dict[tuple, list[tuple[str, Assessment]]] = defaultdict(list)
    for key, a in keyed:
        if key and key[0] == "advisory":
            continue
        eid, met, rel, base, unit = key  # type: ignore[misc]
        by_rest[(eid, rel, base, unit)].append((met, a))
    for pairs in by_rest.values():
        for i in range(len(pairs)):
            for j in range(i + 1, len(pairs)):
                m1, a1 = pairs[i]
                m2, a2 = pairs[j]
                if m1 != m2 and SequenceMatcher(None, m1, m2).ratio() >= _SPLIT_METRIC_RATIO:
                    _add_flag(a1, "possible_split_metric")
                    _add_flag(a2, "possible_split_metric")

    if entities_detail:
        colliding = _slug_collisions(entities_detail)
        for _, a in keyed:
            if a.entity_id in colliding:
                _add_flag(a, "possible_slug_collision")

    conflict_counts = conflict_counts or {}
    for _, a in keyed:
        if conflict_counts.get(a.entity_id):
            _add_flag(a, "identity_conflict")

    assessments = [a for _, a in keyed]
    assessments.sort(key=lambda a: (
        a.cve_id or "", a.entity_id, a.claim_class or a.metric, a.baseline_entity or "",
    ))
    reconciled = {eid: {"aliases": sorted(aliases)} for eid, aliases in entities_index.items()}
    return AnalysisReport(
        entities_reconciled=reconciled, assessments=assessments,
        conflicts=conflicts or [], conflict_counts=conflict_counts,
    )


def run_analysis(config: Config | None = None) -> AnalysisReport:
    config = config or load_config()
    conn = connect(config.paths.db_path)
    try:
        return analyze_claims(
            get_claims_for_analysis(conn),
            get_entities_index(conn),
            entities_detail=get_entities_for_analysis(conn),
            conflicts=get_conflicts(conn),
            conflict_counts=conflict_counts_by_entity(conn),
        )
    finally:
        conn.close()
