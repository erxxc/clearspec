-- 0002 — v2 schema (schema/extraction_schema_v2.yaml). Append-only: do NOT edit 0001.
--
--   1. entity.attribute_citations: per-attribute grounding evidence (JSON map
--      attribute-path -> citation). Every non-null node/chip attribute must have
--      a citation whose quote_span appears in the source (enforced in
--      extract/validate.py), giving entity attributes the same hallucination
--      control that claims already have.
--   2. claim.cite_location_type gains 'unknown' — flat-text extraction can't tell
--      body/table/footnote apart, so it fails safe to 'unknown' rather than
--      laundering a footnote claim into the trusted 'body' bucket.

-- (1) Entity grounding column.
ALTER TABLE entity ADD COLUMN attribute_citations TEXT NOT NULL DEFAULT '{}';

-- (2) Expand the location_type CHECK. SQLite can't alter a CHECK in place, so
-- recreate the claim table. Nothing references claim by foreign key, so this is
-- a safe drop/recreate.
CREATE TABLE claim_new (
    claim_id              TEXT PRIMARY KEY,
    doc_id                TEXT NOT NULL REFERENCES document(doc_id),
    entity_id             TEXT NOT NULL REFERENCES entity(entity_id),
    claim_class           TEXT NOT NULL CHECK (claim_class IN
                            ('performance','efficiency','density','power',
                             'yield','cost','availability')),
    metric                TEXT NOT NULL,
    value                 REAL NOT NULL,
    unit                  TEXT NOT NULL,
    cmp_is_relative       INTEGER NOT NULL DEFAULT 0,
    cmp_baseline_entity   TEXT REFERENCES entity(entity_id),
    cmp_baseline_stated   INTEGER NOT NULL DEFAULT 0,
    cond_workload         TEXT,
    cond_precision        TEXT,
    cond_sparsity         INTEGER,
    cond_thermal_config   TEXT,
    cond_stated_caveats   TEXT NOT NULL DEFAULT '[]',
    completeness          TEXT NOT NULL CHECK (completeness IN
                            ('complete','missing_baseline',
                             'missing_conditions','marketing_only')),
    cite_page             INTEGER,
    cite_quote_span       TEXT NOT NULL,
    cite_location_type    TEXT NOT NULL CHECK (cite_location_type IN
                            ('body','table','figure','footnote','unknown')),
    corr_status           TEXT NOT NULL DEFAULT 'uncorroborated' CHECK (corr_status IN
                            ('uncorroborated','corroborated','contradicted')),
    corr_related_claim_ids TEXT NOT NULL DEFAULT '[]'
);

INSERT INTO claim_new SELECT * FROM claim;
DROP TABLE claim;
ALTER TABLE claim_new RENAME TO claim;

CREATE INDEX IF NOT EXISTS idx_claim_doc    ON claim(doc_id);
CREATE INDEX IF NOT EXISTS idx_claim_entity ON claim(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_class  ON claim(claim_class);
