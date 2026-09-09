"""analyze — cross-source corroboration and the per-CVE conflict ship artifact.

Library entry points (CLI is a thin wrapper):
  run_analysis / analyze_claims — derive-on-read corroboration over the store
  conflict_report / build_conflict_report — GEI-13 per-CVE conflict report
"""

from .conflict_report import (
    QUOTE_SPAN_MAX,
    ClaimSide,
    ConflictGroup,
    ConflictReport,
    CveConflictReport,
    bound_quote_span,
    build_conflict_report,
    conflict_report,
)
from .corroborate import (
    Assessment,
    AnalysisReport,
    analyze_claims,
    run_analysis,
)

__all__ = [
    "Assessment",
    "AnalysisReport",
    "analyze_claims",
    "run_analysis",
    "QUOTE_SPAN_MAX",
    "ClaimSide",
    "ConflictGroup",
    "ConflictReport",
    "CveConflictReport",
    "bound_quote_span",
    "build_conflict_report",
    "conflict_report",
]
