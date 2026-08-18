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


def init_db(config: Config | None = None, *, db_path: Path | None = None) -> Path:
    """Apply all pending migrations. Idempotent — safe to run repeatedly.

    `db_path` overrides config.paths.db_path: the rebuild fold (extract.run_rebuild)
    initializes a temp file it later atomically swaps over the configured path;
    everything else uses the config. Returns the path to the initialized database.
    """
    if db_path is None:
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
# Inserts (parameterized). Plain INSERT — a duplicate primary key RAISES rather
# than silently overwriting. Cross-document reconciliation (a later doc naming an
# entity an earlier doc created) is a deliberate open task for the persistence
# workstream; until it lands, fail loud instead of clobbering. See CLAUDE.md.
# --------------------------------------------------------------------------
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
    # v2: attribute-path -> citation, serialized as a JSON map (mode="json"
    # renders the LocationType enum + int page as JSON scalars).
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
        " chip_launch_date, attribute_citations) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ent.entity_id, _enum(ent.entity_type), ent.vendor, ent.name,
            json.dumps(ent.aliases),
            node.density_mtx_mm2, _enum(node.transistor_type),
            _b(node.backside_power), _d(node.hvm_date_claimed),
            _d(node.hvm_date_actual),
            chip.process_node_ref, chip.transistor_count_b, chip.die_size_mm2,
            chip.package_type, chip.memory_type, chip.memory_bw_gbps, chip.tdp_w,
            _d(chip.launch_date), json.dumps(attr_cites),
        ),
    )


def insert_claim(conn: sqlite3.Connection, claim: models.Claim) -> None:
    c = claim
    # The claim's corroboration verdict is NOT persisted (v3 / decision B2): it is a
    # per-group fact analyze derives on read, not a property of the stored row. The
    # store deliberately holds no corr_status column — read the AnalysisReport.
    conn.execute(
        "INSERT INTO claim"
        "(claim_id, doc_id, entity_id, claim_class, metric, value, unit, "
        " cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated, "
        " cond_workload, cond_precision, cond_sparsity, cond_thermal_config, "
        " cond_stated_caveats, completeness, cite_page, cite_quote_span, "
        " cite_location_type) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            c.claim_id, c.doc_id, c.entity_id, _enum(c.claim_class), c.metric,
            c.value, c.unit,
            _b(c.comparison.is_relative), c.comparison.baseline_entity,
            _b(c.comparison.baseline_stated),
            c.conditions.workload, c.conditions.precision,
            _b(c.conditions.sparsity), c.conditions.thermal_config,
            json.dumps(c.conditions.stated_caveats), _enum(c.completeness),
            c.citation.page, c.citation.quote_span, _enum(c.citation.location_type),
        ),
    )


# --------------------------------------------------------------------------
# Read helpers (used by analyze/ and the `report` command)
# --------------------------------------------------------------------------
def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("document", "entity", "claim", "macro_snapshot")
    return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}


def stored_doc_shas(conn: sqlite3.Connection) -> dict[str, str]:
    """doc_id -> file_sha256 for every persisted Document. `run_extract` uses this
    to classify each ingested sidecar: an unknown doc_id is pending; the same
    doc_id AND the same file_sha256 is already extracted (an honest idempotent
    skip); the same doc_id with a DIFFERENT file_sha256 is a silent source revision
    (the schema's `file_sha256` exists precisely to detect this) — surfaced loudly,
    never skipped. Same-doc_id re-extraction/supersession is deferred (see
    CLAUDE.md); the guarantee here is that a revision is never silently dropped."""
    return {
        row["doc_id"]: row["file_sha256"]
        for row in conn.execute("SELECT doc_id, file_sha256 FROM document")
    }


from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimView:
    """A read-only claim projection joined to its document's source_tier — exactly
    what analyze needs, without reconstructing the full nested Claim model."""

    claim_id: str
    doc_id: str
    entity_id: str
    metric: str
    value: float
    unit: str
    is_relative: bool
    baseline_entity: str | None
    sparsity: bool | None
    completeness: str
    source_tier: int


# Column -> getter maps for fill-null reconciliation (COALESCE semantics).
_NODE_COLS = {
    "node_density_mtx_mm2": lambda n: n.density_mtx_mm2,
    "node_transistor_type": lambda n: _enum(n.transistor_type),
    "node_backside_power": lambda n: _b(n.backside_power),
    "node_hvm_date_claimed": lambda n: _d(n.hvm_date_claimed),
    "node_hvm_date_actual": lambda n: _d(n.hvm_date_actual),
}
_CHIP_COLS = {
    "chip_process_node_ref": lambda c: c.process_node_ref,
    "chip_transistor_count_b": lambda c: c.transistor_count_b,
    "chip_die_size_mm2": lambda c: c.die_size_mm2,
    "chip_package_type": lambda c: c.package_type,
    "chip_memory_type": lambda c: c.memory_type,
    "chip_memory_bw_gbps": lambda c: c.memory_bw_gbps,
    "chip_tdp_w": lambda c: c.tdp_w,
    "chip_launch_date": lambda c: _d(c.launch_date),
}


def reconcile_entity(conn: sqlite3.Connection, ent: models.Entity) -> None:
    """Insert a new entity, or merge into an existing one: union aliases, union
    attribute_citations, and fill NULL node/chip attributes from the newcomer —
    but NEVER overwrite a non-null attribute (a conflict is left to the caller /
    a future workstream). Cross-document trust (tier precedence, poisoning) is a
    deferred Class-A decision; this is the minimal honest-data reconciler."""
    existing = conn.execute("SELECT * FROM entity WHERE entity_id = ?", (ent.entity_id,)).fetchone()
    if existing is None:
        insert_entity(conn, ent)
        return

    aliases = json.loads(existing["aliases"])
    for alias in ent.aliases:
        if alias not in aliases:
            aliases.append(alias)

    attr_cites = json.loads(existing["attribute_citations"])
    for path, cite in ent.attribute_citations.items():
        attr_cites.setdefault(path, cite.model_dump(mode="json"))

    node = ent.node or models.NodeAttributes()
    chip = ent.chip or models.ChipAttributes()
    set_cols = ["aliases = ?", "attribute_citations = ?"]
    params: list[object] = [json.dumps(aliases), json.dumps(attr_cites)]
    # fill NULL columns only (COALESCE keeps a non-null existing value)
    for col, getter in list(_NODE_COLS.items()) + list(_CHIP_COLS.items()):
        set_cols.append(f"{col} = COALESCE({col}, ?)")
        params.append(getter(node if col.startswith("node_") else chip))
    params.append(ent.entity_id)
    conn.execute(f"UPDATE entity SET {', '.join(set_cols)} WHERE entity_id = ?", params)


def get_entities_index(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """entity_id -> aliases, for every reconciled entity in the store."""
    return {
        row["entity_id"]: json.loads(row["aliases"])
        for row in conn.execute("SELECT entity_id, aliases FROM entity")
    }


def get_claims_for_analysis(conn: sqlite3.Connection) -> list[ClaimView]:
    """Every claim, joined to its document's source_tier."""
    rows = conn.execute(
        "SELECT c.claim_id, c.doc_id, c.entity_id, c.metric, c.value, c.unit, "
        "       c.cmp_is_relative, c.cmp_baseline_entity, c.cond_sparsity, "
        "       c.completeness, d.source_tier "
        "FROM claim c JOIN document d ON c.doc_id = d.doc_id"
    ).fetchall()
    return [
        ClaimView(
            claim_id=r["claim_id"], doc_id=r["doc_id"], entity_id=r["entity_id"],
            metric=r["metric"], value=r["value"], unit=r["unit"],
            is_relative=bool(r["cmp_is_relative"]),
            baseline_entity=r["cmp_baseline_entity"],
            sparsity=None if r["cond_sparsity"] is None else bool(r["cond_sparsity"]),
            completeness=r["completeness"], source_tier=int(r["source_tier"]),
        )
        for r in rows
    ]


def report_counts(config: Config | None = None) -> dict[str, int]:
    """Row counts per table. The library entry point behind `semianalyst report`
    (and a future web UI) — callers never open a connection themselves."""
    config = config or load_config()
    conn = connect(config.paths.db_path)
    try:
        return table_counts(conn)
    finally:
        conn.close()
