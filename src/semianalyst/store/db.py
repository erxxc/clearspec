"""SQLite persistence — the ONLY module in semianalyst permitted to touch the DB.

Everything else calls these functions; no other module imports sqlite3 or writes
SQL. This boundary is architectural (see CLAUDE.md): it keeps the storage
representation swappable and confines the nested<->flat mapping to one place.

All writes use parameterized queries. No value is ever interpolated into SQL text.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from ..config import Config, load_config
from . import models

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


# --------------------------------------------------------------------------
# Connection + migration runner
# --------------------------------------------------------------------------
def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _discover_migrations() -> list[tuple[int, Path]]:
    """Return (version, path) for every NNNN_*.sql, sorted by numeric prefix."""
    found: list[tuple[int, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
        version = int(p.name.split("_", 1)[0])
        found.append((version, p))
    return found


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  filename TEXT NOT NULL,"
        "  applied_at TEXT NOT NULL"
        ")"
    )
    return {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}


def init_db(config: Config | None = None) -> Path:
    """Apply all pending migrations. Idempotent — safe to run repeatedly.

    Returns the path to the initialized database.
    """
    config = config or load_config()
    db_path = config.paths.db_path
    conn = connect(db_path)
    try:
        applied = _applied_versions(conn)
        for version, path in _discover_migrations():
            if version in applied:
                continue
            with conn:  # one transaction per migration
                conn.executescript(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (version, filename, applied_at) "
                    "VALUES (?, ?, ?)",
                    (version, path.name, dt.datetime.now(dt.UTC).isoformat()),
                )
    finally:
        conn.close()
    return db_path


# --------------------------------------------------------------------------
# Serialization helpers (nested pydantic -> flat row)
# --------------------------------------------------------------------------
def _d(value: dt.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _b(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _enum(value: object | None) -> object | None:
    return getattr(value, "value", value)


# --------------------------------------------------------------------------
# Inserts (parameterized; upsert on primary key)
# --------------------------------------------------------------------------
def insert_document(conn: sqlite3.Connection, doc: models.Document) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO document "
        "(doc_id, title, publisher, doc_type, source_tier, publish_date, url, "
        " file_sha256, ingest_date, extraction_model, review_status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            doc.doc_id, doc.title, doc.publisher, _enum(doc.doc_type),
            int(doc.source_tier), _d(doc.publish_date), doc.url,
            doc.file_sha256, _d(doc.ingest_date), doc.extraction_model,
            _enum(doc.review_status),
        ),
    )


def insert_entity(conn: sqlite3.Connection, ent: models.Entity) -> None:
    node = ent.node or models.NodeAttributes()
    chip = ent.chip or models.ChipAttributes()
    conn.execute(
        "INSERT OR REPLACE INTO entity "
        "(entity_id, entity_type, vendor, name, aliases, "
        " node_density_mtx_mm2, node_transistor_type, node_backside_power, "
        " node_hvm_date_claimed, node_hvm_date_actual, "
        " chip_process_node_ref, chip_transistor_count_b, chip_die_size_mm2, "
        " chip_package_type, chip_memory_type, chip_memory_bw_gbps, chip_tdp_w, "
        " chip_launch_date) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ent.entity_id, _enum(ent.entity_type), ent.vendor, ent.name,
            json.dumps(ent.aliases),
            node.density_mtx_mm2, _enum(node.transistor_type),
            _b(node.backside_power), _d(node.hvm_date_claimed),
            _d(node.hvm_date_actual),
            chip.process_node_ref, chip.transistor_count_b, chip.die_size_mm2,
            chip.package_type, chip.memory_type, chip.memory_bw_gbps, chip.tdp_w,
            _d(chip.launch_date),
        ),
    )


def insert_claim(conn: sqlite3.Connection, claim: models.Claim) -> None:
    c = claim
    conn.execute(
        "INSERT OR REPLACE INTO claim "
        "(claim_id, doc_id, entity_id, claim_class, metric, value, unit, "
        " cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated, "
        " cond_workload, cond_precision, cond_sparsity, cond_thermal_config, "
        " cond_stated_caveats, completeness, cite_page, cite_quote_span, "
        " cite_location_type, corr_status, corr_related_claim_ids) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            c.claim_id, c.doc_id, c.entity_id, _enum(c.claim_class), c.metric,
            c.value, c.unit,
            _b(c.comparison.is_relative), c.comparison.baseline_entity,
            _b(c.comparison.baseline_stated),
            c.conditions.workload, c.conditions.precision,
            _b(c.conditions.sparsity), c.conditions.thermal_config,
            json.dumps(c.conditions.stated_caveats), _enum(c.completeness),
            c.citation.page, c.citation.quote_span, _enum(c.citation.location_type),
            _enum(c.corroboration.status),
            json.dumps(c.corroboration.related_claim_ids),
        ),
    )


# --------------------------------------------------------------------------
# Read helpers (used by analyze/ and the `report` command)
# --------------------------------------------------------------------------
def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("document", "entity", "claim", "macro_snapshot")
    return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}


def report_counts(config: Config | None = None) -> dict[str, int]:
    """Row counts per table. The library entry point behind `semianalyst report`
    (and a future web UI) — callers never open a connection themselves."""
    config = config or load_config()
    conn = connect(config.paths.db_path)
    try:
        return table_counts(conn)
    finally:
        conn.close()
