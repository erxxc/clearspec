"""store — the sole owner of SQLite persistence.

Public surface: pydantic models (`models`) and the db functions re-exported here.
No other package should import `sqlite3` or write SQL.
"""

from . import models
from .db import (
    connect,
    init_db,
    insert_claim,
    insert_document,
    insert_entity,
    report_counts,
    table_counts,
)

__all__ = [
    "models",
    "connect",
    "init_db",
    "insert_claim",
    "insert_document",
    "insert_entity",
    "report_counts",
    "table_counts",
]
