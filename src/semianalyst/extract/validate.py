"""Validation + normalization — the LLM proposal is a PROPOSAL, not truth.

`build_result` turns a raw model proposal (dict of entities + claims) into a
grounded `ExtractionResult`, enforcing the schema's integrity rules in code:

  1. Shape       — per-item pydantic validation; a malformed item is dropped
                   (with a rejection), never fatal to the whole extraction.
  2. Normalize   — month-precision dates -> first-of-month; units -> canonical.
  3. Ground      — every claim quote_span AND every entity attribute_citation
                   quote_span must appear in the source text, else the claim is
                   dropped / the attribute is nulled. Identity is grounded too
                   (2026-08-18 gate): an entity whose name or vendor never
                   appears in the source is dropped, and an ungrounded alias is
                   dropped from its list (G1) — both case-insensitive presence
                   floors (existence, not verbatim-quote proof).
  4. Provenance  — a claim must be about an entity extracted from THIS document
                   (claim.entity_id present in the proposal), else it's dropped.
  5. Integrity   — a relative claim must use a ratio/percent unit (never an
                   absolute one); a pure-ratio unit (x) requires is_relative; a
                   relative claim with no baseline is downgraded to
                   missing_baseline (the model's `completeness` is not trusted);
                   sparsity + cross-vendor comparison -> marketing_only;
                   sparse-benchmark vocabulary in the grounded quote_span
                   force-sets sparsity=True (self-declaration is not trusted in
                   the non-suspect direction — fails toward suspect).
  6. Fail-safe   — flat-text extraction can't place a quote, so every citation's
                   location_type is forced to `unknown` (never `body`).
  7. Dedup       — one entity per (vendor, name), both case-folded; aliases,
                   attribute VALUES, and their citations are all reconciled into
                   the surviving entity.
                   The canonical `name` is always pinned into `aliases` — it is a
                   surface form of the entity, and models repeat it inconsistently.

Rejections carry only a kind, a model-supplied identifier/path (sanitized before
logging), and a fixed reason string — never raw model text values, which under
injection could carry a hostile string. `validate_proposal` returns them for
tests; `build_result` returns just the cleaned result.

NOTE (store-workstream prerequisite): validate enforces a per-DOCUMENT trust
boundary only. Cross-document entity reconciliation lives in store/; persistence
must not ship until `INSERT OR REPLACE` there is replaced with real reconciliation
(see CLAUDE.md) — otherwise a later document silently overwrites an entity an
earlier one created.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from ..store import models
from .pdf import is_grounded

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when a proposal is structurally unusable (unparseable / refusal)."""


class ExtractionResult(BaseModel):
    """What an Extractor returns for one document (matches the golden fixture)."""

    entities: list[models.Entity] = []
    claims: list[models.Claim] = []


@dataclass(frozen=True)
class Rejection:
    kind: str      # "claim" | "claim_condition" | "entity" | "entity_alias" |
                   #   "entity_attribute" | "entity_merge"
    target: str    # id / path (model-supplied) — sanitized before logging
    reason: str


# --------------------------------------------------------------------------
# Normalization tables
# --------------------------------------------------------------------------
RATIO_UNITS = {"x", "X", "×"}                 # pure ratios — inherently comparative
RELATIVE_OK_UNITS = RATIO_UNITS | {"%"}       # a relative claim may be a ratio or a percent

# (factor, canonical_unit) — bandwidth->GB/s, power->W. Extend as real docs need.
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

# Node/chip attributes that must be grounded when non-null. hvm_date_actual is
# exempt (backfilled, not extracted); process_node_ref is a structural join key.
GROUNDABLE: dict[str, list[str]] = {
    "node": ["density_mtx_mm2", "transistor_type", "backside_power", "hvm_date_claimed"],
    "chip": ["transistor_count_b", "die_size_mm2", "package_type", "memory_type",
             "memory_bw_gbps", "tdp_w", "launch_date"],
}
_VALID_PATHS = {f"{sub}.{f}" for sub, fields in GROUNDABLE.items() for f in fields}

_CTRL = re.compile(r"[\x00-\x1f\x7f]")

# Sparse-benchmark vocabulary (v1, 2026-08-18 gate — injection F1, a live bug):
# conditions.sparsity is model-proposed, and a hostile document can steer the
# model to omit or deny the disclosure. The quote_span is already grounded, so
# its own vocabulary overrides the model's self-declaration — presence of any
# term force-sets sparsity=True. Fails toward suspect, never toward clean (the
# same fail-safe direction as location_type). `2:4` is the structured-sparsity
# ratio notation; \b keeps it from matching inside clock times like "12:45".
_SPARSE_VOCAB_V1 = re.compile(r"(?i)\b(spars\w*|prun\w*|2:4)\b")


def _safe(text: str) -> str:
    """Sanitize a model-controlled id/path before it enters a log line."""
    return _CTRL.sub(" ", text)[:120]


def _grounded_ci(text: str, source_text: str) -> bool:
    """Case-insensitive `is_grounded` — for identity SURFACE FORMS only (name,
    vendor, aliases), whose casing varies legitimately ("TSMC"/"Tsmc", same as
    the dedup key). Quote spans stay case-sensitive: they claim to be verbatim
    quotes; identity presence is an existence floor, not a quote."""
    return is_grounded(text.lower(), source_text.lower())


def normalize_date_str(value: str) -> str:
    """ISO passes through; month-precision -> first-of-month; year -> first-of-year.
    Anything unrecognized is returned unchanged (pydantic rejects it downstream)."""
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
    # Flat text can't distinguish body/table/footnote — fail safe (never `body`).
    citation.location_type = models.LocationType.unknown


def validate_proposal(
    proposal: dict, source_text: str
) -> tuple[ExtractionResult, list[Rejection]]:
    normalized = _pre_normalize(proposal)
    rejections: list[Rejection] = []

    # Per-item shape validation: a single malformed field drops THAT item (with a
    # rejection), never the whole extraction. Real models occasionally emit an
    # off-type value (e.g. sparsity "enabled" instead of true).
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

    # --- entities: presence-ground identity, ground attributes + aliases, dedup ---
    kept_entities: list[models.Entity] = []
    seen: dict[tuple[str, str], models.Entity] = {}
    for ent in entities:
        # Identity presence-grounding (2026-08-18 gate — the "identity citation
        # slots" residual): name/vendor have no attribute_citations home, so a
        # hostile proposal could otherwise mint an entity for a vendor the
        # document never mentions (the first-hostile-writer identity plant).
        # Presence in the source text is the cheap floor — full citation slots
        # are deferred to schema v5. Fail-soft: drops THIS entity (its claims
        # cascade via the kept-entity check below), never the extraction.
        if not _grounded_ci(ent.name, source_text):
            rejections.append(Rejection("entity", ent.entity_id,
                                        "name not found in source"))
            continue
        if not _grounded_ci(ent.vendor, source_text):
            rejections.append(Rejection("entity", ent.entity_id,
                                        "vendor not found in source"))
            continue
        # G1 — alias grounding (2026-08-18 gate): every model-proposed alias
        # must appear in THIS document's text, or a hostile doc could plant a
        # competitor's product name as an alias and capture its claims at
        # store-reconciliation time. Runs BEFORE dedup so merged entities union
        # only grounded aliases. The rejection target is the alias's list index,
        # never the alias string itself (a rejection carries no raw model text).
        kept_aliases: list[str] = []
        for idx, alias in enumerate(ent.aliases):
            if _grounded_ci(alias, source_text):
                kept_aliases.append(alias)
            else:
                rejections.append(Rejection("entity_alias", f"{ent.entity_id}:{idx}",
                                            "alias not found in source"))
        ent.aliases = kept_aliases
        for sub in ("node", "chip"):
            attrs = getattr(ent, sub)
            if attrs is None:
                continue
            for field in GROUNDABLE[sub]:
                if getattr(attrs, field) is None:
                    continue
                path = f"{sub}.{field}"
                cite = ent.attribute_citations.get(path)
                if cite is None or not is_grounded(cite.quote_span, source_text):
                    setattr(attrs, field, None)  # drop the ungrounded attribute
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

        # Vendor is case-folded like name: one document's "TSMC"/"Tsmc" is one
        # vendor, not two entities (2026-08-18 gate, schema-purist risk).
        key = (ent.vendor.strip().lower(), ent.name.strip().lower())
        if key in seen:
            base = seen[key]
            for alias in ent.aliases:
                if alias not in base.aliases:
                    base.aliases.append(alias)
            # Reconcile node/chip attribute VALUES (grounded by now), not just
            # citations — otherwise a merged citation can point at a null value.
            for sub in ("node", "chip"):
                dup_attrs = getattr(ent, sub)
                if dup_attrs is None:
                    continue
                base_attrs = getattr(base, sub)
                if base_attrs is None:
                    setattr(base, sub, dup_attrs)
                else:
                    for field in GROUNDABLE[sub]:
                        if getattr(base_attrs, field) is None and getattr(dup_attrs, field) is not None:
                            setattr(base_attrs, field, getattr(dup_attrs, field))
            for path, cite in ent.attribute_citations.items():
                base.attribute_citations.setdefault(path, cite)
            rejections.append(Rejection("entity_merge", ent.entity_id,
                                        f"merged duplicate into {base.entity_id}"))
        else:
            seen[key] = ent
            kept_entities.append(ent)

    # The canonical `name` is itself a surface form of the entity: pin it into
    # aliases so alias-based resolution never depends on whether the model chose
    # to repeat it there (a judgment call models make inconsistently). Applied to
    # the surviving entities only, so a merged case-variant dup's name never
    # injects alias noise. Exempt from G1 by construction: the name is the
    # shape-validated identity field, already presence-grounded above.
    for ent in kept_entities:
        if ent.name not in ent.aliases:
            ent.aliases.insert(0, ent.name)

    vendor_of = {e.entity_id: e.vendor for e in kept_entities}
    kept_entity_ids = set(vendor_of)

    # --- claims: provenance, ground, integrity, completeness, fail-safe ---
    kept_claims: list[models.Claim] = []
    for claim in claims:
        # A claim must be about an entity extracted from THIS document. A hostile
        # doc can otherwise name a real competitor's entity_id to attach a claim.
        if claim.entity_id not in kept_entity_ids:
            rejections.append(Rejection("claim", claim.claim_id,
                                        "references an entity absent from this document's proposal"))
            continue
        if not is_grounded(claim.citation.quote_span, source_text):
            rejections.append(Rejection("claim", claim.claim_id,
                                        "quote_span not found in source"))
            continue
        # Sparse-benchmark vocabulary in the (now grounded) quote_span force-sets
        # sparsity=True — the self-declaration is not trusted in the non-suspect
        # direction. Must run before the marketing_only check below, which reads it.
        if claim.conditions.sparsity is not True and _SPARSE_VOCAB_V1.search(claim.citation.quote_span):
            claim.conditions.sparsity = True
            rejections.append(Rejection("claim_condition", claim.claim_id,
                                        "sparsity forced true: sparse-benchmark vocabulary in quote_span"))
        # A relative claim must express relative magnitude (ratio or percent),
        # never an absolute measurement unit.
        if claim.comparison.is_relative and claim.unit not in RELATIVE_OK_UNITS:
            rejections.append(Rejection("claim", claim.claim_id,
                                        "relative claim carries a non-ratio/percent (absolutized) unit"))
            continue
        # A pure ratio unit (x) is inherently comparative — is_relative must be set.
        # (% is intentionally excluded: an absolute rate like a 65% yield is valid.)
        if claim.unit in RATIO_UNITS and not claim.comparison.is_relative:
            rejections.append(Rejection("claim", claim.claim_id,
                                        "ratio unit but is_relative not set (undeclared relativity)"))
            continue
        # Don't trust the model's completeness label: a relative claim with no
        # baseline is missing_baseline regardless of what the model reported.
        if (claim.comparison.is_relative and claim.comparison.baseline_entity is None
                and claim.completeness == models.Completeness.complete):
            claim.completeness = models.Completeness.missing_baseline
        # marketing_only: sparsity + a genuine CROSS-VENDOR (competitor) comparison.
        # BOTH vendors must be known — an unresolved (None) baseline vendor is NOT
        # treated as "different vendor" (that misfired on same-vendor claims whose
        # baseline wasn't in the proposal, e.g. a vendor slide citing N2-vs-N3E
        # without declaring N3E). Sparsity suspicion for same-vendor comparisons is
        # an analyze-layer signal, not a completeness label.
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
    """Validate + normalize a proposal, logging (not raising on) per-item rejections."""
    result, rejections = validate_proposal(proposal, source_text)
    for rej in rejections:
        logger.warning("validate %s [%s]: %s", rej.kind, _safe(rej.target), rej.reason)
    return result
