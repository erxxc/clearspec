"""Validation + normalization — the LLM proposal is a PROPOSAL, not truth."""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from ..store import models
from ..textnorm import CTRL_CLASS, fold
from .pdf import is_grounded

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when a proposal is structurally unusable (unparseable / refusal)."""


class ExtractionResult(BaseModel):
    entities: list[models.Entity] = []
    claims: list[models.Claim] = []


@dataclass(frozen=True)
class Rejection:
    kind: str
    target: str
    reason: str


RATIO_UNITS = {"x", "X", "×"}
RELATIVE_OK_UNITS = RATIO_UNITS | {"%"}

_UNIT_CONV: dict[str, tuple[float, str]] = {
    "TB/s": (1000.0, "GB/s"), "GB/s": (1.0, "GB/s"), "MB/s": (0.001, "GB/s"),
    "kW": (1000.0, "W"), "W": (1.0, "W"), "mW": (0.001, "W"),
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTHS.update({name[:3]: num for name, num in dict(_MONTHS).items()})

GROUNDABLE: dict[str, list[str]] = {
    "node": ["density_mtx_mm2", "transistor_type", "backside_power", "hvm_date_claimed"],
    "chip": ["transistor_count_b", "die_size_mm2", "package_type", "memory_type",
             "memory_bw_gbps", "tdp_w", "launch_date"],
    "package": ["ecosystem", "name", "purl", "cpe"],
    "product": ["ecosystem", "name", "purl", "cpe"],
    "cve": ["cwe"],
}
# v5 identity citation slots — optional; presence-grounding remains the floor
IDENTITY_CITE_PATHS = {"vendor", "name", "entity_type", "cve.cve_id"}
_VALID_PATHS = {f"{sub}.{f}" for sub, fields in GROUNDABLE.items() for f in fields} | IDENTITY_CITE_PATHS

_CTRL = re.compile(CTRL_CLASS)
_SPARSE_VOCAB_V1 = re.compile(r"(?i)\b(spars\w*|prun\w*|2:4)\b")


def _safe(text: str) -> str:
    return _CTRL.sub(" ", text)[:120]


def _grounded_ci(text: str, source_text: str) -> bool:
    return is_grounded(text.casefold(), source_text.casefold())


def normalize_date_str(value: str) -> str:
    s = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    m = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-01"
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", s)
    if m and m.group(1).lower() in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}-01"
    if re.fullmatch(r"\d{4}", s):
        return f"{s}-01-01"
    return s


def normalize_unit(value: float, unit: str) -> tuple[float, str]:
    if unit in _UNIT_CONV:
        factor, canonical = _UNIT_CONV[unit]
        return value * factor, canonical
    return value, unit


def _pre_normalize(proposal: dict) -> dict:
    p = copy.deepcopy(proposal)
    for ent in p.get("entities", []):
        for sub in ("node", "chip"):
            attrs = ent.get(sub)
            if isinstance(attrs, dict):
                for date_field in ("hvm_date_claimed", "hvm_date_actual", "launch_date"):
                    if attrs.get(date_field) is not None:
                        attrs[date_field] = normalize_date_str(str(attrs[date_field]))
    for claim in p.get("claims", []):
        if claim.get("value") is not None and claim.get("unit") is not None:
            claim["value"], claim["unit"] = normalize_unit(claim["value"], claim["unit"])
    return p


def _force_unknown(citation: models.Citation) -> None:
    citation.location_type = models.LocationType.unknown


def validate_proposal(
    proposal: dict, source_text: str
) -> tuple[ExtractionResult, list[Rejection]]:
    normalized = _pre_normalize(proposal)
    rejections: list[Rejection] = []

    entities: list[models.Entity] = []
    for raw_entity in normalized.get("entities", []):
        try:
            entities.append(models.Entity.model_validate(raw_entity))
        except ValidationError as exc:
            eid = raw_entity.get("entity_id", "?") if isinstance(raw_entity, dict) else "?"
            rejections.append(Rejection("entity", str(eid),
                                        f"shape invalid at {[e['loc'] for e in exc.errors()]}"))
    claims: list[models.Claim] = []
    for raw_claim in normalized.get("claims", []):
        try:
            claims.append(models.Claim.model_validate(raw_claim))
        except ValidationError as exc:
            cid = raw_claim.get("claim_id", "?") if isinstance(raw_claim, dict) else "?"
            rejections.append(Rejection("claim", str(cid),
                                        f"shape invalid at {[e['loc'] for e in exc.errors()]}"))

    kept_entities: list[models.Entity] = []
    seen: dict[tuple[str, str], models.Entity] = {}
    for ent in entities:
        if not _grounded_ci(ent.name, source_text):
            rejections.append(Rejection("entity", ent.entity_id,
                                        "name not found in source"))
            continue
        if not _grounded_ci(ent.vendor, source_text):
            rejections.append(Rejection("entity", ent.entity_id,
                                        "vendor not found in source"))
            continue
        if ent.cve is not None and not _grounded_ci(ent.cve.cve_id, source_text):
            rejections.append(Rejection("entity", ent.entity_id,
                                        "cve_id not found in source"))
            continue
        kept_aliases: list[str] = []
        for idx, alias in enumerate(ent.aliases):
            if _grounded_ci(alias, source_text):
                kept_aliases.append(alias)
            else:
                rejections.append(Rejection("entity_alias", f"{ent.entity_id}:{idx}",
                                            "alias not found in source"))
        ent.aliases = kept_aliases
        for sub, fields in GROUNDABLE.items():
            attrs = getattr(ent, sub)
            if attrs is None:
                continue
            for field in fields:
                if getattr(attrs, field) is None:
                    continue
                path = f"{sub}.{field}"
                cite = ent.attribute_citations.get(path)
                if cite is None or not is_grounded(cite.quote_span, source_text):
                    setattr(attrs, field, None)
                    ent.attribute_citations.pop(path, None)
                    rejections.append(Rejection("entity_attribute", f"{ent.entity_id}:{path}",
                        "missing grounding citation" if cite is None
                        else "quote_span not found in source"))
        for path in list(ent.attribute_citations):
            if path not in _VALID_PATHS:
                ent.attribute_citations.pop(path)
                rejections.append(Rejection("entity_attribute", f"{ent.entity_id}:{path}",
                                            "citation for an unknown or exempt attribute path"))
            else:
                _force_unknown(ent.attribute_citations[path])

        key = (fold(ent.vendor), fold(ent.name))
        if key in seen:
            base = seen[key]
            for alias in ent.aliases:
                if alias not in base.aliases:
                    base.aliases.append(alias)
            for sub, fields in GROUNDABLE.items():
                dup_attrs = getattr(ent, sub)
                if dup_attrs is None:
                    continue
                base_attrs = getattr(base, sub)
                if base_attrs is None:
                    setattr(base, sub, dup_attrs)
                else:
                    for field in fields:
                        if getattr(base_attrs, field) is None and getattr(dup_attrs, field) is not None:
                            setattr(base_attrs, field, getattr(dup_attrs, field))
            for path, cite in ent.attribute_citations.items():
                base.attribute_citations.setdefault(path, cite)
            rejections.append(Rejection("entity_merge", ent.entity_id,
                                        f"merged duplicate into {base.entity_id}"))
        else:
            seen[key] = ent
            kept_entities.append(ent)

    for ent in kept_entities:
        if ent.name not in ent.aliases:
            ent.aliases.insert(0, ent.name)

    vendor_of = {e.entity_id: e.vendor for e in kept_entities}
    kept_entity_ids = set(vendor_of)

    kept_claims: list[models.Claim] = []
    for claim in claims:
        if claim.entity_id not in kept_entity_ids:
            rejections.append(Rejection("claim", claim.claim_id,
                                        "references an entity absent from this document's proposal"))
            continue
        if not is_grounded(claim.citation.quote_span, source_text):
            rejections.append(Rejection("claim", claim.claim_id,
                                        "quote_span not found in source"))
            continue
        if claim.conditions.sparsity is not True and _SPARSE_VOCAB_V1.search(claim.citation.quote_span):
            claim.conditions.sparsity = True
            rejections.append(Rejection("claim_condition", claim.claim_id,
                                        "sparsity forced true: sparse-benchmark vocabulary in quote_span"))
        if (claim.unit is not None and claim.comparison.is_relative
                and claim.unit not in RELATIVE_OK_UNITS):
            rejections.append(Rejection("claim", claim.claim_id,
                                        "relative claim carries a non-ratio/percent (absolutized) unit"))
            continue
        if claim.unit is not None and claim.unit in RATIO_UNITS and not claim.comparison.is_relative:
            rejections.append(Rejection("claim", claim.claim_id,
                                        "ratio unit but is_relative not set (undeclared relativity)"))
            continue
        if (claim.comparison.is_relative and claim.comparison.baseline_entity is None
                and claim.completeness == models.Completeness.complete):
            claim.completeness = models.Completeness.missing_baseline
        entity_vendor = vendor_of.get(claim.entity_id)
        baseline_vendor = vendor_of.get(claim.comparison.baseline_entity)
        if (claim.conditions.sparsity is True
                and claim.comparison.is_relative
                and entity_vendor is not None
                and baseline_vendor is not None
                and entity_vendor != baseline_vendor):
            claim.completeness = models.Completeness.marketing_only
        _force_unknown(claim.citation)
        kept_claims.append(claim)

    return ExtractionResult(entities=kept_entities, claims=kept_claims), rejections


def build_result(proposal: dict, source_text: str) -> ExtractionResult:
    result, rejections = validate_proposal(proposal, source_text)
    for rej in rejections:
        logger.warning("validate %s [%s]: %s", rej.kind, _safe(rej.target), rej.reason)
    return result
