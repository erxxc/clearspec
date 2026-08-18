"""Persistence + entity reconciliation (store.persist_extraction / db.reconcile_entity)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from semianalyst import store
from semianalyst.store import models as m


def _doc(doc_id: str, publisher="TSMC") -> m.Document:
    return m.Document(doc_id=doc_id, title="t", publisher=publisher,
                      doc_type=m.DocType.foundry_announcement, source_tier=m.SourceTier.foundry,
                      url="https://x", file_sha256="0" * 64, ingest_date=dt.date(2026, 1, 1))


def _entity(aliases, node=None, *, entity_id="tsmc_n2", vendor="TSMC", name="N2",
            chip=None) -> m.Entity:
    return m.Entity(entity_id=entity_id, entity_type=m.EntityType.process_node,
                    vendor=vendor, name=name, aliases=aliases, node=node, chip=chip)


def _claim(claim_id: str, doc_id: str, metric="logic_speed") -> m.Claim:
    return m.Claim(claim_id=claim_id, doc_id=doc_id, entity_id="tsmc_n2",
                   claim_class=m.ClaimClass.performance, metric=metric, value=1.15, unit="x",
                   comparison=m.Comparison(is_relative=True, baseline_stated=True),
                   completeness=m.Completeness.complete,
                   citation=m.Citation(quote_span="x", location_type=m.LocationType.unknown))


def _conn(tmp_config):
    store.init_db(tmp_config)
    return store.connect(tmp_config.paths.db_path)


def _conflicts(conn) -> list[tuple]:
    """The deterministic identity of each conflict row (created_at is a
    store-stamped wall clock; conflict_id an autoincrement — neither is content)."""
    return [(c.kind.value, c.entity_id, c.doc_id, c.field, c.stored_value, c.offered_value)
            for c in store.get_conflicts(conn)]


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


# --------------------------------------------------------------------------
# Conflict records (v4 — 2026-08-18 gate: Conflict 1, K1/K2, G3). The merge
# never overwrites; what it refuses to apply is persisted, naming the offender.
# --------------------------------------------------------------------------
def test_null_race_records_one_attribute_conflict(tmp_config):
    conn = _conn(tmp_config)
    try:
        # doc A fills the null; doc B later offers a DIFFERENT value: the stored
        # value stays, and the refusal is recorded ONCE, naming doc B.
        store.persist_extraction(conn, _doc("d1"),
            [_entity(["N2"], node=m.NodeAttributes(transistor_type=m.TransistorType.finfet))], [])
        store.persist_extraction(conn, _doc("d2"),
            [_entity(["N2"], node=m.NodeAttributes(transistor_type=m.TransistorType.cfet))], [])
        conn.commit()
        row = conn.execute("SELECT node_transistor_type FROM entity "
                           "WHERE entity_id='tsmc_n2'").fetchone()
        assert row["node_transistor_type"] == "finfet"
        assert _conflicts(conn) == [
            ("attribute", "tsmc_n2", "d2", "node.transistor_type", "finfet", "cfet")]
        assert store.conflict_counts_by_entity(conn) == {"tsmc_n2": 1}
    finally:
        conn.close()


def test_equal_reoffer_records_no_conflict(tmp_config):
    conn = _conn(tmp_config)
    try:
        node = m.NodeAttributes(transistor_type=m.TransistorType.finfet, backside_power=True)
        store.persist_extraction(conn, _doc("d1"), [_entity(["N2"], node=node)], [])
        store.persist_extraction(conn, _doc("d2"), [_entity(["N2"], node=node)], [])
        conn.commit()
        assert _conflicts(conn) == []
        assert store.conflict_counts_by_entity(conn) == {}
    finally:
        conn.close()


def test_identity_typo_is_a_conflict_but_case_only_is_not(tmp_config):
    conn = _conn(tmp_config)
    try:
        store.persist_extraction(conn, _doc("d1"), [_entity(["N2"])], [])
        # Case-only re-description: the same identity, NOT a conflict.
        store.persist_extraction(conn, _doc("d2"), [_entity(["N2"], vendor="tsmc")], [])
        conn.commit()
        assert _conflicts(conn) == []
        # A real difference (the typo'd-vendor conflation attack): recorded, and
        # the stored identity stays frozen by the first document.
        store.persist_extraction(conn, _doc("d3"), [_entity(["N2"], vendor="TMSC")], [])
        conn.commit()
        assert _conflicts(conn) == [
            ("identity_field", "tsmc_n2", "d3", "vendor", "TSMC", "TMSC")]
        row = conn.execute("SELECT vendor FROM entity WHERE entity_id='tsmc_n2'").fetchone()
        assert row["vendor"] == "TSMC"
    finally:
        conn.close()


def test_alias_collision_is_refused_and_recorded(tmp_config):
    conn = _conn(tmp_config)
    try:
        store.persist_extraction(conn, _doc("d1"), [
            _entity(["N2"]),
            _entity(["N3E"], entity_id="tsmc_n3e", name="N3E"),
        ], [])
        # d2 re-offers tsmc_n2 with: an alias equal (case-insensitively) to
        # ANOTHER entity's name -> refused (G3), and a normal new alias -> unioned.
        store.persist_extraction(conn, _doc("d2"),
            [_entity(["N2", "n3e", "TSMC 2nm"])], [])
        conn.commit()
        aliases = json.loads(conn.execute(
            "SELECT aliases FROM entity WHERE entity_id='tsmc_n2'").fetchone()["aliases"])
        assert set(aliases) == {"N2", "TSMC 2nm"}  # the colliding alias never unioned
        assert _conflicts(conn) == [
            ("alias_collision", "tsmc_n2", "d2", "alias", None, "n3e")]
    finally:
        conn.close()


def test_conflict_values_truncate_at_120(tmp_config):
    conn = _conn(tmp_config)
    try:
        # chip.package_type is unbounded in ChipAttributes — an over-long offered
        # value must land in the conflict record truncated to the 120-char bound
        # (the Conflict model and the entity_conflict CHECK both enforce it).
        store.persist_extraction(conn, _doc("d1"),
            [_entity(["N2"], chip=m.ChipAttributes(package_type="CoWoS"))], [])
        store.persist_extraction(conn, _doc("d2"),
            [_entity(["N2"], chip=m.ChipAttributes(package_type="X" * 300))], [])
        conn.commit()
        [(kind, _, _, field, stored, offered)] = _conflicts(conn)
        assert (kind, field, stored) == ("attribute", "chip.package_type", "CoWoS")
        assert offered == "X" * 120
    finally:
        conn.close()


def test_claimview_publisher_joined_from_document(tmp_config):
    conn = _conn(tmp_config)
    try:
        store.persist_extraction(conn, _doc("d1", publisher="TSMC"),
                                 [_entity(["N2"])], [_claim("c1", "d1")])
        store.persist_extraction(conn, _doc("d2", publisher="Vendor Z"),
                                 [_entity(["N2"])], [_claim("c2", "d2")])
        conn.commit()
        by_doc = {c.doc_id: c.publisher for c in store.get_claims_for_analysis(conn)}
        assert by_doc == {"d1": "TSMC", "d2": "Vendor Z"}
    finally:
        conn.close()
