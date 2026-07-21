"""Store layer: migrations, inserts, and the schema's non-negotiable invariants."""

from __future__ import annotations

import datetime as dt

from semianalyst import store
from semianalyst.store import models


def _tables(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_init_db_creates_schema(tmp_config):
    path = store.init_db(tmp_config)
    assert path.exists()
    conn = store.connect(path)
    try:
        assert {"document", "entity", "claim", "macro_snapshot", "schema_migrations"} <= _tables(conn)
        applied = conn.execute("SELECT version FROM schema_migrations").fetchall()
        assert [r["version"] for r in applied] == [1, 2, 3]  # initial + v2 grounding + v3 weakly_corroborated
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_config):
    store.init_db(tmp_config)
    store.init_db(tmp_config)  # second run must not re-apply or error
    conn = store.connect(tmp_config.paths.db_path)
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"]
        assert n == 3  # all migrations applied once; second init_db is a no-op
    finally:
        conn.close()


def test_insert_and_count(tmp_config):
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        store.insert_document(conn, models.Document(
            doc_id="tsmc_n2_2025",
            title="TSMC unveils N2",
            publisher="TSMC",
            doc_type=models.DocType.foundry_announcement,
            source_tier=models.SourceTier.foundry,
            url="https://example.test/n2",
            file_sha256="0" * 64,
            ingest_date=dt.date(2026, 1, 1),
        ))
        store.insert_entity(conn, models.Entity(
            entity_id="tsmc_n3e", entity_type=models.EntityType.process_node,
            vendor="TSMC", name="N3E",
        ))
        store.insert_entity(conn, models.Entity(
            entity_id="tsmc_n2", entity_type=models.EntityType.process_node,
            vendor="TSMC", name="N2", aliases=["N2"],
            node=models.NodeAttributes(transistor_type=models.TransistorType.gaa_nanosheet),
        ))
        store.insert_claim(conn, models.Claim(
            claim_id="tsmc_n2_speed_vs_n3e", doc_id="tsmc_n2_2025", entity_id="tsmc_n2",
            claim_class=models.ClaimClass.performance, metric="logic_speed",
            value=1.15, unit="x",
            comparison=models.Comparison(is_relative=True, baseline_entity="tsmc_n3e", baseline_stated=True),
            conditions=models.Conditions(stated_caveats=["at iso-power"]),
            completeness=models.Completeness.complete,
            citation=models.Citation(page=1, quote_span="N2 delivers 1.15x", location_type=models.LocationType.body),
        ))
        conn.commit()
        assert store.table_counts(conn) == {"document": 1, "entity": 2, "claim": 1, "macro_snapshot": 0}
    finally:
        conn.close()


def test_relative_claim_keeps_ratio_and_baseline(tmp_config):
    """The core schema rule: a relative claim stores the ratio + baseline ref,
    never a reconstructed absolute."""
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        store.insert_document(conn, models.Document(
            doc_id="d", title="t", publisher="TSMC",
            doc_type=models.DocType.foundry_announcement, source_tier=models.SourceTier.foundry,
            url="https://example.test", file_sha256="0" * 64, ingest_date=dt.date(2026, 1, 1),
        ))
        store.insert_entity(conn, models.Entity(entity_id="base", entity_type=models.EntityType.process_node, vendor="TSMC", name="N3E"))
        store.insert_entity(conn, models.Entity(entity_id="e", entity_type=models.EntityType.process_node, vendor="TSMC", name="N2"))
        store.insert_claim(conn, models.Claim(
            claim_id="c", doc_id="d", entity_id="e",
            claim_class=models.ClaimClass.performance, metric="logic_speed", value=1.15, unit="x",
            comparison=models.Comparison(is_relative=True, baseline_entity="base", baseline_stated=True),
            completeness=models.Completeness.complete,
            citation=models.Citation(quote_span="1.15x", location_type=models.LocationType.body),
        ))
        conn.commit()
        row = conn.execute(
            "SELECT value, unit, cmp_is_relative, cmp_baseline_entity FROM claim WHERE claim_id='c'"
        ).fetchone()
        assert row["cmp_is_relative"] == 1
        assert row["cmp_baseline_entity"] == "base"
        assert row["value"] == 1.15 and row["unit"] == "x"  # stayed a ratio, not absolutized
    finally:
        conn.close()
