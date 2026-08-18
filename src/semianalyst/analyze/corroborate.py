"""analyze — cross-source corroboration and divergence (v1 + WS-2a floors).

Reads claims (joined to their document's source_tier and publisher) from the
store, groups them by (entity, normalized metric, is_relative, baseline,
normalized unit), and assigns each group a corroboration verdict. Read-only over
the store; derives on read (does not mutate `claim.corroboration`).

Verdict rules:
  - Compare only within a shared (metric, is_relative, baseline, unit) group.
    `metric` and `unit` are normalized (casefold + whitespace collapse) for the
    group KEY — they are attacker-influenceable free text, and a one-character
    variant must not opt a hostile claim out of divergence detection
    (2026-08-18 gate, Challenge 3). Display keeps the stored string.
  - A SUSPECT member (sparsity=true or completeness=marketing_only) may ride
    along but does NOT count toward the >=2 needed for `corroborated`.
  - H1 (publisher-diversity floor, 2026-08-18 gate): `corroborated` additionally
    requires the agreeing non-suspect members to span >=2 distinct NORMALIZED
    publishers; a single-publisher agreement demotes to `weakly_corroborated`
    + `single_publisher`. This is honestly a publisher/OPERATOR-diversity floor
    (publishers come from the operator's watchlist in WS-2b's direct-URL scope),
    not a hostile-input defense. H2 (all-tier-3 confidence cap) is DEFERRED —
    trigger: the watchlist carries >=2 distinct tier-3 publishers for one metric
    (docs/ROADMAP.md).
  - status: singleton -> uncorroborated; spread beyond tolerance -> contradicted;
    >=2 non-suspect within tolerance across >=2 publishers -> corroborated;
    else -> weakly_corroborated.
  - Advisory flags (never change a verdict): `possible_split_metric` — two
    groups differing only by a near-identical metric string (the evasion
    residue normalization can't close); `possible_slug_collision` (J) — two
    stored entities sharing (entity_type, vendor) with overlapping surface
    forms; `identity_conflict` — the entity has persisted reconciliation
    conflicts (see store.get_conflicts; values surface via `report` through the
    hardened sanitizer only).

Remaining hostile-input guards (tier-precedence K3 stays deliberately tier-blind
— see _assess; controlled metric vocabulary; identity citation slots) are
resolved or deferred per docs/reviews/2026-08-18-live-ingest-plan/resolution.md.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..config import Config, load_config
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
_SPLIT_METRIC_RATIO = 0.85   # SequenceMatcher ratio at/above which two distinct
                             # metric strings are flagged as a possible split group

_CONFIDENCE = {
    "corroborated": "high",
    "weakly_corroborated": "medium",
    "contradicted": "low",
    "uncorroborated": "none",
}

_WS = re.compile(r"\s+")


def _norm_key(s: str) -> str:
    """Normalize an attacker-influenceable free-text key component for grouping
    and publisher comparison: whitespace collapse + strip + casefold. The same
    folding G3 mandates for aliases — a casing/spacing variant is one value."""
    return _WS.sub(" ", s).strip().casefold()


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
        # Serialized only when present: a conflict-free store keeps the v3 dict
        # shape byte-for-byte, so the honest-corpus fixtures stay stable
        # (2026-08-18 gate, Challenge 4 — the flag budget's serialization twin).
        if self.conflicts:
            d["conflicts"] = [c.model_dump(mode="json") for c in self.conflicts]
            d["conflict_counts"] = dict(self.conflict_counts)
        return d


def _suspect(claim: ClaimView) -> bool:
    return claim.sparsity is True or claim.completeness == "marketing_only"


def _assess(group: list[ClaimView], entity_ids: set[str]) -> Assessment:
    members = sorted(group, key=lambda c: c.claim_id)
    values = [c.value for c in members]
    lo, hi = min(values), max(values)
    # Spread as a % of the larger-magnitude endpoint, NOT of `lo`. Dividing by
    # `lo` detonates when lo == 0 (a legal "0 defects"/"0%" claim): the old
    # `if lo else 0.0` guard reported spread 0.0 for a group like [0.0, 40.0],
    # i.e. a FALSE "corroborated/high" on two numbers that agree on nothing. The
    # max-magnitude denominator is finite for any non-[0,0] group and preserves
    # every status the golden asserts. (Whether an *absolute* claim deserves an
    # *absolute* tolerance rather than this relative %, is an open decision — see
    # CLAUDE.md; today the only absolute claim is a singleton, so it's moot.)
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
        # H1: agreement is only corroboration when it crosses a publisher
        # boundary — one publisher agreeing with itself is one voice, however
        # many PDFs it prints (2026-08-18 gate, Conflict 3 / §2.3).
        if len({_norm_key(c.publisher) for c in non_suspect}) >= 2:
            status = "corroborated"
        else:
            status = "weakly_corroborated"
            flags.append("single_publisher")
    else:
        status = "weakly_corroborated"

    favored_tier = None
    if status == "contradicted":
        # Report the highest-trust (lowest) tier present in the divergence. This
        # is advisory surfacing, NOT enforcement: a suspect member is deliberately
        # NOT excluded here (K3, ratified at the 2026-08-18 gate): suspect-ness is
        # self-declared by the claim's own document, so excluding suspects would
        # punish the honest discloser and reward the concealer. Tier-blind min
        # preserves the honest discloser's tier authority.
        favored_tier = min(c.source_tier for c in members)

    return Assessment(
        entity_id=members[0].entity_id, metric=members[0].metric, baseline_entity=baseline,
        status=status, members=[c.claim_id for c in members],
        value_range=[lo, hi], spread_pct=spread, tiers=tiers,
        confidence=_CONFIDENCE[status], flags=sorted(flags), favored_tier=favored_tier,
    )


def _add_flag(a: Assessment, flag: str) -> None:
    if flag not in a.flags:
        a.flags = sorted([*a.flags, flag])


def _slug_collisions(entities: list[dict]) -> set[str]:
    """J (advisory): entity_ids whose (entity_type, vendor) twin shares a surface
    form (name or alias, normalized). Advisory, never fail-loud — a fail-loud
    check would let a hostile alias DoS honest ingestion (G3 blocks the graft at
    reconcile; this surfaces the residue)."""
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
        groups[(claim.entity_id, _norm_key(claim.metric), claim.is_relative,
                claim.baseline_entity, _norm_key(claim.unit))].append(claim)

    keyed = [(key, _assess(g, entity_ids)) for key, g in groups.items()]

    # possible_split_metric: two groups identical but for a near-identical metric
    # string — the evasion residue key normalization can't close (a controlled
    # metric vocabulary is deferred; trigger in docs/ROADMAP.md).
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
    """Library entry point behind `semianalyst report`. Read-only over the store."""
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
