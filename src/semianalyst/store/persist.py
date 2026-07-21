"""Persist a document's extraction into the store, with entity reconciliation.

`persist_extraction` is the write-path the future ingest->extract pipeline will
call. It inserts the document (fail-loud on a duplicate doc_id), reconciles each
entity into the store (alias-union + fill-null; see db.reconcile_entity), and
inserts each claim under a document-scoped claim_id so two documents' claims about
the same entity+metric don't collide.

Cross-document TRUST (tier precedence, hostile-first writes, alias gating,
baseline poisoning of a real entity) is deliberately NOT enforced here — those are
Class-A hostile-input decisions (K/G/H/I/J + resolved-baseline) deferred to the
live-ingest workstream, since no hostile document can reach this path in the
curated-fixture MVP. See CLAUDE.md.
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
    insert_document(conn, document)  # fail-loud on duplicate doc_id
    for entity in entities:
        reconcile_entity(conn, entity)
    for claim in claims:
        scoped = claim.model_copy(update={"claim_id": _scope(document.doc_id, claim.claim_id)})
        insert_claim(conn, scoped)
