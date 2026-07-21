"""analyze v1 — cross-source corroboration and divergence.

Reads claims (joined to their document's source_tier) from the store, groups them
by (entity, metric, is_relative, baseline, unit), and assigns each group a
corroboration verdict. Read-only over the store; derives on read (does not mutate
`claim.corroboration` this iteration).

Verdict rules (honest-data domain):
  - Compare only within a shared (metric, is_relative, baseline, unit) — a relative
    claim never compares against an absolute one, nor across baselines.
  - A SUSPECT member (sparsity=true or completeness=marketing_only) may ride along
    but does NOT count toward the >=2 needed for `corroborated`.
  - status: singleton -> uncorroborated; spread beyond tolerance -> contradicted;
    >=2 non-suspect within tolerance -> corroborated; else (>=2 members agree but
    <2 non-suspect) -> weakly_corroborated.
  - flags surface sparsity / marketing_only / unresolved_baseline / single_source.

Hostile-input guards (tier-precedence, tier-diversity status floor, resolved-entity
baseline poisoning, alias gating) are Class-A decisions deferred to the live-ingest
workstream — no hostile document can reach this MVP's curated inputs. See CLAUDE.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..config import Config, load_config
from ..store import ClaimView, connect, get_claims_for_analysis, get_entities_index

TOLERANCE_PCT = 10.0

_CONFIDENCE = {
    "corroborated": "high",
    "weakly_corroborated": "medium",
    "contradicted": "low",
    "uncorroborated": "none",
}


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

    def to_dict(self) -> dict:
        return {
            "entities_reconciled": self.entities_reconciled,
            "assessments": [a.to_dict() for a in self.assessments],
        }


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
        status = "corroborated"
    else:
        status = "weakly_corroborated"

    favored_tier = None
    if status == "contradicted":
        # Report the highest-trust (lowest) tier present in the divergence. This
        # is advisory surfacing, NOT enforcement: a suspect member is deliberately
        # NOT excluded here. The excluding variant (`non_suspect or members`) let a
        # sparsity flag override the tier ordering — a live tier-precedence decision
        # (deferred question K, see CLAUDE.md), unexercised because on honest data
        # the suspect member is always the higher tier. Tier-blind min matches the
        # deliberately tier-blind reconciler next to it.
        favored_tier = min(c.source_tier for c in members)

    return Assessment(
        entity_id=members[0].entity_id, metric=members[0].metric, baseline_entity=baseline,
        status=status, members=[c.claim_id for c in members],
        value_range=[lo, hi], spread_pct=spread, tiers=tiers,
        confidence=_CONFIDENCE[status], flags=sorted(flags), favored_tier=favored_tier,
    )


def analyze_claims(claims: list[ClaimView], entities_index: dict[str, list[str]]) -> AnalysisReport:
    entity_ids = set(entities_index)
    groups: dict[tuple, list[ClaimView]] = defaultdict(list)
    for claim in claims:
        groups[(claim.entity_id, claim.metric, claim.is_relative,
                claim.baseline_entity, claim.unit)].append(claim)

    assessments = [_assess(g, entity_ids) for g in groups.values()]
    assessments.sort(key=lambda a: (a.entity_id, a.metric, a.baseline_entity or ""))
    reconciled = {eid: {"aliases": sorted(aliases)} for eid, aliases in entities_index.items()}
    return AnalysisReport(entities_reconciled=reconciled, assessments=assessments)


def run_analysis(config: Config | None = None) -> AnalysisReport:
    """Library entry point behind `semianalyst report`. Read-only over the store."""
    config = config or load_config()
    conn = connect(config.paths.db_path)
    try:
        return analyze_claims(get_claims_for_analysis(conn), get_entities_index(conn))
    finally:
        conn.close()
