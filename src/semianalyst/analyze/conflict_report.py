"""GEI-13 — per-CVE conflict report (the ship artifact).

Conflict is the product: group advisory assessments by CVE and surface
contradicted (and related weakly_corroborated) groups for affected_range /
patched_in / exploit_status, with each side's bounded quote_span and
source_record_kind/doc. Never picks a winning range or kind. Never
auto-resolves. Does not interpolate workaround_text.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..config import Config, load_config
from ..store import ClaimView, connect, get_claims_for_analysis
from .corroborate import AnalysisReport, Assessment, run_analysis

# Schema bounds.cite_quote_span.max / Span2000 — flood guard for display.
QUOTE_SPAN_MAX = 2000

_FOCUS_CLASSES = frozenset({"affected_range", "patched_in", "exploit_status"})
# Conflict is the product; related context (weakly_corroborated) rides along.
_REPORT_STATUSES = frozenset({"contradicted", "weakly_corroborated"})


def bound_quote_span(text: str | None, *, max_len: int = QUOTE_SPAN_MAX) -> str:
    """Truncate to schema cite_quote_span max. Empty/None → \"\"."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len]


@dataclass
class ClaimSide:
    """One persisting side of a conflict — never dropped for a 'winner'."""

    claim_id: str
    doc_id: str
    source_record_kind: str | None
    source_tier: int
    publisher: str
    quote_span: str  # bounded; CLI display-sanitizes via _ansi_safe
    version_range: dict | None = None
    exploit_status: str | None = None
    value: float | None = None
    unit: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "claim_id": self.claim_id,
            "doc_id": self.doc_id,
            "source_record_kind": self.source_record_kind,
            "source_tier": self.source_tier,
            "publisher": self.publisher,
            "quote_span": self.quote_span,
        }
        if self.version_range is not None:
            d["version_range"] = self.version_range
        if self.exploit_status is not None:
            d["exploit_status"] = self.exploit_status
        if self.value is not None:
            d["value"] = self.value
            d["unit"] = self.unit
        # workaround_text intentionally omitted — injection surface.
        return d


@dataclass
class ConflictGroup:
    claim_class: str
    package_or_product: str
    status: str
    set_relation: str | None
    confidence: str
    flags: list[str]
    favored_tier: int | None  # display-only ordering hint; not a resolver
    sides: list[ClaimSide]

    def to_dict(self) -> dict:
        d = {
            "claim_class": self.claim_class,
            "package_or_product": self.package_or_product,
            "status": self.status,
            "confidence": self.confidence,
            "flags": list(self.flags),
            "sides": [s.to_dict() for s in self.sides],
        }
        if self.set_relation is not None:
            d["set_relation"] = self.set_relation
        if self.favored_tier is not None:
            d["favored_tier"] = self.favored_tier
        return d


@dataclass
class CveConflictReport:
    cve_id: str
    groups: list[ConflictGroup] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"cve_id": self.cve_id, "groups": [g.to_dict() for g in self.groups]}


@dataclass
class ConflictReport:
    """Per-CVE conflict ship artifact — not a CVE feed."""

    cves: list[CveConflictReport] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"cves": [c.to_dict() for c in self.cves]}


def _claims_by_id(claims: list[ClaimView]) -> dict[str, ClaimView]:
    return {c.claim_id: c for c in claims}


def _side_from_claim(claim: ClaimView) -> ClaimSide:
    return ClaimSide(
        claim_id=claim.claim_id,
        doc_id=claim.doc_id,
        source_record_kind=claim.source_record_kind,
        source_tier=claim.source_tier,
        publisher=claim.publisher or "",
        quote_span=bound_quote_span(claim.quote_span),
        version_range=claim.version_range,
        exploit_status=claim.exploit_status,
        value=claim.value,
        unit=claim.unit or "",
    )


def _include_assessment(a: Assessment) -> bool:
    if not a.claim_class or a.claim_class not in _FOCUS_CLASSES:
        return False
    if not (a.cve_id or "").strip():
        return False
    return a.status in _REPORT_STATUSES


def build_conflict_report(
    analysis: AnalysisReport,
    claims: list[ClaimView],
    *,
    cve_id: str | None = None,
) -> ConflictReport:
    """Group advisory assessments into a per-CVE conflict report.

    Never auto-resolves: every member claim becomes a ClaimSide. Filter to
    affected_range / patched_in / exploit_status with contradicted or
    weakly_corroborated status. Optional cve_id narrows to one CVE.
    """
    by_id = _claims_by_id(claims)
    wanted = (cve_id or "").strip().upper() or None

    by_cve: dict[str, list[ConflictGroup]] = defaultdict(list)
    for a in analysis.assessments:
        if not _include_assessment(a):
            continue
        cid = (a.cve_id or "").strip()
        if wanted and cid.upper() != wanted:
            continue
        sides: list[ClaimSide] = []
        for mid in a.members:
            claim = by_id.get(mid)
            if claim is None:
                # Member id without a joinable claim — still surface the id.
                sides.append(ClaimSide(
                    claim_id=mid, doc_id="", source_record_kind=None,
                    source_tier=0, publisher="", quote_span="",
                ))
            else:
                sides.append(_side_from_claim(claim))
        sides.sort(key=lambda s: (s.doc_id, s.claim_id))
        by_cve[cid].append(ConflictGroup(
            claim_class=a.claim_class or a.metric,
            package_or_product=a.entity_id,
            status=a.status,
            set_relation=a.set_relation,
            confidence=a.confidence,
            flags=list(a.flags),
            favored_tier=a.favored_tier,
            sides=sides,
        ))

    cves: list[CveConflictReport] = []
    for cid in sorted(by_cve):
        groups = by_cve[cid]
        groups.sort(key=lambda g: (g.package_or_product, g.claim_class, g.status))
        cves.append(CveConflictReport(cve_id=cid, groups=groups))
    return ConflictReport(cves=cves)


def conflict_report(
    config: Config | None = None,
    *,
    cve_id: str | None = None,
) -> ConflictReport:
    """Library entry: run analysis + build the per-CVE conflict ship artifact."""
    config = config or load_config()
    analysis = run_analysis(config)
    conn = connect(config.paths.db_path)
    try:
        claims = get_claims_for_analysis(conn)
    finally:
        conn.close()
    return build_conflict_report(analysis, claims, cve_id=cve_id)
