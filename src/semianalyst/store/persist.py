"""Persist a document's extraction into the store, with entity reconciliation.

`persist_extraction` is the write-path the ingest->extract pipeline calls. It
inserts the document (fail-loud on a duplicate doc_id), reconciles each entity
into the store (read-compare-write: alias-union with G3 collision refusal,
fill-null with never-overwrite, refusals persisted as Conflict records — see
db.reconcile_entity), and inserts each claim under a document-scoped claim_id so
two documents' claims about the same entity+metric don't collide.

Remaining cross-document trust decisions (tier precedence beyond never-overwrite,
status-level tier floors) stay with analyze / later workstreams. See CLAUDE.md.
"""

from __future__ import annotations

import sqlite3

from . import models
from .db import insert_claim, insert_document, reconcile_entity


def _scope(doc_id: str, claim_id: str) -> str:
    """Document-scope a claim_id; idempotent if already scoped."""
    prefix = f"{doc_id}:"
    return claim_id if claim_id.startswith(prefix) else prefix + claim_id


def persist_extraction(
    conn: sqlite3.Connection,
    document: models.Document,
    entities: list[models.Entity],
    claims: list[models.Claim],
) -> None:
    """Fold one document's validated extraction into the store.

    Reconciliation refusals land in `entity_conflict` under this document's
    doc_id. Conflicts are a deterministic function of persist order and content:
    a rebuild (extract.run_rebuild) replays persist_extraction over retained
    artifacts in `_extracted_at` order — the actual incremental chronology — so
    incremental conflicts regenerate identically on refold — and conflicts attributed to forgotten or
    superseded documents disappear with them. That is correct semantics: the
    conflict table describes the CURRENT fold, not an audit log of every write
    ever attempted (the quarantined artifact remains the durable record).
    """
    insert_document(conn, document)  # fail-loud on duplicate doc_id
    for entity in entities:
        reconcile_entity(conn, entity, document.doc_id)
    for claim in claims:
        scoped = claim.model_copy(update={"claim_id": _scope(document.doc_id, claim.claim_id)})
        insert_claim(conn, scoped)
