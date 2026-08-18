"""The NAMED hostile suite (WS-2a gate mandate — see
docs/reviews/2026-08-18-live-ingest-plan/resolution.md and plan §3).

Constructed hostile documents/proposals driven through the REAL chain — either
`validate_proposal -> persist_extraction -> run_analysis` or the full
`ingest_file -> run_extract(injected extractor) -> run_analysis` pipeline where
the case needs the filesystem seam. Deterministic and offline: no model, no
network, no API key. One test per named case; each docstring names its attack.

The honest acceptance fixtures are never used to build a hostile case. The two
Challenge-4 guards at the bottom (`test_honest_corpus_regression`,
`test_flag_budget`) deliberately LOAD the honest analyze corpus read-only — they
pin it as the honest-corpus contract from the hostile suite's side, per the
gate's acceptance criteria.

All hostile inputs are constructed in-test (the plan's preferred form): source
text is inline, and the pipeline-level cases build minimal one-page PDFs with
`_mini_pdf`, so no binary fixture can drift silently under tests/fixtures/.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path

import pytest

from semianalyst import store
from semianalyst.analyze import run_analysis
from semianalyst.cli import _ansi_safe
from semianalyst.config import Config
from semianalyst.extract import AnthropicExtractor, ReplayModelClient, run_extract, validate_proposal
from semianalyst.ingest import SidecarCollision, forget, ingest_file
from semianalyst.store import models as m

# ---------------------------------------------------------------------------
# Builders — hostile inputs are constructed here, not stored as fixtures.
# ---------------------------------------------------------------------------


def _mini_pdf(lines: list[str]) -> bytes:
    """A minimal valid one-page PDF whose text pypdf extracts as `lines` —
    the same handcrafted structure as the committed raw.pdf fixtures, built
    in-test so each hostile document's content is visible at its use site."""

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    body = "BT\n/F1 11 Tf\n14 TL\n72 730 Td\n"
    for i, line in enumerate(lines):
        body += ("(%s) Tj\n" % esc(line)) if i == 0 else ("T* (%s) Tj\n" % esc(line))
    body += "ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(body.encode('latin-1'))} >>\nstream\n{body}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{i} 0 obj\n{obj}\nendobj\n"
    xref_pos = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n"
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    return out.encode("latin-1")


def _doc(doc_id: str, *, publisher: str, tier: int, doc_type: str = "vendor_whitepaper",
         ingest: str = "2026-01-01") -> m.Document:
    return m.Document(
        doc_id=doc_id, title=f"{doc_id} title", publisher=publisher, doc_type=doc_type,
        source_tier=tier, url=f"https://example.test/{doc_id}",
        file_sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        ingest_date=dt.date.fromisoformat(ingest),
    )


def _pe(eid: str, vendor: str, name: str, *, entity_type: str = "chip", aliases=(),
        node=None, chip=None, cites=None) -> dict:
    """A proposal-shaped entity (pre-validate dict, like the model would emit)."""
    return {"entity_id": eid, "entity_type": entity_type, "vendor": vendor, "name": name,
            "aliases": list(aliases), "node": node, "chip": chip,
            "attribute_citations": cites or {}}


def _pc(cid: str, doc_id: str, eid: str, *, metric: str, value: float, quote: str,
        unit: str = "GB/s", relative: bool = False, baseline: str | None = None,
        claim_class: str = "performance") -> dict:
    """A proposal-shaped claim. Defaults to an ABSOLUTE claim (no baseline in the
    group key) so corroboration cases carry no unrelated baseline flags."""
    return {"claim_id": cid, "doc_id": doc_id, "entity_id": eid, "claim_class": claim_class,
            "metric": metric, "value": value, "unit": unit,
            "comparison": {"is_relative": relative, "baseline_entity": baseline,
                           "baseline_stated": baseline is not None},
            "conditions": {"stated_caveats": []}, "completeness": "complete",
            "citation": {"quote_span": quote, "location_type": "body"}}


def _cite(quote: str) -> dict:
    return {"quote_span": quote, "location_type": "body"}


def _persist_validated(conn, document: m.Document, proposal: dict, source: str):
    """The real chain for store-level cases: validate the proposal against ITS
    OWN source text (grounding is per-document), then persist what survives."""
    result, rejections = validate_proposal(proposal, source)
    store.persist_extraction(conn, document, result.entities, result.claims)
    return result, rejections


def _conn(tmp_config: Config):
    store.init_db(tmp_config)
    return store.connect(tmp_config.paths.db_path)


def _conflict_keys(conn) -> list[tuple]:
    """Deterministic conflict identity (created_at/conflict_id are store-stamped)."""
    return [(c.kind.value, c.entity_id, c.doc_id, c.field, c.stored_value, c.offered_value)
            for c in store.get_conflicts(conn)]


def _aliases(conn, entity_id: str) -> list[str]:
    row = conn.execute("SELECT aliases FROM entity WHERE entity_id = ?", (entity_id,)).fetchone()
    return json.loads(row["aliases"])


# ---------------------------------------------------------------------------
# 1. alias_graft — G3 cross-entity collision refusal at reconcile
# ---------------------------------------------------------------------------
def test_alias_graft(tmp_config: Config):
    """ATTACK: a hostile second document re-describes an entity it shares with the
    store and plants a COMPETITOR entity's name ("18A") in its alias list. The
    alias IS grounded in the hostile doc's own text (the doc mentions the rival,
    naturally), so G1 keeps it — the graft must die at reconcile (G3): the union
    is refused, an alias_collision conflict names the offender, and no alias
    list ends up bridging the two identities.

    KNOWN RESIDUAL (found building this suite, 2026-08-18; not a named case):
    G3 guards the MERGE path only. A hostile doc that mints a NEW entity_id
    (different vendor, so J's same-vendor pairing never fires) can still store a
    competitor's surface form in its alias list with no refusal, no conflict,
    and no flag — inert today (grouping is by entity_id), but it pre-plants the
    capture for any future alias-based resolution."""
    conn = _conn(tmp_config)
    try:
        # Honest doc: creates both real things — TSMC N2 and the competitor Intel 18A.
        src1 = "TSMC N2 enters production. Intel 18A is a rival process node."
        _persist_validated(conn, _doc("d1", publisher="TSMC", tier=2), {
            "entities": [
                _pe("tsmc_n2", "TSMC", "N2", entity_type="process_node"),
                _pe("intel_18a", "Intel", "18A", entity_type="process_node"),
            ],
            "claims": [],
        }, src1)

        # Hostile doc: re-describes tsmc_n2 with the competitor's name as an alias.
        src2 = "TSMC N2 beats 18A on every speed metric."
        result, rejections = _persist_validated(
            conn, _doc("d2", publisher="Rival Labs", tier=3), {
                "entities": [_pe("tsmc_n2", "TSMC", "N2", entity_type="process_node",
                                 aliases=["18A"])],
                "claims": [],
            }, src2)
        conn.commit()

        # G1 kept the grounded alias — validate alone is NOT the defense here.
        assert "18A" in result.entities[0].aliases

        # G3 refused the union: neither identity's surface forms were bridged.
        assert _aliases(conn, "tsmc_n2") == ["N2"]          # graft never unioned
        assert _aliases(conn, "intel_18a") == ["18A"]       # competitor unpolluted
        assert _conflict_keys(conn) == [
            ("alias_collision", "tsmc_n2", "d2", "alias", None, "18A")]
        assert store.conflict_counts_by_entity(conn) == {"tsmc_n2": 1}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. alias_ungrounded — G1 alias grounding at validate
# ---------------------------------------------------------------------------
def test_alias_ungrounded(tmp_config: Config):
    """ATTACK: a hostile proposal plants an alias ("CompetitorY Max") that never
    appears in its document's source text — the classic capture-by-alias plant.
    G1 drops it at validate with an entity_alias rejection (indexed target, no
    raw model text), and the store never sees it."""
    conn = _conn(tmp_config)
    try:
        src = "Acme ships X1 worldwide."
        result, rejections = _persist_validated(
            conn, _doc("d1", publisher="Acme", tier=3), {
                "entities": [_pe("acme_x1", "Acme", "X1", aliases=["CompetitorY Max"])],
                "claims": [],
            }, src)
        conn.commit()

        assert result.entities[0].aliases == ["X1"]  # canonical name pinned; plant gone
        dropped = [r for r in rejections if r.kind == "entity_alias"]
        assert [(r.target, r.reason) for r in dropped] == [
            ("acme_x1:0", "alias not found in source")]
        assert _aliases(conn, "acme_x1") == ["X1"]   # never reached the store
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. field_flood — v4 content bounds, fail-soft per item + DDL CHECK backstop
# ---------------------------------------------------------------------------
def test_field_flood(tmp_config: Config):
    """ATTACK: oversize/hostile strings flood the proposal — a >120-char metric,
    a >16-item alias list, a control-character (ANSI ESC) vendor, and a
    >200-char claim_id. Each drops ITS item fail-soft at the pydantic shape
    stage (v4 bounds); sibling items survive; nothing crashes end-to-end. Belt
    AND suspenders: the DDL mirrors the length bounds as CHECK constraints, so
    a hand-built over-limit INSERT through a raw sqlite3 connection (bypassing
    pydantic entirely) is refused by the database itself."""
    conn = _conn(tmp_config)
    try:
        src = "V ships N and W ships M. N reaches 40 GB/s in tests."
        proposal = {
            "entities": [
                _pe("good_e", "V", "N"),                                    # survivor
                _pe("flood_e", "W", "M", aliases=[f"a{i}" for i in range(17)]),  # >16 aliases
                _pe("ctrl_e", "V\x1b[31mendor", "M"),                       # C0 byte in vendor
            ],
            "claims": [
                _pc("good", "d1", "good_e", metric="throughput", value=40.0,
                    quote="N reaches 40 GB/s in tests."),                   # survivor
                _pc("big_metric", "d1", "good_e", metric="m" * 121, value=40.0,
                    quote="N reaches 40 GB/s in tests."),                   # metric > 120
                _pc("c" * 201, "d1", "good_e", metric="throughput2", value=40.0,
                    quote="N reaches 40 GB/s in tests."),                   # claim_id > 200
            ],
        }
        result, rejections = _persist_validated(
            conn, _doc("d1", publisher="V", tier=3), proposal, src)
        conn.commit()

        # Fail-soft per ITEM: only the flood items died; the siblings survived.
        assert [e.entity_id for e in result.entities] == ["good_e"]
        assert [c.claim_id for c in result.claims] == ["good"]
        shape_rejected = {r.kind for r in rejections if "shape invalid" in r.reason}
        assert shape_rejected == {"entity", "claim"}
        assert len([r for r in rejections if "shape invalid" in r.reason]) == 4

        # ...and the surviving result persisted cleanly (nothing crashed).
        counts = store.table_counts(conn)
        assert counts["entity"] == 1 and counts["claim"] == 1
    finally:
        conn.close()

    # DDL backstop: the same bounds hold even against a writer that bypasses the
    # models — a raw connection's over-long INSERT trips the CHECK constraints.
    raw = sqlite3.connect(tmp_config.paths.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            raw.execute(
                "INSERT INTO claim (claim_id, doc_id, entity_id, claim_class, metric,"
                " value, unit, cmp_is_relative, cmp_baseline_stated, cond_stated_caveats,"
                " completeness, cite_quote_span, cite_location_type)"
                " VALUES ('c','d','e','performance',?,1.0,'x',0,0,'[]','complete','q','unknown')",
                ("m" * 121,))
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            raw.execute(
                "INSERT INTO entity_conflict (kind, entity_id, doc_id, field,"
                " stored_value, offered_value, created_at)"
                " VALUES ('attribute','e','d','f',NULL,?,'now')",
                ("x" * 121,))
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# 4. tier3_flood — H1 publisher-diversity floor (and the H2 deferral, pinned)
# ---------------------------------------------------------------------------
def test_tier3_flood(tmp_config: Config):
    """ATTACK: one vendor prints three agreeing tier-3 PDFs about its own chip —
    one voice pretending to be a chorus. H1 refuses `corroborated`: a
    single-publisher agreement demotes to weakly_corroborated + single_publisher.
    Variant: TWO DISTINCT tier-3 publishers agreeing IS corroborated — and H2
    (the all-tier-3 confidence cap to 'medium' + vendor_only) is DEFERRED at the
    gate (resolution Conflict 3), so confidence stays 'high'. This pins the
    current behavior; ROADMAP trigger to revisit: the watchlist carries >=2
    distinct tier-3 publishers for one metric."""
    conn = _conn(tmp_config)
    try:
        # Three same-publisher tier-3 docs agreeing within tolerance.
        for i, value in enumerate((100.0, 101.0, 102.0), start=1):
            src = f"Vendor Z quarterly brief. Z reaches {value:.0f} GB/s."
            _persist_validated(conn, _doc(f"flood{i}", publisher="Vendor Z", tier=3,
                                          ingest=f"2026-01-0{i}"), {
                "entities": [_pe("vendorz_z", "Vendor Z", "Z")],
                "claims": [_pc("tp", f"flood{i}", "vendorz_z", metric="throughput",
                               value=value, quote=f"Z reaches {value:.0f} GB/s.")],
            }, src)

        # Variant: two distinct-publisher tier-3 docs agreeing on one metric.
        for i, (publisher, value) in enumerate(
                (("Alpha Corp", 100.0), ("Beta Corp", 101.0)), start=1):
            src = f"{publisher} on Gamma G1. G1 reaches {value:.0f} GB/s."
            _persist_validated(conn, _doc(f"pair{i}", publisher=publisher, tier=3,
                                          ingest=f"2026-02-0{i}"), {
                "entities": [_pe("gamma_g1", "Gamma", "G1")],
                "claims": [_pc("tp", f"pair{i}", "gamma_g1", metric="throughput",
                               value=value, quote=f"G1 reaches {value:.0f} GB/s.")],
            }, src)
        conn.commit()
    finally:
        conn.close()

    report = run_analysis(tmp_config)
    by_entity = {a.entity_id: a for a in report.assessments}
    assert set(by_entity) == {"vendorz_z", "gamma_g1"}

    flood = by_entity["vendorz_z"]
    assert flood.status == "weakly_corroborated"       # NOT corroborated
    assert flood.flags == ["single_publisher"]
    assert flood.confidence == "medium"
    assert len(flood.members) == 3

    pair = by_entity["gamma_g1"]
    assert pair.status == "corroborated"
    assert pair.flags == []
    # H2 DEFERRED (gate, Conflict 3): an all-tier-3 two-publisher agreement keeps
    # confidence 'high' with no vendor_only flag today. Revisit when the ROADMAP
    # trigger fires: watchlist carries >=2 distinct tier-3 publishers for one metric.
    assert pair.confidence == "high"
    assert pair.tiers == [3]


# ---------------------------------------------------------------------------
# 5. null_race — K2: first-writer fills the null; the honest arrival is a
#    visible conflict, not a silent loss
# ---------------------------------------------------------------------------
def test_null_race(tmp_config: Config):
    """ATTACK: a hostile document arrives FIRST and fills a null attribute with a
    wrong value (grounded in its own fabricated text — grounding proves presence,
    not truth). When the honest document later offers the real value, K1/K2
    never-overwrite keeps the stored (wrong) value — the race the hostile doc
    wins — but the defense is that the refusal is RECORDED naming the honest doc
    as offerer and SURFACED via run_analysis (identity_conflict flag +
    conflict_counts), so a human sees the dispute instead of nothing."""
    conn = _conn(tmp_config)
    try:
        # Hostile first: plants transistor_type=cfet.
        src_h = "Rival Labs teardown. TSMC N2 uses CFET transistors."
        _persist_validated(conn, _doc("hostile1", publisher="Rival Labs", tier=3), {
            "entities": [_pe("tsmc_n2", "TSMC", "N2", entity_type="process_node",
                             node={"transistor_type": "cfet"},
                             cites={"node.transistor_type":
                                    _cite("TSMC N2 uses CFET transistors.")})],
            "claims": [],
        }, src_h)

        # Honest later: the real value + a claim (so the entity has an assessment).
        src_o = ("TSMC N2 update. N2 uses gate-all-around nanosheet transistors. "
                 "N2 reaches 200 GB/s bandwidth.")
        _persist_validated(conn, _doc("honest1", publisher="TSMC", tier=2,
                                      doc_type="foundry_announcement", ingest="2026-01-02"), {
            "entities": [_pe("tsmc_n2", "TSMC", "N2", entity_type="process_node",
                             node={"transistor_type": "gaa_nanosheet"},
                             cites={"node.transistor_type":
                                    _cite("N2 uses gate-all-around nanosheet transistors.")})],
            "claims": [_pc("bw", "honest1", "tsmc_n2", metric="mem_bw", value=200.0,
                           quote="N2 reaches 200 GB/s bandwidth.")],
        }, src_o)
        conn.commit()

        # The stored value is unchanged (the hostile doc won the null race)...
        row = conn.execute("SELECT node_transistor_type FROM entity "
                           "WHERE entity_id='tsmc_n2'").fetchone()
        assert row["node_transistor_type"] == "cfet"
        # ...but the honest doc's arrival is a persisted, attributed conflict.
        assert _conflict_keys(conn) == [
            ("attribute", "tsmc_n2", "honest1", "node.transistor_type",
             "cfet", "gaa_nanosheet")]
    finally:
        conn.close()

    # Surfaced at the report layer: the reader is told this entity is disputed.
    report = run_analysis(tmp_config)
    assert report.conflict_counts == {"tsmc_n2": 1}
    [assessment] = report.assessments
    assert assessment.entity_id == "tsmc_n2"
    assert "identity_conflict" in assessment.flags
    assert "conflicts" in report.to_dict()


# ---------------------------------------------------------------------------
# 6. identity_typo — identity_field conflict; no silent conflation
# ---------------------------------------------------------------------------
def test_identity_typo(tmp_config: Config):
    """ATTACK: a second document reuses an existing entity_id under a DIFFERENT
    vendor (the typo'd-vendor conflation — 'TMSC' vs 'TSMC' would silently merge
    two real things under one id pre-WS-2a). The identity fields are frozen by
    the first document; the difference is recorded as an identity_field conflict
    naming the offender, and the stored identity is intact."""
    conn = _conn(tmp_config)
    try:
        src1 = "TSMC announces N2."
        _persist_validated(conn, _doc("d1", publisher="TSMC", tier=2,
                                      doc_type="foundry_announcement"), {
            "entities": [_pe("tsmc_n2", "TSMC", "N2", entity_type="process_node")],
            "claims": [],
        }, src1)

        # The typo'd vendor IS grounded in the second doc's own text — presence
        # grounding can't catch a typo the document itself repeats.
        src2 = "TMSC N2 process report."
        _persist_validated(conn, _doc("d2", publisher="Some Blog", tier=3,
                                      ingest="2026-01-02"), {
            "entities": [_pe("tsmc_n2", "TMSC", "N2", entity_type="process_node")],
            "claims": [],
        }, src2)
        conn.commit()

        # One entity, identity frozen by the first writer — conflated LOUDLY.
        assert conn.execute("SELECT COUNT(*) AS n FROM entity").fetchone()["n"] == 1
        row = conn.execute("SELECT vendor, name FROM entity "
                           "WHERE entity_id='tsmc_n2'").fetchone()
        assert (row["vendor"], row["name"]) == ("TSMC", "N2")
        assert _conflict_keys(conn) == [
            ("identity_field", "tsmc_n2", "d2", "vendor", "TSMC", "TMSC")]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. sidecar_clobber — S1: content identity never rebinds to a second doc_id
# ---------------------------------------------------------------------------
def test_sidecar_clobber(tmp_config: Config, tmp_path: Path):
    """ATTACK: the SAME bytes are re-ingested under a DIFFERENT doc_id — the
    sidecar-layer sibling of identity conflation. Pre-WS-2a, write_sidecar
    last-write-wins clobbered the first ingest's provenance. S1 refuses:
    SidecarCollision raises, and the first sidecar is intact on disk."""
    src = tmp_path / "brief.pdf"
    src.write_bytes(_mini_pdf(["Vendor Q brief.", "Q1 reaches 10 GB/s."]))
    kwargs = dict(title="Vendor Q brief", publisher="Vendor Q",
                  doc_type="vendor_whitepaper", source_tier=3,
                  url="https://example.test/q1", ingest_date="2026-01-01")

    first = ingest_file(tmp_config, src, doc_id="q1_brief", **kwargs)
    with pytest.raises(SidecarCollision) as exc:
        ingest_file(tmp_config, src, doc_id="q1_impostor",
                    **{**kwargs, "title": "clobbered title", "publisher": "Impostor"})
    assert "q1_brief" in str(exc.value) and "q1_impostor" in str(exc.value)

    # First ingest's provenance is byte-for-byte what it wrote — not half-updated.
    sidecar = tmp_config.paths.raw_dir / f"{first.sha256}.meta.json"
    meta = json.loads(sidecar.read_text())
    assert meta["doc_id"] == "q1_brief"
    assert meta["title"] == "Vendor Q brief" and meta["publisher"] == "Vendor Q"
    assert meta == first.meta


# ---------------------------------------------------------------------------
# 8. blob_tamper — S2: blob hash re-verified at read
# ---------------------------------------------------------------------------
def test_blob_tamper(tmp_config: Config, tmp_path: Path):
    """ATTACK: after an honest ingest, the raw blob's bytes are rewritten on disk
    (a second writer to data/raw/ — the WS-2b threat, live-tested now). The
    sidecar FILENAME still claims the old sha256; S2 recomputes the hash at
    read, reports the mismatch in ExtractReport.errors, and the tampered bytes
    never reach the extractor or the store."""
    src = tmp_path / "brief.pdf"
    src.write_bytes(_mini_pdf(["Vendor Q brief.", "Q1 reaches 10 GB/s."]))
    store.init_db(tmp_config)
    raw = ingest_file(tmp_config, src, doc_id="q1_brief", title="Vendor Q brief",
                      publisher="Vendor Q", doc_type="vendor_whitepaper", source_tier=3,
                      url="https://example.test/q1", ingest_date="2026-01-01")

    raw.blob_path.write_bytes(b"tampered payload under the same filename")

    report = run_extract(tmp_config, extractor=None)  # nothing valid pending -> no client
    assert report.extracted == [] and report.skipped == []
    assert any(ident == raw.sha256 and "hash mismatch" in reason
               for ident, reason in report.errors)
    conn = store.connect(tmp_config.paths.db_path)
    try:
        assert store.table_counts(conn)["document"] == 0  # never extracted
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 9. trojan_display — §2.8 Cf stripping at display + gate injection F3
#    (Trojan-Source payload planted in conflict.offered_value via reconcile)
# ---------------------------------------------------------------------------
def test_trojan_display(tmp_config: Config):
    """ATTACK: Trojan-Source. A hostile proposal carries bidi-override and
    zero-width payloads (U+202E, U+200B, U+FEFF — category Cf) in its metric,
    alias, and an attribute value. Cf codepoints deliberately PASS the model
    bounds (_NO_CTRL rejects only C0/DEL — a C0/ANSI payload dies at shape, as
    asserted below), so they genuinely land in the store; the guarantee under
    test is the DISPLAY edge: cli._ansi_safe strips every Cf at render. The F3
    half: the payload is also planted in conflict.offered_value THROUGH a real
    reconcile refusal (never direct SQL) — the conflict record exists to be read
    by a human, making it the highest-incentive display surface in the store —
    and the report's conflict line must render sanitized."""
    ALIAS_PAYLOAD = "Z1\u200bUltra"                 # U+200B zero-width space hides the seam
    METRIC_PAYLOAD = "band\u202ewidth\u200b"        # U+202E RLO reorders what a human reads
    PKG_PAYLOAD = "CoWoS\u202eEVIL\ufeff"           # Cf payload for offered_value (F3)

    conn = _conn(tmp_config)
    try:
        # Honest doc first: package_type=CoWoS, so the hostile offer differs.
        src1 = "Acme Z1 launch. Z1 uses CoWoS packaging."
        _persist_validated(conn, _doc("d1", publisher="Acme", tier=3), {
            "entities": [_pe("acme_z1", "Acme", "Z1",
                             chip={"package_type": "CoWoS"},
                             cites={"chip.package_type":
                                    _cite("Z1 uses CoWoS packaging.")})],
            "claims": [],
        }, src1)

        # Hostile doc: Cf-laden alias (grounded — the SOURCE TEXT is attacker-
        # authored too, so it simply contains the payload), Cf-laden metric
        # (metric is free text, never grounded), Cf-laden package_type offer.
        src2 = (f"Acme Z1 lab notes. Z1 reaches 100 GB/s. Also sold as {ALIAS_PAYLOAD}.")
        result, rejections = _persist_validated(
            conn, _doc("d2", publisher="Rival Labs", tier=3, ingest="2026-01-02"), {
                "entities": [_pe("acme_z1", "Acme", "Z1", aliases=[ALIAS_PAYLOAD],
                                 chip={"package_type": PKG_PAYLOAD},
                                 cites={"chip.package_type":
                                        _cite("Acme Z1 lab notes.")})],
                "claims": [
                    _pc("bw", "d2", "acme_z1", metric=METRIC_PAYLOAD, value=100.0,
                        quote="Z1 reaches 100 GB/s."),
                    # The ANSI half of the classic payload: a C0 ESC byte in a
                    # metric fails _NO_CTRL at shape — it can never even reach
                    # the store, which is why the stored payload is Cf-only.
                    _pc("ansi", "d2", "acme_z1", metric="bw\x1b[31m", value=1.0,
                        quote="Z1 reaches 100 GB/s."),
                ],
            }, src2)
        conn.commit()

        assert [c.claim_id for c in result.claims] == ["bw"]  # ANSI claim shape-dropped
        assert any(r.kind == "claim" and "shape invalid" in r.reason for r in rejections)

        # The Cf payloads genuinely reached the store (the premise of the attack).
        assert ALIAS_PAYLOAD in _aliases(conn, "acme_z1")
        assert _conflict_keys(conn) == [
            ("attribute", "acme_z1", "d2", "chip.package_type", "CoWoS", PKG_PAYLOAD)]
    finally:
        conn.close()

    report = run_analysis(tmp_config)
    [assessment] = report.assessments
    assert assessment.metric == METRIC_PAYLOAD          # raw in the data layer...

    # ...and stripped at the display edge, exactly where cli.report renders it.
    assert _ansi_safe(assessment.metric) == "bandwidth"
    rendered_aliases = [_ansi_safe(a)
                        for a in report.entities_reconciled["acme_z1"]["aliases"]]
    assert "Z1Ultra" in rendered_aliases
    for text in (_ansi_safe(assessment.metric), *rendered_aliases):
        assert not any(unicodedata.category(ch) == "Cf" for ch in text)

    # F3: the conflict line, built exactly as cli.report builds it, is sanitized.
    [c] = report.conflicts
    assert "\u202e" in c.offered_value              # evidence stored raw...
    stored = _ansi_safe(c.stored_value) if c.stored_value is not None else "-"
    line = (f"  [{_ansi_safe(c.kind.value)}] {_ansi_safe(c.entity_id)}"
            f" <- {_ansi_safe(c.doc_id)}  {_ansi_safe(c.field)}:"
            f" {stored} -> {_ansi_safe(c.offered_value)}")
    assert not any(unicodedata.category(ch) == "Cf" for ch in line)  # ...rendered inert
    assert "\x1b" not in line
    assert "CoWoSEVIL" in line                          # visible text survives, unspoofed


# ---------------------------------------------------------------------------
# 10. split_metric_evasion — group-key normalization + possible_split_metric
# ---------------------------------------------------------------------------
def test_split_metric_evasion(tmp_config: Config):
    """ATTACK: a hostile claim tries to opt OUT of divergence detection by
    varying the free-text group key. (a) A casing/whitespace variant
    ('logic  speed' vs 'Logic Speed') is closed by normalization — the hostile
    claim lands in the SAME group and its divergence reads `contradicted`.
    (b) A near-identical-but-different string ('perf_densityy') does split the
    group, but both singleton groups are flagged possible_split_metric — the
    advisory residue normalization can't close (controlled vocabulary deferred
    with a named trigger)."""
    conn = _conn(tmp_config)
    try:
        src1 = ("IEDM session on Acme X. X reaches 100 GB/s. "
                "X delivers 50 MTr per square mm.")
        _persist_validated(conn, _doc("d1", publisher="IEDM", tier=1,
                                      doc_type="conference_paper"), {
            "entities": [_pe("acme_x", "Acme", "X")],
            "claims": [
                _pc("speed", "d1", "acme_x", metric="Logic Speed", value=100.0,
                    quote="X reaches 100 GB/s."),
                _pc("dens", "d1", "acme_x", metric="perf_density", value=50.0,
                    unit="MTr/mm2", quote="X delivers 50 MTr per square mm.",
                    claim_class="density"),
            ],
        }, src1)

        src2 = ("Vendor Q rebuttal on Acme X. X reaches 300 GB/s in our lab. "
                "X delivers 80 MTr per square mm.")
        _persist_validated(conn, _doc("d2", publisher="Vendor Q", tier=3,
                                      ingest="2026-01-02"), {
            "entities": [_pe("acme_x", "Acme", "X")],
            "claims": [
                _pc("speed", "d2", "acme_x", metric="logic  speed", value=300.0,
                    quote="X reaches 300 GB/s in our lab."),
                _pc("dens", "d2", "acme_x", metric="perf_densityy", value=80.0,
                    unit="MTr/mm2", quote="X delivers 80 MTr per square mm.",
                    claim_class="density"),
            ],
        }, src2)
        conn.commit()
    finally:
        conn.close()

    report = run_analysis(tmp_config)
    assert len(report.assessments) == 3
    by_metric = {a.metric.casefold().replace("  ", " "): a for a in report.assessments}

    # (a) Normalization closed the casing/whitespace evasion: ONE group, and the
    # hostile number is compared against the honest one -> contradicted.
    speed = by_metric["logic speed"]
    assert sorted(speed.members) == ["d1:speed", "d2:speed"]
    assert speed.status == "contradicted"
    assert speed.favored_tier == 1                      # the conference number leads

    # (b) The near-identical variant split the group, but BOTH sides are flagged.
    for name in ("perf_density", "perf_densityy"):
        assert "possible_split_metric" in by_metric[name].flags
        assert by_metric[name].status == "uncorroborated"


# ---------------------------------------------------------------------------
# 11. forget_round_trip — retraction: quarantine + refold erase the hostile
#     doc's claims AND its conflicts from derived state
# ---------------------------------------------------------------------------
def test_forget_round_trip(tmp_config: Config, tmp_path: Path):
    """ATTACK/REMEDY: a hostile document is discovered after ingestion. `forget`
    must retract it completely from derived state — its claims gone, its
    conflict records gone (conflicts describe the CURRENT fold, not an audit
    log), the report clean — while the quarantine directory retains the sidecar
    and extraction artifact as evidence. Runs the FULL pipeline (ingest_file ->
    run_extract with an injected replay extractor -> run_analysis) both sides
    of the retraction."""
    store.init_db(tmp_config)

    honest_pdf = tmp_path / "honest.pdf"
    honest_pdf.write_bytes(_mini_pdf([
        "TSMC N2 Technology Update",
        "TSMC N2 reaches 200 GB/s bandwidth.",
        "N2 uses gate-all-around nanosheet transistors.",
    ]))
    hostile_pdf = tmp_path / "hostile.pdf"
    hostile_pdf.write_bytes(_mini_pdf([
        "Rival Labs teardown of TSMC N2",
        "TSMC N2 uses CFET transistors.",
        "N2 reaches only 90 GB/s bandwidth.",
    ]))
    hostile_sha = hashlib.sha256(hostile_pdf.read_bytes()).hexdigest()

    honest_proposal = {
        "entities": [_pe("tsmc_n2", "TSMC", "N2", entity_type="process_node",
                         node={"transistor_type": "gaa_nanosheet"},
                         cites={"node.transistor_type":
                                _cite("N2 uses gate-all-around nanosheet transistors.")})],
        "claims": [_pc("bw", "honest_n2", "tsmc_n2", metric="mem_bw", value=200.0,
                       quote="TSMC N2 reaches 200 GB/s bandwidth.")],
    }
    hostile_proposal = {
        "entities": [_pe("tsmc_n2", "TSMC", "N2", entity_type="process_node",
                         node={"transistor_type": "cfet"},
                         cites={"node.transistor_type":
                                _cite("TSMC N2 uses CFET transistors.")})],
        "claims": [_pc("bw", "hostile_rival", "tsmc_n2", metric="mem_bw", value=90.0,
                       quote="N2 reaches only 90 GB/s bandwidth.")],
    }

    ingest_file(tmp_config, honest_pdf, doc_id="honest_n2", title="TSMC N2 Update",
                publisher="TSMC", doc_type="foundry_announcement", source_tier=2,
                url="https://example.test/honest_n2", ingest_date="2026-01-01")
    rep = run_extract(tmp_config, extractor=AnthropicExtractor(
        ReplayModelClient(json.dumps(honest_proposal))))
    assert rep.extracted == ["honest_n2"] and rep.errors == []

    ingest_file(tmp_config, hostile_pdf, doc_id="hostile_rival", title="Rival teardown",
                publisher="Rival Labs", doc_type="vendor_whitepaper", source_tier=3,
                url="https://example.test/hostile_rival", ingest_date="2026-01-02")
    rep = run_extract(tmp_config, extractor=AnthropicExtractor(
        ReplayModelClient(json.dumps(hostile_proposal))))
    assert rep.extracted == ["hostile_rival"] and rep.errors == []

    # Pre-retraction: the hostile doc is fully folded in — diverging claim,
    # attribute conflict, disputed entity flagged at the report layer.
    conn = store.connect(tmp_config.paths.db_path)
    try:
        assert set(store.stored_doc_shas(conn)) == {"honest_n2", "hostile_rival"}
        assert _conflict_keys(conn) == [
            ("attribute", "tsmc_n2", "hostile_rival", "node.transistor_type",
             "gaa_nanosheet", "cfet")]
    finally:
        conn.close()
    before = run_analysis(tmp_config)
    [assessment] = before.assessments
    assert assessment.status == "contradicted"
    assert "identity_conflict" in assessment.flags

    # Retract.
    forget_report = forget(tmp_config, "hostile_rival")
    assert sorted(forget_report.quarantined) == sorted(
        [f"{hostile_sha}.meta.json", f"{hostile_sha}.extraction.json"])
    assert forget_report.rebuild.folded == ["honest_n2"]
    assert forget_report.rebuild.errors == []

    # Quarantine holds the evidence — moved, not deleted.
    quarantine = tmp_config.paths.data_dir / "quarantine"
    q_meta = json.loads((quarantine / f"{hostile_sha}.meta.json").read_text())
    assert q_meta["doc_id"] == "hostile_rival"
    q_artifact = json.loads((quarantine / f"{hostile_sha}.extraction.json").read_text())
    assert q_artifact["document"]["doc_id"] == "hostile_rival"
    assert [c["claim_id"] for c in q_artifact["claims"]] == ["bw"]  # what it tried to say

    # Post-retraction derived state: claims gone, conflicts gone, report clean.
    conn = store.connect(tmp_config.paths.db_path)
    try:
        assert list(store.stored_doc_shas(conn)) == ["honest_n2"]
        assert store.get_conflicts(conn) == []          # fold semantics: refusal
        claims = store.get_claims_for_analysis(conn)    # records fell with the doc
        assert [c.claim_id for c in claims] == ["honest_n2:bw"]
    finally:
        conn.close()
    after = run_analysis(tmp_config)
    [assessment] = after.assessments
    assert assessment.members == ["honest_n2:bw"]
    assert assessment.status == "uncorroborated"
    assert "identity_conflict" not in assessment.flags
    assert "conflicts" not in after.to_dict()           # the clean v3 report shape


# ---------------------------------------------------------------------------
# Challenge-4 acceptance guards (gate resolution): the reader's defense.
# These two tests pin the HONEST corpus from the hostile suite's side.
# ---------------------------------------------------------------------------
_ANALYZE_FIXTURE = Path(__file__).parent / "fixtures" / "analyze" / "tsmc_n2_corroboration"
_ANALYZE_SOURCES = ["source_foundry.json", "source_conf.json", "source_vendor.json"]

# Every flag WS-2a introduced. The gate's budget: no honest assessment gains more
# than ONE new flag from this workstream — and we ship at ZERO.
_WS2A_FLAGS = {"single_publisher", "possible_split_metric",
               "possible_slug_collision", "identity_conflict"}


def _load_honest_corpus(tmp_config: Config) -> None:
    conn = _conn(tmp_config)
    try:
        for name in _ANALYZE_SOURCES:
            data = json.loads((_ANALYZE_FIXTURE / name).read_text())
            store.persist_extraction(
                conn, m.Document(**data["document"]),
                [m.Entity(**e) for e in data["entities"]],
                [m.Claim(**c) for c in data["claims"]])
        conn.commit()
    finally:
        conn.close()


def test_honest_corpus_regression(tmp_config: Config):
    """Challenge 4(a): the honest analyze corpus, run through the SAME
    persist -> run_analysis chain the hostile cases use, must reproduce
    expected_analysis.json EXACTLY — verdicts, flags, and the serialized dict
    shape (no conflicts key on a conflict-free store). Any WS-2a floor that
    shifts an honest verdict fails here, not in production."""
    _load_honest_corpus(tmp_config)
    expected = {k: v for k, v in
                json.loads((_ANALYZE_FIXTURE / "expected_analysis.json").read_text()).items()
                if not k.startswith("_")}
    assert run_analysis(tmp_config).to_dict() == expected


def test_flag_budget(tmp_config: Config):
    """Challenge 4(b): the flag budget. No honest assessment may carry ANY of the
    flags WS-2a introduced (single_publisher, possible_split_metric,
    possible_slug_collision, identity_conflict) — the budget is <=1 new flag per
    honest assessment and this workstream ships at zero. A floor that cannot
    meet the budget belongs behind config, not as an unconditional default."""
    _load_honest_corpus(tmp_config)
    report = run_analysis(tmp_config)
    assert report.assessments  # the guard must actually see the corpus
    for assessment in report.assessments:
        leaked = set(assessment.flags) & _WS2A_FLAGS
        assert not leaked, (
            f"honest assessment {assessment.entity_id}/{assessment.metric} "
            f"gained WS-2a flag(s) {sorted(leaked)} — flag budget exceeded")
    assert report.conflicts == [] and report.conflict_counts == {}
