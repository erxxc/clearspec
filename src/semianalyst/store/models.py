"""Canonical pydantic models — generated from schema/extraction_schema_v1.yaml.

These mirror the schema's *nested* shape (claim.comparison, claim.conditions,
entity.node, entity.chip, ...). The relational storage layer (db.py) flattens
them into columns; keeping the models nested keeps the schema's semantics
legible and keeps the store as the only place that knows about SQL.

Design invariants carried from the schema (see CLAUDE.md):
  - The claim is the atomic unit.
  - Relative claims keep the ratio + baseline ref; they are NEVER converted to
    absolutes (Comparison.is_relative / baseline_entity).
  - Every value cites a source span (Citation.quote_span).
  - source_tier is set at the document level and inherited by claims.
"""

from __future__ import annotations

import datetime as dt
import enum

from pydantic import BaseModel, ConfigDict


# --------------------------------------------------------------------------
# Enums (from the schema's `enum` annotations)
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
    footnote = "footnote"  # footnote-sourced claims deserve suspicion


class CorroborationStatus(str, enum.Enum):
    uncorroborated = "uncorroborated"
    corroborated = "corroborated"
    contradicted = "contradicted"


# --------------------------------------------------------------------------
# DOCUMENT
# --------------------------------------------------------------------------
class Document(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    doc_id: str
    title: str
    publisher: str
    doc_type: DocType
    source_tier: SourceTier
    publish_date: dt.date | None = None
    url: str
    file_sha256: str
    ingest_date: dt.date
    extraction_model: str | None = None
    review_status: ReviewStatus = ReviewStatus.unreviewed


# --------------------------------------------------------------------------
# ENTITY (with node / chip sub-attributes)
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
    entity_id: str
    entity_type: EntityType
    vendor: str
    name: str
    aliases: list[str] = []
    node: NodeAttributes | None = None
    chip: ChipAttributes | None = None


# --------------------------------------------------------------------------
# CLAIM (the atomic unit)
# --------------------------------------------------------------------------
class Comparison(BaseModel):
    is_relative: bool = False
    baseline_entity: str | None = None  # what it's compared AGAINST
    baseline_stated: bool = False       # did the doc actually name the baseline?


class Conditions(BaseModel):
    workload: str | None = None
    precision: str | None = None     # FP4/FP8/FP16/INT8 — critical for AI claims
    sparsity: bool | None = None     # the classic 2x inflation lever
    thermal_config: str | None = None
    stated_caveats: list[str] = []   # verbatim footnote text


class Citation(BaseModel):
    page: int | None = None
    quote_span: str                  # exact source text supporting the value
    location_type: LocationType


class Corroboration(BaseModel):
    status: CorroborationStatus = CorroborationStatus.uncorroborated
    related_claim_ids: list[str] = []


class Claim(BaseModel):
    claim_id: str
    doc_id: str
    entity_id: str
    claim_class: ClaimClass
    metric: str
    value: float
    unit: str
    comparison: Comparison = Comparison()
    conditions: Conditions = Conditions()
    completeness: Completeness
    citation: Citation
    corroboration: Corroboration = Corroboration()


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
