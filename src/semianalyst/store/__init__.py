"""store — the sole owner of SQLite persistence.

Public surface: pydantic models (`models`) and the db functions re-exported here.
No other package should import `sqlite3` or write SQL.
"""

from . import models
from .attestation import KIND_COMPAT, attested_kind, identity_material, kind_from_operator_sidecar, kind_from_sidecar, stamp_advisory_claims
from .db import (
    ClaimView,
    StoreNotInitialized,
    conflict_counts_by_entity,
    connect,
    get_claims_for_analysis,
    get_conflicts,
    get_entities_for_analysis,
    get_entities_index,
    init_db,
    insert_claim,
    insert_conflict,
    insert_document,
    insert_entity,
    reconcile_entity,
    report_counts,
    stored_doc_shas,
    table_counts,
)
from .persist import persist_extraction

__all__ = [
    "models",
    "KIND_COMPAT",
    "attested_kind",
    "identity_material",
    "kind_from_operator_sidecar",
    "kind_from_sidecar",
    "stamp_advisory_claims",
    "ClaimView",
    "StoreNotInitialized",
    "conflict_counts_by_entity",
    "connect",
    "get_claims_for_analysis",
    "get_conflicts",
    "get_entities_for_analysis",
    "get_entities_index",
    "init_db",
    "insert_claim",
    "insert_conflict",
    "insert_document",
    "insert_entity",
    "reconcile_entity",
    "persist_extraction",
    "report_counts",
    "stored_doc_shas",
    "table_counts",
]
