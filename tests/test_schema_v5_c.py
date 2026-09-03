"""GEI-7 schema v5 continued tests (c)."""
from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from semianalyst import store
from semianalyst.extract.validate import validate_proposal
from semianalyst.store import models as m

from tests.test_schema_v5 import (
    _doc, _cite, _interval, _range_claim, _pkg_runc,
)


def test_no_python_resolver_function_exists():
    import semianalyst.store.models as models_mod
    import semianalyst.store.db as db_mod
    forbidden = (
        "pick_winner", "resolve_conflict", "winning_tier", "rank_source",
        "advisory_source_weight", "choose_tier", "auto_resolve",
    )
    for name in forbidden:
        assert not hasattr(models_mod, name), name
        assert not hasattr(db_mod, name), name
        assert not hasattr(m.Claim, name), name


def test_foundry_path_still_persists(tmp_config):
    store.init_db(tmp_config)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        versions = [r["version"] for r in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
        assert versions == [1, 2, 3, 4, 5]
        node = m.Entity(
            entity_id="tsmc_n2", entity_type=m.EntityType.process_node,
            vendor="TSMC", name="N2",
            node=m.NodeAttributes(transistor_type=m.TransistorType.gaa_nanosheet),
            attribute_citations={"node.transistor_type": _cite("N2 GAA")},
        )
        foundry_doc = m.Document(
            doc_id="tsmc_n2_2025", title="TSMC N2", publisher="TSMC",
            doc_type=m.DocType.foundry_announcement, source_tier=m.SourceTier.foundry,
            url="https://example.com/n2", file_sha256="a" * 64,
            ingest_date=dt.date(2025, 4, 24),
        )
        claim = m.Claim(
            claim_id="c1", doc_id="tsmc_n2_2025", entity_id="tsmc_n2",
            claim_class=m.ClaimClass.performance, metric="logic_speed",
            value=1.15, unit="x",
            comparison=m.Comparison(is_relative=True, baseline_entity="tsmc_n3e", baseline_stated=True),
            completeness=m.Completeness.complete, citation=_cite("15% faster"),
        )
        store.persist_extraction(conn, foundry_doc, [node], [claim])
        conn.commit()
        row = conn.execute("SELECT value, unit, version_range FROM claim").fetchone()
        assert row["value"] == 1.15
        assert row["unit"] == "x"
        assert row["version_range"] is None
    finally:
        conn.close()


def test_validate_rejects_inferred_exclusive_bound_not_in_quote():
    proposal = {
        "entities": [{
            "entity_id": "pkg_runc", "entity_type": "package",
            "vendor": "opencontainers", "name": "runc",
            "package": {"ecosystem": "go", "name": "github.com/opencontainers/runc"},
            "attribute_citations": {
                "package.ecosystem": {"quote_span": "ecosystem go", "location_type": "unknown"},
                "package.name": {"quote_span": "github.com/opencontainers/runc", "location_type": "unknown"},
            },
        }],
        "claims": [{
            "claim_id": "c1", "doc_id": "nvd_21626", "entity_id": "pkg_runc",
            "cve_id": "CVE-2024-21626", "claim_class": "affected_range",
            "metric": "affected_range",
            "version_range": {"intervals": [{"end": {"version": "1.1.12", "inclusive": False}}]},
            "completeness": "complete",
            "citation": {"quote_span": "runc 1.1.11 and earlier", "location_type": "unknown"},
        }],
    }
    src = "runc 1.1.11 and earlier. ecosystem go. github.com/opencontainers/runc"
    result, rej = validate_proposal(proposal, src)
    assert result.claims == []
    assert any("version_bound" in r.reason for r in rej)
