"""Canonical pydantic models — v4 foundry pack + v5 advisory pack (GEI-7).

v4 yaml is unedited. v5 (schema/extraction_schema_v5.yaml) adds advisory
entity/claim types, structured version intervals, and claim-level
source_record_kind. Foundry enums and node/chip attributes remain legal so
the v4 path does not break.

Never auto-resolve: no model helper picks a winning source_record_kind.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_serializer, model_validator

# --------------------------------------------------------------------------
# v4 bounded string types (schema `bounds` block). _NO_CTRL rejects C0/DEL.
# --------------------------------------------------------------------------
_NO_CTRL = r"^[^\x00-\x1f\x7f]*$"
SlugId80 = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,80}$")]
DocId120 = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")]
ClaimId200 = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
CveId = Annotated[str, StringConstraints(pattern=r"^CVE-[0-9]{4}-[0-9]{4,}$", max_length=32)]
CweId = Annotated[str, StringConstraints(pattern=r"^CWE-[0-9]{1,8}$", max_length=32)]
Text16 = Annotated[str, StringConstraints(max_length=16, pattern=_NO_CTRL)]
Text32 = Annotated[str, StringConstraints(max_length=32, pattern=_NO_CTRL)]
Text40 = Annotated[str, StringConstraints(max_length=40, pattern=_NO_CTRL)]
Text80 = Annotated[str, StringConstraints(max_length=80, pattern=_NO_CTRL)]
Text120 = Annotated[str, StringConstraints(max_length=120, pattern=_NO_CTRL)]
Text200 = Annotated[str, StringConstraints(max_length=200, pattern=_NO_CTRL)]
Text256 = Annotated[str, StringConstraints(max_length=256, pattern=_NO_CTRL)]
Text300 = Annotated[str, StringConstraints(max_length=300, pattern=_NO_CTRL)]
Text512 = Annotated[str, StringConstraints(max_length=512, pattern=_NO_CTRL)]
Text2000 = Annotated[str, StringConstraints(max_length=2000, pattern=_NO_CTRL)]
Span2000 = Annotated[str, StringConstraints(max_length=2000)]
Caveat500 = Annotated[str, StringConstraints(max_length=500)]


class DocType(str, enum.Enum):
    foundry_announcement = "foundry_announcement"
    conference_paper = "conference_paper"
    vendor_whitepaper = "vendor_whitepaper"
    product_brief = "product_brief"
    # v5 advisory pack
    nvd_record = "nvd_record"
    ghsa = "ghsa"
    vendor_advisory = "vendor_advisory"
    cisa_kev = "cisa_kev"
    researcher_writeup = "researcher_writeup"


class SourceTier(enum.IntEnum):
    # foundry document-level 1/2/3 — NOT the advisory claim-class rank
    conference = 1
    foundry = 2
    vendor = 3


class SourceRecordKind(str, enum.Enum):
    """Claim-level source identity (v5). Distinguishes NVD CNA from NVD CPE
    even when they share a URL. Ranking is documented in the yaml and is
    NEVER applied as a resolver."""
    nvd_cna = "nvd_cna"
    nvd_cpe = "nvd_cpe"
    nvd_catalog = "nvd_catalog"
    ghsa_reviewed = "ghsa_reviewed"
    ghsa_unreviewed = "ghsa_unreviewed"
    vendor_json = "vendor_json"
    vendor_cna = "vendor_cna"
    vendor_acknowledgement = "vendor_acknowledgement"
    vendor_cvss = "vendor_cvss"
    cisa_kev = "cisa_kev"
    nvd_exploit_field = "nvd_exploit_field"
    ghsa_exploit_field = "ghsa_exploit_field"
    peer_research = "peer_research"


class ReviewStatus(str, enum.Enum):
    unreviewed = "unreviewed"
    human_verified = "human_verified"
    disputed = "disputed"


class EntityType(str, enum.Enum):
    process_node = "process_node"
    chip = "chip"
    chiplet = "chiplet"
    package = "package"          # foundry: semiconductor package; advisory: software package
    ip_block = "ip_block"
    cve = "cve"
    product = "product"
    advisory = "advisory"


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
    affected_range = "affected_range"
    patched_in = "patched_in"
    cvss = "cvss"
    exploit_status = "exploit_status"
    workaround = "workaround"


FOUNDRY_CLAIM_CLASSES = frozenset({
    ClaimClass.performance, ClaimClass.efficiency, ClaimClass.density,
    ClaimClass.power, ClaimClass.yield_, ClaimClass.cost, ClaimClass.availability,
})
ADVISORY_CLAIM_CLASSES = frozenset({
    ClaimClass.affected_range, ClaimClass.patched_in, ClaimClass.cvss,
    ClaimClass.exploit_status, ClaimClass.workaround,
})
RANGE_CLAIM_CLASSES = frozenset({ClaimClass.affected_range, ClaimClass.patched_in})


class Completeness(str, enum.Enum):
    complete = "complete"
    missing_baseline = "missing_baseline"
    missing_conditions = "missing_conditions"
    marketing_only = "marketing_only"
    missing_range = "missing_range"
    missing_product = "missing_product"


class LocationType(str, enum.Enum):
    body = "body"
    table = "table"
    figure = "figure"
    footnote = "footnote"
    unknown = "unknown"


class CorroborationStatus(str, enum.Enum):
    uncorroborated = "uncorroborated"
    corroborated = "corroborated"
    weakly_corroborated = "weakly_corroborated"
    contradicted = "contradicted"


class ExploitStatus(str, enum.Enum):
    known_exploited = "known_exploited"
    no_known_exploit = "no_known_exploit"
    disputed = "disputed"


class Citation(BaseModel):
    page: int | None = None
    quote_span: Span2000
    location_type: LocationType


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


class NodeAttributes(BaseModel):
    density_mtx_mm2: float | None = None
    transistor_type: TransistorType | None = None
    backside_power: bool | None = None
    hvm_date_claimed: dt.date | None = None
    hvm_date_actual: dt.date | None = None


class ChipAttributes(BaseModel):
    process_node_ref: SlugId80 | None = None
    transistor_count_b: float | None = None
    die_size_mm2: float | None = None
    package_type: Text120 | None = None
    memory_type: Text120 | None = None
    memory_bw_gbps: float | None = None
    tdp_w: float | None = None
    launch_date: dt.date | None = None


class PackageAttributes(BaseModel):
    """Software-package attrs (v5). All citation-grounded when non-null."""
    ecosystem: Text80
    name: Text80
    purl: Text512 | None = None
    cpe: Text256 | None = None


class ProductAttributes(BaseModel):
    """Product attrs (v5). ecosystem nullable (OpenSSH / PAN-OS have no eco)."""
    name: Text80
    ecosystem: Text80 | None = None
    purl: Text512 | None = None
    cpe: Text256 | None = None


class CveAttributes(BaseModel):
    cve_id: CveId
    cwe: CweId | None = None


class Entity(BaseModel):
    entity_id: SlugId80
    entity_type: EntityType
    vendor: Text80
    name: Text80
    aliases: list[Text80] = Field(default=[], max_length=16)
    node: NodeAttributes | None = None
    chip: ChipAttributes | None = None
    package: PackageAttributes | None = None
    product: ProductAttributes | None = None
    cve: CveAttributes | None = None
    attribute_citations: dict[str, Citation] = {}

    @model_serializer(mode="wrap")
    def _omit_null_v5_attrs(self, handler):
        data = handler(self)
        for key in ("package", "product", "cve"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _advisory_identity(self) -> "Entity":
        if self.entity_type == EntityType.cve and self.cve is None:
            raise ValueError("cve entities require cve.cve_id (identity)")
        if self.entity_type == EntityType.product and self.product is None:
            raise ValueError("product entities require product attributes")
        return self


class Comparison(BaseModel):
    is_relative: bool = False
    baseline_entity: SlugId80 | None = None
    baseline_stated: bool = False


class Conditions(BaseModel):
    workload: Text120 | None = None
    precision: Text120 | None = None
    sparsity: bool | None = None
    thermal_config: Text120 | None = None
    stated_caveats: list[Caveat500] = Field(default=[], max_length=16)


class Corroboration(BaseModel):
    status: CorroborationStatus = CorroborationStatus.uncorroborated
    related_claim_ids: list[str] = []


class VersionBound(BaseModel):
    """One end of a structured version interval. quote_span is NOT this."""
    version: Text80
    inclusive: bool


class VersionInterval(BaseModel):
    start: VersionBound | None = None  # None = unbounded below
    end: VersionBound | None = None    # None = unbounded above

    @model_validator(mode="after")
    def _not_empty(self) -> "VersionInterval":
        if self.start is None and self.end is None:
            raise ValueError("version interval must have a start and/or end bound")
        return self


class VersionRange(BaseModel):
    """A set of structured intervals. Not a display string."""
    intervals: list[VersionInterval] = Field(min_length=1, max_length=32)


class Claim(BaseModel):
    claim_id: ClaimId200
    doc_id: DocId120
    entity_id: SlugId80
    claim_class: ClaimClass
    metric: Text120
    value: float | None = None
    unit: Text16 | None = None
    comparison: Comparison = Comparison()
    conditions: Conditions = Conditions()
    completeness: Completeness
    citation: Citation
    corroboration: Corroboration = Corroboration()
    # v5 advisory fields
    cve_id: CveId | None = None
    version_range: VersionRange | None = None
    exploit_status: ExploitStatus | None = None
    workaround_text: Caveat500 | None = None
    # Ingest-attested (sidecar / CNA-vs-CPE parser), never model-emitted.
    # validate.py strips proposal values; SQL CHECK requires it for advisory
    # classes at persist. Pydantic does not require it — the model must not
    # be the source of this field.
    source_record_kind: SourceRecordKind | None = None

    @model_serializer(mode="wrap")
    def _omit_null_v5_fields(self, handler):
        data = handler(self)
        for key in ("cve_id", "version_range", "exploit_status",
                    "workaround_text", "source_record_kind"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _payload_matches_class(self) -> "Claim":
        cls = self.claim_class
        if cls in FOUNDRY_CLAIM_CLASSES:
            if self.value is None or self.unit is None:
                raise ValueError("foundry claims require numeric value and unit")
            if self.version_range is not None:
                raise ValueError("foundry claims do not carry version_range")
            return self
        if cls in RANGE_CLAIM_CLASSES:
            if self.version_range is None:
                raise ValueError(
                    "affected_range/patched_in require a structured version_range; "
                    "quote_span is the verbatim string, not the stored range"
                )
            return self
        if cls == ClaimClass.cvss:
            if self.value is None:
                raise ValueError("cvss claims require a numeric value")
            return self
        if cls == ClaimClass.exploit_status:
            if self.exploit_status is None:
                raise ValueError("exploit_status claims require exploit_status")
            return self
        if cls == ClaimClass.workaround:
            if self.workaround_text is None:
                raise ValueError("workaround claims require workaround_text")
            return self
        return self

    def advisory_group_key(self) -> tuple[str, str, str]:
        """Represent the GEI-9 grouping key. Does not compare or resolve."""
        return (self.cve_id or "", self.entity_id, self.claim_class.value)


class ConflictKind(str, enum.Enum):
    identity_field = "identity_field"
    attribute = "attribute"
    alias_collision = "alias_collision"
    alias_overflow = "alias_overflow"


class Conflict(BaseModel):
    conflict_id: int | None = None
    kind: ConflictKind
    entity_id: SlugId80
    doc_id: DocId120
    field: Text80
    stored_value: Text120 | None = None
    offered_value: Text120
    created_at: str


class MacroSnapshot(BaseModel):
    vendor: str
    period: str
    capex_usd_m: float | None = None
    segment_revenue: dict[str, float] = {}
    inventory_days: float | None = None
    rd_spend_usd_m: float | None = None
    filing_url: str | None = None
