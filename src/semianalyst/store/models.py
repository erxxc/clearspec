"""Canonical pydantic models — generated from schema/extraction_schema_v4.yaml
(v2 nested shape + v3 derived corroboration + v4 content bounds & Conflict).

These mirror the schema's *nested* shape (claim.comparison, claim.conditions,
entity.node, entity.chip, entity.attribute_citations, ...). The relational
storage layer (db.py) flattens them into columns; keeping the models nested
keeps the schema's semantics legible and confines SQL knowledge to the store.

Design invariants carried from the schema (see CLAUDE.md):
  - The claim is the atomic unit.
  - Relative claims keep the ratio + baseline ref; they are NEVER absolutized.
  - Every claim value AND every non-null entity attribute cites a source span
    (Citation / attribute_citations) — grounding is code-enforced (v2).
  - source_tier is set at the document level and inherited by claims.
  - v4 content bounds: every model- or network-influenced string is length- and
    charset-bounded here (the shape guard); migration 0004 mirrors the LENGTH
    bounds as SQLite CHECKs (the durable flood guard). Verbatim source text
    (quote_span, stated_caveats) is length-bounded only — it may legitimately
    contain newlines the no-control-chars pattern would reject.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# --------------------------------------------------------------------------
# v4 bounded string types (schema `bounds` block). _NO_CTRL rejects C0/DEL —
# terminal-escape bytes never enter the store, independent of display sanitizing.
# --------------------------------------------------------------------------
_NO_CTRL = r"^[^\x00-\x1f\x7f]*$"
SlugId80 = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,80}$")]
DocId120 = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")]
ClaimId200 = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Text16 = Annotated[str, StringConstraints(max_length=16, pattern=_NO_CTRL)]
Text80 = Annotated[str, StringConstraints(max_length=80, pattern=_NO_CTRL)]
Text120 = Annotated[str, StringConstraints(max_length=120, pattern=_NO_CTRL)]
Text200 = Annotated[str, StringConstraints(max_length=200, pattern=_NO_CTRL)]
Text300 = Annotated[str, StringConstraints(max_length=300, pattern=_NO_CTRL)]
Text2000 = Annotated[str, StringConstraints(max_length=2000, pattern=_NO_CTRL)]
Span2000 = Annotated[str, StringConstraints(max_length=2000)]   # verbatim source text
Caveat500 = Annotated[str, StringConstraints(max_length=500)]   # verbatim footnotes


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class DocType(str, enum.Enum):
    foundry_announcement = "foundry_announcement"
    conference_paper = "conference_paper"
    vendor_whitepaper = "vendor_whitepaper"
    product_brief = "product_brief"


class SourceTier(enum.IntEnum):
    # conf=1, foundry=2, vendor=3 — lower tier == higher trust.
    conference = 1
    foundry = 2
    vendor = 3


class ReviewStatus(str, enum.Enum):
    unreviewed = "unreviewed"
    human_verified = "human_verified"
    disputed = "disputed"


class EntityType(str, enum.Enum):
    process_node = "process_node"
    chip = "chip"
    chiplet = "chiplet"
    package = "package"
    ip_block = "ip_block"


class TransistorType(str, enum.Enum):
    finfet = "finfet"
    gaa_nanosheet = "gaa_nanosheet"
    cfet = "cfet"


class ClaimClass(str, enum.Enum):
    performance = "performance"
    efficiency = "efficiency"
    density = "density"
    power = "power"
    yield_ = "yield"
    cost = "cost"
    availability = "availability"


class Completeness(str, enum.Enum):
    complete = "complete"
    missing_baseline = "missing_baseline"
    missing_conditions = "missing_conditions"
    marketing_only = "marketing_only"


class LocationType(str, enum.Enum):
    body = "body"
    table = "table"
    figure = "figure"
    footnote = "footnote"     # footnote-sourced claims deserve suspicion
    unknown = "unknown"       # v2: location undetermined (flat text) — fail-safe


class CorroborationStatus(str, enum.Enum):
    uncorroborated = "uncorroborated"
    corroborated = "corroborated"
    weakly_corroborated = "weakly_corroborated"  # v3: >=2 agree within tolerance, <2 non-suspect
    contradicted = "contradicted"


# --------------------------------------------------------------------------
# CITATION — a grounded source span. Reused by claims AND entity attributes (v2).
# --------------------------------------------------------------------------
class Citation(BaseModel):
    page: int | None = None
    quote_span: Span2000             # exact source text supporting the value
    location_type: LocationType


# --------------------------------------------------------------------------
# DOCUMENT
# --------------------------------------------------------------------------
class Document(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    doc_id: DocId120
    title: Text300
    publisher: Text120
    doc_type: DocType
    source_tier: SourceTier
    publish_date: dt.date | None = None
    url: Text2000
    file_sha256: Sha256Hex
    ingest_date: dt.date
    extraction_model: Text200 | None = None
    review_status: ReviewStatus = ReviewStatus.unreviewed


# --------------------------------------------------------------------------
# ENTITY (with node / chip sub-attributes + per-attribute grounding)
# --------------------------------------------------------------------------
class NodeAttributes(BaseModel):
    density_mtx_mm2: float | None = None
    transistor_type: TransistorType | None = None
    backside_power: bool | None = None
    hvm_date_claimed: dt.date | None = None
    hvm_date_actual: dt.date | None = None  # backfilled later — slip tracking


class ChipAttributes(BaseModel):
    process_node_ref: str | None = None  # FK to the node entity — the join key
    transistor_count_b: float | None = None
    die_size_mm2: float | None = None
    package_type: str | None = None
    memory_type: str | None = None
    memory_bw_gbps: float | None = None
    tdp_w: float | None = None
    launch_date: dt.date | None = None


class Entity(BaseModel):
    entity_id: SlugId80
    entity_type: EntityType
    vendor: Text80
    name: Text80
    aliases: list[Text80] = Field(default=[], max_length=16)
    node: NodeAttributes | None = None
    chip: ChipAttributes | None = None
    # v2: attribute-path -> Citation. Every non-null node/chip attribute (except
    # hvm_date_actual, which is backfilled) must have a grounded citation here.
    attribute_citations: dict[str, Citation] = {}


# --------------------------------------------------------------------------
# CLAIM (the atomic unit)
# --------------------------------------------------------------------------
class Comparison(BaseModel):
    is_relative: bool = False
    baseline_entity: SlugId80 | None = None  # what it's compared AGAINST
    baseline_stated: bool = False       # did the doc actually name the baseline?


class Conditions(BaseModel):
    workload: Text120 | None = None
    precision: Text120 | None = None    # FP4/FP8/FP16/INT8 — critical for AI claims
    sparsity: bool | None = None        # the classic 2x inflation lever
    thermal_config: Text120 | None = None
    stated_caveats: list[Caveat500] = Field(default=[], max_length=16)  # verbatim footnote text


class Corroboration(BaseModel):
    # DERIVED, NOT PERSISTED (v3 / decision B2). The corroboration verdict is a
    # per-GROUP fact analyze computes derive-on-read (see analyze/corroborate.py →
    # AnalysisReport); it is NOT stored on the claim row. This field carries a
    # neutral default on the in-memory claim so extraction output has a stable
    # shape, but `store.insert_claim` never writes it and no row-to-claim reader
    # reads it back. Do not add a persisted per-row verdict without settling the
    # per-group-fact-in-a-per-row-home question (CLAUDE.md, analyze resolution).
    status: CorroborationStatus = CorroborationStatus.uncorroborated
    related_claim_ids: list[str] = []


class Claim(BaseModel):
    claim_id: ClaimId200
    doc_id: DocId120
    entity_id: SlugId80
    claim_class: ClaimClass
    metric: Text120
    value: float
    unit: Text16
    comparison: Comparison = Comparison()
    conditions: Conditions = Conditions()
    completeness: Completeness
    citation: Citation
    corroboration: Corroboration = Corroboration()


# --------------------------------------------------------------------------
# CONFLICT (v4) — persisted reconciliation-refusal record.
# --------------------------------------------------------------------------
class ConflictKind(str, enum.Enum):
    identity_field = "identity_field"    # later doc differs on frozen vendor/name/entity_type
    attribute = "attribute"              # later doc differs on a non-null node/chip attribute (K1/K2)
    alias_collision = "alias_collision"  # incoming alias equals another entity's name/alias (G3)


class Conflict(BaseModel):
    """What a later document tried to write and the store refused to apply
    (never-overwrite is universal). Persisted because the offered value has no
    other home — reconcile drops it at refusal time (2026-08-18 gate, Conflict 1).
    offered_value/stored_value are ADVERSARY-AUTHORED text meant for a human
    reader: bounded here and in DDL, and every display site must route them
    through the hardened sanitizer (ANSI/OSC + Unicode Cf)."""

    conflict_id: int | None = None       # assigned by the store on insert
    kind: ConflictKind
    entity_id: SlugId80
    doc_id: DocId120                     # the offending document
    field: Text80                        # identity field name, attribute path, or 'alias'
    stored_value: Text120 | None = None  # null for alias_collision
    offered_value: Text120
    created_at: str                      # ISO timestamp, store-stamped


# --------------------------------------------------------------------------
# MACRO_SNAPSHOT (Phase 2 — thin EDGAR layer)
# --------------------------------------------------------------------------
class MacroSnapshot(BaseModel):
    vendor: str
    period: str                      # e.g. FY2026-Q2
    capex_usd_m: float | None = None
    segment_revenue: dict[str, float] = {}
    inventory_days: float | None = None
    rd_spend_usd_m: float | None = None
    filing_url: str | None = None
