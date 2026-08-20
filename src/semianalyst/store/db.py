"""SQLite persistence — the ONLY module in semianalyst permitted to touch the DB.

Everything else calls these functions; no other module imports sqlite3 or writes
SQL. This boundary is architectural (see CLAUDE.md): it keeps the storage
representation swappable and confines the nested<->flat mapping to one place.

All writes use parameterized queries. No value is ever interpolated into SQL text.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from ..config import Config, load_config
from ..textnorm import CTRL_CLASS, fold
from . import models

# The schema's per-entity alias ceiling (v4 bounds: max_items 16) — pydantic
# enforces it per document contribution; the reconcile union enforces it here.
MAX_ALIASES_PER_ENTITY = 16

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


def insert_conflict(conn: sqlite3.Connection, conflict: models.Conflict) -> None:
    """Persist a reconciliation-refusal record (v4, 2026-08-18 gate, Conflict 1).
    `conflict_id` is assigned by AUTOINCREMENT and `created_at` is stamped here
    (UTC ISO) — the store owns the clock, exactly like migration timestamps; the
    model's `created_at` field is populated on read, never trusted on write."""
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


# --------------------------------------------------------------------------
# Read helpers (used by analyze/ and the `report` command)
# --------------------------------------------------------------------------
def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ("document", "entity", "claim", "entity_conflict", "macro_snapshot")
    try:
        return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}
    except sqlite3.OperationalError as exc:
        raise _translate_missing_schema(exc) from exc


def stored_doc_shas(conn: sqlite3.Connection) -> dict[str, str]:
    """doc_id -> file_sha256 for every persisted Document. `run_extract` uses this
    to classify each ingested sidecar: an unknown doc_id is pending; the same
    doc_id AND the same file_sha256 is already extracted (an honest idempotent
    skip); the same doc_id with a DIFFERENT file_sha256 is a silent source revision
    (the schema's `file_sha256` exists precisely to detect this) — surfaced loudly,
    never skipped. Same-doc_id re-extraction/supersession is deferred (see
    CLAUDE.md); the guarantee here is that a revision is never silently dropped."""
    try:
        rows = conn.execute("SELECT doc_id, file_sha256 FROM document").fetchall()
    except sqlite3.OperationalError as exc:
        raise _translate_missing_schema(exc) from exc
    return {
        row["doc_id"]: row["file_sha256"]
        for row in rows
    }


def get_conflicts(conn: sqlite3.Connection) -> list[models.Conflict]:
    """Every persisted reconciliation-refusal record, in insertion order. The
    values are ADVERSARY-AUTHORED text (see models.Conflict) — display sites must
    route them through the hardened sanitizer; this reader does not."""
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
    """entity_id -> number of recorded conflicts — the cheap summary `report`
    surfaces next to each entity (the CLI wiring is the report workstream's)."""
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
    """A read-only claim projection joined to its document's source_tier and
    publisher — exactly what analyze needs, without reconstructing the full
    nested Claim model."""

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
    # Joined from document like source_tier (WS-2a: H1's publisher-diversity
    # floor reads it). Defaulted only so pre-v4 direct construction stays valid;
    # get_claims_for_analysis always populates it.
    publisher: str = ""


# Column -> getter maps for read-compare-write reconciliation. The getters
# serialize exactly like insert_entity (dates -> ISO, bools -> 0/1, enums ->
# value), so comparisons happen on the STORED representation.
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


# Identity fields are frozen by the FIRST document that creates the entity —
# never overwritten, no tier exception (K1). Case-folded comparison: cross-doc
# casing ("TSMC"/"Tsmc") is the same identity, not a conflict.
_IDENTITY_COLS = ("vendor", "name", "entity_type")


def _conflict_repr(value: object) -> str:
    """Stringify a stored/offered value for a conflict record: dates/bools/floats
    via str() on the stored representation, control bytes scrubbed, truncated to
    the 120-char bound the Conflict model and the entity_conflict DDL both
    enforce. The scrub is load-bearing (appsec, 2026-08-18): a legacy/poisoned
    stored value carrying a control byte would otherwise fail Conflict's
    Text120 pattern and raise from INSIDE reconcile — aborting the whole
    document instead of recording the refusal."""
    return _CTRL_RE.sub(" ", str(value))[:120]


_CTRL_RE = re.compile(CTRL_CLASS)  # shared CLASS, local scrub semantics (textnorm)


class StoreNotInitialized(RuntimeError):
    """The DB file exists (or was just created by connect) but carries no
    schema — `semianalyst db init` has not been run. Raised instead of a raw
    sqlite OperationalError so the CLI can guide the operator without importing
    sqlite3 (store is the sole SQLite owner)."""


def _translate_missing_schema(exc: sqlite3.OperationalError) -> Exception:
    if "no such table" in str(exc):
        return StoreNotInitialized("database schema missing — run `semianalyst db init` first")
    return exc


def _foreign_surface_forms(conn: sqlite3.Connection, entity_id: str) -> set[str]:
    """Every OTHER entity's surface forms (name + aliases), folded via the
    SHARED textnorm.fold — one query; the store is small enough that a full
    scan per reconcile is fine."""
    foreign: set[str] = set()
    for row in conn.execute(
        "SELECT name, aliases FROM entity WHERE entity_id != ?", (entity_id,)
    ):
        foreign.add(fold(row["name"]))
        foreign.update(fold(a) for a in json.loads(row["aliases"]))
    return foreign


def _refusal(
    kind: models.ConflictKind, entity_id: str, doc_id: str, field: str,
    stored: object | None, offered: object,
) -> models.Conflict:
    return models.Conflict(
        kind=kind, entity_id=entity_id, doc_id=doc_id, field=field,
        stored_value=None if stored is None else _conflict_repr(stored),
        offered_value=_conflict_repr(offered),
        created_at="",  # store-stamped at insert (like conflict_id)
    )


def reconcile_entity(conn: sqlite3.Connection, ent: models.Entity, doc_id: str) -> None:
    """Insert a new entity, or merge a later document's re-description into an
    existing one — read-compare-write (2026-08-18 gate: Conflict 1, K1/K2, G3).

    The merge NEVER overwrites, no tier exception. What it refuses to apply is
    persisted as a Conflict naming the offending `doc_id` — the offered value has
    no other home; reconcile drops it at refusal time:
      - identity fields (vendor/name/entity_type): frozen by the first document;
        a case-folded difference is recorded as `identity_field` (case-only
        variation is the same identity, not a conflict);
      - node/chip attributes: a stored NULL is filled from the newcomer, and the
        attribute's citation moves WITH the value (never one without the other);
        a differing non-null value is recorded as `attribute` under its schema
        path (e.g. 'node.transistor_type'); an equal re-offer is a no-op;
      - aliases (G3): unioned, EXCEPT an alias that equals (case-insensitive)
        ANOTHER stored entity's name or alias — refused as `alias_collision`.
        This applies on BOTH paths — merge AND first insert — so neither a later
        doc nor a freshly minted entity can capture a competitor's surface form
        (the entity's own shape-validated name is exempt on insert).
    """
    existing = conn.execute("SELECT * FROM entity WHERE entity_id = ?", (ent.entity_id,)).fetchone()
    if existing is None:
        # G3 applies to the INSERT path too (hostile-suite finding, 2026-08-18):
        # a NEW entity must not capture another entity's surface form as an
        # alias any more than a merge may. The entity's OWN shape-validated
        # `name` is exempt (the pinned-name invariant — an identity-level
        # name squat is the J/identity domain, not alias filtering). Refused
        # aliases become alias_collision conflicts AFTER the insert (the
        # conflict row FK-references the entity).
        foreign = _foreign_surface_forms(conn, ent.entity_id)
        kept: list[str] = []
        refused: list[str] = []
        for alias in ent.aliases:
            if fold(alias) != fold(ent.name) and fold(alias) in foreign:
                refused.append(alias)
            else:
                kept.append(alias)
        insert_entity(conn, ent.model_copy(update={"aliases": kept}))
        for alias in refused:
            insert_conflict(conn, _refusal(
                models.ConflictKind.alias_collision, ent.entity_id, doc_id,
                "alias", None, alias))
        return

    # --- identity fields: compare case-folded; first writer wins (K1) ---
    for col in _IDENTITY_COLS:
        offered = _enum(getattr(ent, col))
        # SHARED fold, not bare casefold: PDF text-layer noise ("TSMC " with a
        # trailing space) is the same identity, never a spurious conflict.
        if fold(str(offered)) != fold(str(existing[col])):
            insert_conflict(conn, _refusal(
                models.ConflictKind.identity_field, ent.entity_id, doc_id,
                col, existing[col], offered))

    # --- node/chip attributes: fill NULLs (value + citation as a pair), record
    # --- a differing non-null as a conflict, never overwrite (K1/K2) ---
    attr_cites = json.loads(existing["attribute_citations"])
    node = ent.node or models.NodeAttributes()
    chip = ent.chip or models.ChipAttributes()
    set_cols: list[str] = []
    params: list[object] = []
    for col, getter in list(_NODE_COLS.items()) + list(_CHIP_COLS.items()):
        offered = getter(node if col.startswith("node_") else chip)
        if offered is None:
            continue
        stored = existing[col]
        if stored is None:
            set_cols.append(f"{col} = ?")
            params.append(offered)
            # The citation union is scoped to values actually filled — a merged
            # citation must never point at a value its document didn't supply.
            path = col.replace("_", ".", 1)  # node_transistor_type -> node.transistor_type
            if path in ent.attribute_citations:
                attr_cites[path] = ent.attribute_citations[path].model_dump(mode="json")
        elif stored != offered:
            insert_conflict(conn, _refusal(
                models.ConflictKind.attribute, ent.entity_id, doc_id,
                col.replace("_", ".", 1), stored, offered))

    # --- aliases: union, refusing cross-entity collisions (G3) and enforcing
    # --- the schema's per-entity ceiling at the true point of accumulation ---
    aliases = json.loads(existing["aliases"])
    if ent.aliases:
        foreign = _foreign_surface_forms(conn, ent.entity_id)
        have = {fold(a) for a in aliases}  # folded membership: a case/space variant is a re-offer
        for alias in ent.aliases:
            f = fold(alias)
            if f in have:
                continue  # already unioned — an equal re-offer, not a conflict
            if f in foreign:
                insert_conflict(conn, _refusal(
                    models.ConflictKind.alias_collision, ent.entity_id, doc_id,
                    "alias", None, alias))
            elif len(aliases) >= MAX_ALIASES_PER_ENTITY:
                # The schema's 16-item bound is a PER-ENTITY invariant; pydantic
                # only sees one document's contribution, so the union here is
                # the real enforcement point. Refuse the alias — never the
                # document (a fail-closed DDL under a fail-soft model layer is
                # the posture inversion the precommit gate rejected).
                insert_conflict(conn, _refusal(
                    models.ConflictKind.alias_overflow, ent.entity_id, doc_id,
                    "alias", None, alias))
            else:
                aliases.append(alias)
                have.add(f)

    set_cols += ["aliases = ?", "attribute_citations = ?"]
    params += [json.dumps(aliases), json.dumps(attr_cites), ent.entity_id]
    conn.execute(f"UPDATE entity SET {', '.join(set_cols)} WHERE entity_id = ?", params)


def get_entities_index(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """entity_id -> aliases, for every reconciled entity in the store."""
    return {
        row["entity_id"]: json.loads(row["aliases"])
        for row in conn.execute("SELECT entity_id, aliases FROM entity")
    }


def get_entities_for_analysis(conn: sqlite3.Connection) -> list[dict]:
    """Read-only identity projection for analyze's advisory checks (J slug
    collisions): entity_id, entity_type, vendor, name, aliases (decoded)."""
    return [
        {
            "entity_id": r["entity_id"], "entity_type": r["entity_type"],
            "vendor": r["vendor"], "name": r["name"],
            "aliases": json.loads(r["aliases"]),
        }
        for r in conn.execute(
            "SELECT entity_id, entity_type, vendor, name, aliases FROM entity "
            "ORDER BY entity_id"
        )
    ]


def get_claims_for_analysis(conn: sqlite3.Connection) -> list[ClaimView]:
    """Every claim, joined to its document's source_tier and publisher."""
    try:
        rows = conn.execute(
            "SELECT c.claim_id, c.doc_id, c.entity_id, c.metric, c.value, c.unit, "
            "       c.cmp_is_relative, c.cmp_baseline_entity, c.cond_sparsity, "
            "       c.completeness, d.source_tier, d.publisher "
            "FROM claim c JOIN document d ON c.doc_id = d.doc_id"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise _translate_missing_schema(exc) from exc
    return [
        ClaimView(
            claim_id=r["claim_id"], doc_id=r["doc_id"], entity_id=r["entity_id"],
            metric=r["metric"], value=r["value"], unit=r["unit"],
            is_relative=bool(r["cmp_is_relative"]),
            baseline_entity=r["cmp_baseline_entity"],
            sparsity=None if r["cond_sparsity"] is None else bool(r["cond_sparsity"]),
            completeness=r["completeness"], source_tier=int(r["source_tier"]),
            publisher=r["publisher"],
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
