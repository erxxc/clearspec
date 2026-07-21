"""Persistence + entity reconciliation (store.persist_extraction / db.reconcile_entity)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from semianalyst import store
from semianalyst.store import models as m


def _doc(doc_id: str) -> m.Document:
    return m.Document(doc_id=doc_id, title="t", publisher="TSMC",
                      doc_type=m.DocType.foundry_announcement, source_tier=m.SourceTier.foundry,
                      url="https://x", file_sha256="0" * 64, ingest_date=dt.date(2026, 1, 1))


def _entity(aliases, node=None) -> m.Entity:
    return m.Entity(entity_id="tsmc_n2", entity_type=m.EntityType.process_node,
                    vendor="TSMC", name="N2", aliases=aliases, node=node)


def _conn(tmp_config):
    store.init_db(tmp_config)
    return store.connect(tmp_config.paths.db_path)


def test_alias_union_across_documents(tmp_config):
    conn = _conn(tmp_config)
    try:
        store.persist_extraction(conn, _doc("d1"), [_entity(["N2"])], [])
        store.persist_extraction(conn, _doc("d2"), [_entity(["N2", "TSMC 2nm"])], [])
        conn.commit()
        aliases = json.loads(conn.execute(
            "SELECT aliases FROM entity WHERE entity_id='tsmc_n2'").fetchone()["aliases"])
        assert set(aliases) == {"N2", "TSMC 2nm"}
        assert conn.execute("SELECT COUNT(*) AS n FROM entity").fetchone()["n"] == 1
    finally:
        conn.close()


def test_fill_null_never_overwrites_non_null(tmp_config):
    conn = _conn(tmp_config)
    try:
        # doc1: transistor_type set (non-null); doc2: a DIFFERENT transistor_type
        # (must NOT overwrite) plus a new backside_power (must fill the null).
        store.persist_extraction(conn, _doc("d1"),
            [_entity(["N2"], node=m.NodeAttributes(transistor_type=m.TransistorType.finfet))], [])
        store.persist_extraction(conn, _doc("d2"),
            [_entity(["N2"], node=m.NodeAttributes(transistor_type=m.TransistorType.cfet,
                                                   backside_power=False))], [])
        conn.commit()
        row = conn.execute("SELECT node_transistor_type, node_backside_power "
                           "FROM entity WHERE entity_id='tsmc_n2'").fetchone()
        assert row["node_transistor_type"] == "finfet"   # first value kept, not clobbered
        assert row["node_backside_power"] == 0            # null filled from the newcomer
    finally:
        conn.close()


def test_claim_id_is_document_scoped(tmp_config):
    conn = _conn(tmp_config)
    try:
        store.persist_extraction(conn, _doc("d1"), [_entity(["N2"])], [
            m.Claim(claim_id="logic_speed", doc_id="d1", entity_id="tsmc_n2",
                    claim_class=m.ClaimClass.performance, metric="logic_speed", value=1.15, unit="x",
                    comparison=m.Comparison(is_relative=True, baseline_stated=True),
                    completeness=m.Completeness.complete,
                    citation=m.Citation(quote_span="x", location_type=m.LocationType.unknown))])
        conn.commit()
        cid = conn.execute("SELECT claim_id FROM claim").fetchone()["claim_id"]
        assert cid == "d1:logic_speed"
    finally:
        conn.close()


def test_duplicate_document_is_fail_loud(tmp_config):
    conn = _conn(tmp_config)
    try:
        store.persist_extraction(conn, _doc("d1"), [], [])
        with pytest.raises(Exception):  # sqlite3.IntegrityError — a duplicate doc_id must raise
            store.persist_extraction(conn, _doc("d1"), [], [])
    finally:
        conn.close()
