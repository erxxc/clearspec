"""analyze — cross-source corroboration and divergence detection (FUTURE WORK).

This module is intentionally empty this phase. It will read claims from the store
(never touching SQLite directly — it goes through store.db) and answer the
questions that make this an analyst tool rather than a scraper:

  Corroboration
    Do independent sources agree on the same metric for the same entity? Group
    claims by (entity, normalized metric), compare values within tolerance, and
    weight agreement by source_tier (conference > foundry > vendor). Populate
    claim.corroboration.status and related_claim_ids.

  Divergence
    Where do sources contradict each other, and does the disagreement track with
    tier or with disclosed conditions? A vendor's "2.5x" that only holds under
    sparsity, against a foundry's iso-condition number, is a divergence the tool
    must surface rather than average away. Relative claims are compared as
    ratios against their stated baselines — never as reconstructed absolutes.

Design constraint: analysis is read-only over the store and must preserve the
schema's normalization rules (no relative->absolute conversion).
"""

from .corroborate import (
    Assessment,
    AnalysisReport,
    analyze_claims,
    run_analysis,
)

__all__ = ["Assessment", "AnalysisReport", "analyze_claims", "run_analysis"]
