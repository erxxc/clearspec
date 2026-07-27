"""store — the sole owner of SQLite persistence.

Public surface: pydantic models (`models`) and the db functions re-exported here.
No other package should import `sqlite3` or write SQL.
"""

from . import models
from .db import (
    ClaimView,
    connect,
    get_claims_for_analysis,
    get_entities_index,
    init_db,
    insert_claim,
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
    "ClaimView",
    "connect",
    "get_claims_for_analysis",
    "get_entities_index",
    "init_db",
    "insert_claim",
    "insert_document",
    "insert_entity",
    "reconcile_entity",
    "persist_extraction",
    "report_counts",
    "stored_doc_shas",
    "table_counts",
]
