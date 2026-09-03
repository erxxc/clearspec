
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
_PKG_COLS = {
    "pkg_ecosystem": lambda p: None if p is None else p.ecosystem,
    "pkg_name": lambda p: None if p is None else p.name,
    "pkg_purl": lambda p: None if p is None else p.purl,
    "pkg_cpe": lambda p: None if p is None else p.cpe,
}
_PRODUCT_COLS = {
    "product_ecosystem": lambda p: None if p is None else p.ecosystem,
    "product_name": lambda p: None if p is None else p.name,
    "product_purl": lambda p: None if p is None else p.purl,
    "product_cpe": lambda p: None if p is None else p.cpe,
}
_CVE_COLS = {
    "cve_id": lambda c: None if c is None else c.cve_id,
    "cve_cwe": lambda c: None if c is None else c.cwe,
}

_COL_PATH = {
    **{col: col.replace("_", ".", 1) for col in list(_NODE_COLS) + list(_CHIP_COLS)},
    "pkg_ecosystem": "package.ecosystem",
    "pkg_name": "package.name",
    "pkg_purl": "package.purl",
    "pkg_cpe": "package.cpe",
    "product_ecosystem": "product.ecosystem",
    "product_name": "product.name",
    "product_purl": "product.purl",
    "product_cpe": "product.cpe",
    "cve_id": "cve.cve_id",
    "cve_cwe": "cve.cwe",
}

_IDENTITY_COLS = ("vendor", "name", "entity_type")


def _conflict_repr(value: object) -> str:
    return _CTRL_RE.sub(" ", str(value))[:120]


_CTRL_RE = re.compile(CTRL_CLASS)


class StoreNotInitialized(RuntimeError):
    """The DB file exists but carries no schema."""


def _translate_missing_schema(exc: sqlite3.OperationalError) -> Exception:
    if "no such table" in str(exc):
        return StoreNotInitialized("database schema missing — run `semianalyst db init` first")
    return exc


def _foreign_surface_forms(conn: sqlite3.Connection, entity_id: str) -> set[str]:
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
        created_at="",
    )


def reconcile_entity(conn: sqlite3.Connection, ent: models.Entity, doc_id: str) -> None:
    """Insert or merge. NEVER overwrites; no tier exception. Advisory package /
    product / cve attributes follow the same K1/K2 never-overwrite as node/chip.
    No path picks a winning source_record_kind — that lives on claims, not here.
    """
    existing = conn.execute("SELECT * FROM entity WHERE entity_id = ?", (ent.entity_id,)).fetchone()
    if existing is None:
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

    for col in _IDENTITY_COLS:
        offered = _enum(getattr(ent, col))
        if fold(str(offered)) != fold(str(existing[col])):
            insert_conflict(conn, _refusal(
                models.ConflictKind.identity_field, ent.entity_id, doc_id,
                col, existing[col], offered))

    attr_cites = json.loads(existing["attribute_citations"])
    node = ent.node or models.NodeAttributes()
    chip = ent.chip or models.ChipAttributes()
    set_cols: list[str] = []
    params: list[object] = []

    attr_groups = [
        (_NODE_COLS, node),
        (_CHIP_COLS, chip),
        (_PKG_COLS, ent.package),
        (_PRODUCT_COLS, ent.product),
        (_CVE_COLS, ent.cve),
    ]
    for col_map, obj in attr_groups:
        for col, getter in col_map.items():
            offered = getter(obj)
            if offered is None:
                continue
            stored = existing[col]
            path = _COL_PATH[col]
            if stored is None:
                set_cols.append(f"{col} = ?")
                params.append(offered)
                if path in ent.attribute_citations:
                    attr_cites[path] = ent.attribute_citations[path].model_dump(mode="json")
            elif stored != offered:
                insert_conflict(conn, _refusal(
                    models.ConflictKind.attribute, ent.entity_id, doc_id,
                    path, stored, offered))

    aliases = json.loads(existing["aliases"])
    if ent.aliases:
        foreign = _foreign_surface_forms(conn, ent.entity_id)
        have = {fold(a) for a in aliases}
        for alias in ent.aliases:
            f = fold(alias)
            if f in have:
                continue
            if f in foreign:
                insert_conflict(conn, _refusal(
                    models.ConflictKind.alias_collision, ent.entity_id, doc_id,
                    "alias", None, alias))
            elif len(aliases) >= MAX_ALIASES_PER_ENTITY:
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
    return {
        row["entity_id"]: json.loads(row["aliases"])
        for row in conn.execute("SELECT entity_id, aliases FROM entity")
    }


def get_entities_for_analysis(conn: sqlite3.Connection) -> list[dict]:
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
    try:
        rows = conn.execute(
            "SELECT c.claim_id, c.doc_id, c.entity_id, c.metric, c.value, c.unit, "
            "       c.cmp_is_relative, c.cmp_baseline_entity, c.cond_sparsity, "
            "       c.completeness, d.source_tier, d.publisher, "
            "       c.claim_class, c.source_record_kind, c.cve_id, "
            "       c.version_range, c.exploit_status, c.workaround_text "
            "FROM claim c JOIN document d ON c.doc_id = d.doc_id"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise _translate_missing_schema(exc) from exc
    out: list[ClaimView] = []
    for r in rows:
        vr = r["version_range"]
        if isinstance(vr, str):
            vr = json.loads(vr)
        out.append(ClaimView(
            claim_id=r["claim_id"], doc_id=r["doc_id"], entity_id=r["entity_id"],
            metric=r["metric"], value=r["value"], unit=r["unit"] or "",
            is_relative=bool(r["cmp_is_relative"]),
            baseline_entity=r["cmp_baseline_entity"],
            sparsity=None if r["cond_sparsity"] is None else bool(r["cond_sparsity"]),
            completeness=r["completeness"], source_tier=int(r["source_tier"]),
            publisher=r["publisher"],
            claim_class=r["claim_class"],
            source_record_kind=r["source_record_kind"],
            cve_id=r["cve_id"],
            version_range=vr,
            exploit_status=r["exploit_status"],
            workaround_text=r["workaround_text"],
        ))
    return out


def report_counts(config: Config | None = None) -> dict[str, int]:
    config = config or load_config()
    conn = connect(config.paths.db_path)
    try:
        return table_counts(conn)
    finally:
        conn.close()
