"""SQLite persistence — the ONLY module in semianalyst permitted to touch the DB."""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from ..config import Config, load_config
from ..textnorm import CTRL_CLASS, fold
from . import models

MAX_ALIASES_PER_ENTITY = 16

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _discover_migrations() -> list[tuple[int, Path]]:
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


def init_db(config: Config | None = None, *, db_path: Path | None = None) -> Path:
    if db_path is None:
        config = config or load_config()
        db_path = config.paths.db_path
    conn = connect(db_path)
    try:
        applied = _applied_versions(conn)
        for version, path in _discover_migrations():
            if version in applied:
                continue
            with conn:
                conn.executescript(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (version, filename, applied_at) "
                    "VALUES (?, ?, ?)",
                    (version, path.name, dt.datetime.now(dt.UTC).isoformat()),
                )
    finally:
        conn.close()
    return db_path


def _d(value: dt.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _b(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _enum(value: object | None) -> object | None:
    return getattr(value, "value", value)


def insert_document(conn: sqlite3.Connection, doc: models.Document) -> None:
    conn.execute(
        "INSERT INTO document"
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
    pkg = ent.package
    product = ent.product
    cve = ent.cve
    attr_cites = {
        path: cite.model_dump(mode="json") for path, cite in ent.attribute_citations.items()
    }
    conn.execute(
        "INSERT INTO entity"
        "(entity_id, entity_type, vendor, name, aliases, "
        " node_density_mtx_mm2, node_transistor_type, node_backside_power, "
        " node_hvm_date_claimed, node_hvm_date_actual, "
        " chip_process_node_ref, chip_transistor_count_b, chip_die_size_mm2, "
        " chip_package_type, chip_memory_type, chip_memory_bw_gbps, chip_tdp_w, "
        " chip_launch_date, attribute_citations, "
        " pkg_ecosystem, pkg_name, pkg_purl, pkg_cpe, "
        " product_ecosystem, product_name, product_purl, product_cpe, "
        " cve_id, cve_cwe) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ent.entity_id, _enum(ent.entity_type), ent.vendor, ent.name,
            json.dumps(ent.aliases),
            node.density_mtx_mm2, _enum(node.transistor_type),
            _b(node.backside_power), _d(node.hvm_date_claimed),
            _d(node.hvm_date_actual),
            chip.process_node_ref, chip.transistor_count_b, chip.die_size_mm2,
            chip.package_type, chip.memory_type, chip.memory_bw_gbps, chip.tdp_w,
            _d(chip.launch_date), json.dumps(attr_cites),
            None if pkg is None else pkg.ecosystem,
            None if pkg is None else pkg.name,
            None if pkg is None else pkg.purl,
            None if pkg is None else pkg.cpe,
            None if product is None else product.ecosystem,
            None if product is None else product.name,
            None if product is None else product.purl,
            None if product is None else product.cpe,
            None if cve is None else cve.cve_id,
            None if cve is None else cve.cwe,
        ),
    )


def insert_claim(conn: sqlite3.Connection, claim: models.Claim) -> None:
    c = claim
    version_range_json = None
    if c.version_range is not None:
        version_range_json = json.dumps(c.version_range.model_dump(mode="json"))
    conn.execute(
        "INSERT INTO claim"
        "(claim_id, doc_id, entity_id, claim_class, metric, value, unit, "
        " cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated, "
        " cond_workload, cond_precision, cond_sparsity, cond_thermal_config, "
        " cond_stated_caveats, completeness, cite_page, cite_quote_span, "
        " cite_location_type, cve_id, source_record_kind, version_range, "
        " exploit_status, workaround_text) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            c.claim_id, c.doc_id, c.entity_id, _enum(c.claim_class), c.metric,
            c.value, c.unit,
            _b(c.comparison.is_relative), c.comparison.baseline_entity,
            _b(c.comparison.baseline_stated),
            c.conditions.workload, c.conditions.precision,
            _b(c.conditions.sparsity), c.conditions.thermal_config,
            json.dumps(c.conditions.stated_caveats), _enum(c.completeness),
            c.citation.page, c.citation.quote_span, _enum(c.citation.location_type),
            c.cve_id, _enum(c.source_record_kind), version_range_json,
            _enum(c.exploit_status), c.workaround_text,
        ),
    )


def insert_conflict(conn: sqlite3.Connection, conflict: models.Conflict) -> None:
    conn.execute(
        "INSERT INTO entity_conflict"
        "(kind, entity_id, doc_id, field, stored_value, offered_value, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            _enum(conflict.kind), conflict.entity_id, conflict.doc_id,
            conflict.field, conflict.stored_value, conflict.offered_value,
            dt.datetime.now(dt.UTC).isoformat(),
        ),
    )


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("document", "entity", "claim", "entity_conflict", "macro_snapshot")
    try:
        return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}
    except sqlite3.OperationalError as exc:
        raise _translate_missing_schema(exc) from exc


def stored_doc_shas(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT doc_id, file_sha256 FROM document").fetchall()
    except sqlite3.OperationalError as exc:
        raise _translate_missing_schema(exc) from exc
    return {row["doc_id"]: row["file_sha256"] for row in rows}


def get_conflicts(conn: sqlite3.Connection) -> list[models.Conflict]:
    rows = conn.execute(
        "SELECT conflict_id, kind, entity_id, doc_id, field, stored_value, "
        "       offered_value, created_at "
        "FROM entity_conflict ORDER BY conflict_id"
    ).fetchall()
    return [
        models.Conflict(
            conflict_id=r["conflict_id"], kind=r["kind"], entity_id=r["entity_id"],
            doc_id=r["doc_id"], field=r["field"], stored_value=r["stored_value"],
            offered_value=r["offered_value"], created_at=r["created_at"],
        )
        for r in rows
    ]


def conflict_counts_by_entity(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        row["entity_id"]: row["n"]
        for row in conn.execute(
            "SELECT entity_id, COUNT(*) AS n FROM entity_conflict "
            "GROUP BY entity_id ORDER BY entity_id"
        )
    }


from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimView:
    claim_id: str
    doc_id: str
    entity_id: str
    metric: str
    value: float | None
    unit: str
    is_relative: bool
    baseline_entity: str | None
    sparsity: bool | None
    completeness: str
    source_tier: int
    publisher: str = ""
    claim_class: str = ""
    source_record_kind: str | None = None
    cve_id: str | None = None
    version_range: dict | None = None
    exploit_status: str | None = None
    workaround_text: str | None = None

    def advisory_group_key(self) -> tuple[str, str, str]:
        """GEI-9 grouping key (cve_id, package_or_product, claim_class).

        Representation only — never a resolver; never picks a winning kind.
        """
        return (self.cve_id or "", self.entity_id, self.claim_class)
