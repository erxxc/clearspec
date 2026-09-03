"""analyze — cross-source corroboration and divergence (v1 + WS-2a floors).

Advisory claim_class values are excluded from the foundry ±10% ruler (GEI-9
owns version-range grouping). This is a skip, not a resolver — no path picks
a winning source_record_kind.
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


def _assess(group: list[ClaimView], entity_ids: set[str]) -> Assessment:
    members = sorted(group, key=lambda c: c.claim_id)
    values = [c.value for c in members if c.value is not None]
    if not values:
        lo, hi, spread = 0.0, 0.0, 0.0
    else:
        lo, hi = min(values), max(values)
        denom = max(abs(lo), abs(hi))
        spread = 0.0 if denom == 0 else round((hi - lo) / denom * 100, 1)
    tiers = sorted({c.source_tier for c in members})
    non_suspect = [c for c in members if not _suspect(c)]
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
    elif len(non_suspect) >= 2:
        if len({_norm_key(c.publisher) for c in non_suspect}) >= 2:
            status = "corroborated"
        else:
            status = "weakly_corroborated"
            flags.append("single_publisher")
    else:
        status = "weakly_corroborated"

    favored_tier = None
    if status == "contradicted":
        favored_tier = min(c.source_tier for c in members)

    return Assessment(
        entity_id=members[0].entity_id, metric=members[0].metric, baseline_entity=baseline,
        status=status, members=[c.claim_id for c in members],
        value_range=[lo, hi] if values else [0.0, 0.0], spread_pct=spread, tiers=tiers,
        confidence=_CONFIDENCE[status], flags=sorted(flags), favored_tier=favored_tier,
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
    groups: dict[tuple, list[ClaimView]] = defaultdict(list)
    for claim in claims:
        # GEI-9 owns advisory grouping; do not apply the foundry ±10% ruler
        # and do not pick a winning source_record_kind.
        if claim.claim_class in _ADVISORY_CLASSES:
            continue
        groups[(claim.entity_id, _norm_key(claim.metric), claim.is_relative,
                claim.baseline_entity, _norm_key(claim.unit))].append(claim)

    keyed = [(key, _assess(g, entity_ids)) for key, g in groups.items()]

    by_rest: dict[tuple, list[tuple[str, Assessment]]] = defaultdict(list)
    for (eid, met, rel, base, unit), a in keyed:
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
    assessments.sort(key=lambda a: (a.entity_id, a.metric, a.baseline_entity or ""))
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
