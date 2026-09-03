"""source_record_kind is ingest-attested, not model-emitted.

Kind comes from fetch/provenance (sidecar `doc_type` + CNA-vs-CPE parser role),
never from the LLM extraction proposal. `validate.py` strips any model-emitted
value; `persist_extraction` stamps the ingest kind onto advisory claims; SQL
CHECK requires it for advisory classes.

Yaml ranking later treats `ghsa_reviewed` / `nvd_cna` / `cisa_kev` as
high-weight — a researcher_writeup must not be able to self-attest those.

GEI-11 owns full operator ingest. This module is the stamp hook + compatibility
table only.
"""

from __future__ import annotations

from . import models

# (doc_type value, parser_role) -> source_record_kind
# parser_role is the ingest discriminator (CNA vs CPE, GHSA reviewed vs not).
# It is NOT model output.
KIND_COMPAT: dict[tuple[str, str], models.SourceRecordKind] = {
    ("nvd_record", "cna"): models.SourceRecordKind.nvd_cna,
    ("nvd_record", "cpe"): models.SourceRecordKind.nvd_cpe,
    ("nvd_record", "catalog"): models.SourceRecordKind.nvd_catalog,
    ("nvd_record", "exploit_field"): models.SourceRecordKind.nvd_exploit_field,
    ("ghsa", "reviewed"): models.SourceRecordKind.ghsa_reviewed,
    ("ghsa", "unreviewed"): models.SourceRecordKind.ghsa_unreviewed,
    ("ghsa", "exploit_field"): models.SourceRecordKind.ghsa_exploit_field,
    ("vendor_advisory", "json"): models.SourceRecordKind.vendor_json,
    ("vendor_advisory", "cna"): models.SourceRecordKind.vendor_cna,
    ("vendor_advisory", "acknowledgement"): models.SourceRecordKind.vendor_acknowledgement,
    ("vendor_advisory", "cvss"): models.SourceRecordKind.vendor_cvss,
    ("cisa_kev", "kev"): models.SourceRecordKind.cisa_kev,
    ("researcher_writeup", "peer"): models.SourceRecordKind.peer_research,
}


def attested_kind(
    doc_type: str | models.DocType, parser_role: str,
) -> models.SourceRecordKind:
    """Resolve ingest provenance to a source_record_kind.

    `parser_role` is the CNA-vs-CPE (or GHSA reviewed vs unreviewed) discriminator
    supplied by fetch/parser, not by the extraction model.
    """
    key = (getattr(doc_type, "value", doc_type), parser_role)
    try:
        return KIND_COMPAT[key]
    except KeyError as exc:
        raise ValueError(
            f"no ingest attestation for doc_type={key[0]!r} parser_role={parser_role!r}"
        ) from exc


def stamp_advisory_claims(
    claims: list[models.Claim],
    kind: models.SourceRecordKind | str,
) -> list[models.Claim]:
    """Overwrite source_record_kind on advisory claims. Foundry claims untouched.

    Ingest stamp wins over any leftover model value (validate should already
    have stripped it).
    """
    stamped = models.SourceRecordKind(kind)
    out: list[models.Claim] = []
    for claim in claims:
        if claim.claim_class in models.ADVISORY_CLAIM_CLASSES:
            out.append(claim.model_copy(update={"source_record_kind": stamped}))
        else:
            out.append(claim)
    return out


def identity_material(url: str, source_record_kind: str | None = None) -> bytes:
    """Bytes hashed into ingest doc_id. Foundry (kind is None) is url-only.

    NVD CNA and NVD CPE share a URL but are different records (GEI-6): passing
    the ingest kind keeps their doc_ids distinct. URL alone must never be the
    identity key.
    """
    if source_record_kind:
        return f"{url}\0{source_record_kind}".encode()
    return url.encode()


def kind_from_sidecar(meta: dict) -> models.SourceRecordKind | None:
    """DO NOT use on the operator ingest path (GEI-11).

    Reads meta['source_record_kind'] and BYPASSES KIND_COMPAT. A sidecar or
    advisory JSON that self-attests ghsa_reviewed / cisa_kev / nvd_cna would
    launder that kind as if ingest had attested it. Operator ingest stamps
    via `kind_from_operator_sidecar` (doc_type + parser_role through
    KIND_COMPAT only) and ignores these fields as adversary-controlled.
    """
    raw = meta.get("source_record_kind")
    if not raw:
        return None
    return models.SourceRecordKind(raw)


def kind_from_operator_sidecar(meta: dict) -> models.SourceRecordKind | None:
    """Stamp kind ONLY via KIND_COMPAT(doc_type, parser_role).

    Sidecar still stores doc_type + publisher (PRD) plus operator parser_role.
    `source_record_kind` / `ghsa_reviewed` / `cisa_kev` / `nvd_cna` on the
    sidecar or in the ingested JSON are ignored — never copied, never used
    as identity. Foundry (doc_type not in KIND_COMPAT) returns None.
    """
    doc_type = meta.get("doc_type")
    if not doc_type:
        return None
    dt = getattr(doc_type, "value", doc_type)
    if dt not in {key[0] for key in KIND_COMPAT}:
        return None
    parser_role = meta.get("parser_role")
    if not parser_role:
        raise ValueError(
            f"advisory sidecar for doc_type={dt!r} missing operator parser_role"
        )
    return attested_kind(dt, parser_role)
