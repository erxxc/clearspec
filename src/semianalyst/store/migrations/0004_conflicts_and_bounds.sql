-- 0004 — v4 schema (schema/extraction_schema_v4.yaml). Append-only: do NOT edit 0001-0003.
--
-- (1) NEW table entity_conflict: a persisted, per-EVENT reconciliation-refusal
--     record (2026-08-18 gate, Conflict 1 resolution). Written whenever a later
--     document differs from stored state in a way reconcile refuses to apply
--     (never-overwrite is universal). Persisted, not derive-on-read, because the
--     offered value is otherwise LOST at refusal time — nothing to re-derive from
--     (contrast decision B2: the corroboration verdict re-derives from surviving
--     rows). offered_value/stored_value are ADVERSARY-AUTHORED text meant for a
--     human reader: bounded <=120 here AND in pydantic, and display sites must
--     route them through the hardened sanitizer (ANSI/OSC + Unicode Cf).
-- (2) LENGTH bounds (v4 `bounds` block) mirrored as CHECK constraints on
--     document/entity/claim — the durable flood guard; charset/pattern stays in
--     pydantic (SQLite has no honest regex CHECK). SQLite can't ALTER-in a CHECK,
--     so the three tables are recreated (0003 precedent). FK enforcement is
--     suspended for the swap: executescript runs this outside the runner's
--     transaction, so the PRAGMAs below take effect.
--
-- Carry-forward lists every surviving column explicitly (no SELECT *).

PRAGMA foreign_keys = OFF;
BEGIN;

-- DOCUMENT (recreated: + length CHECKs; columns unchanged)
CREATE TABLE document_v4 (
    doc_id            TEXT PRIMARY KEY CHECK (length(doc_id) <= 120),
    title             TEXT NOT NULL CHECK (length(title) <= 300),
    publisher         TEXT NOT NULL CHECK (length(publisher) <= 120),
    doc_type          TEXT NOT NULL CHECK (doc_type IN
                        ('foundry_announcement','conference_paper',
                         'vendor_whitepaper','product_brief')),
    source_tier       INTEGER NOT NULL CHECK (source_tier IN (1,2,3)),
    publish_date      TEXT,
    url               TEXT NOT NULL CHECK (length(url) <= 2000),
    file_sha256       TEXT NOT NULL CHECK (length(file_sha256) = 64),
    ingest_date       TEXT NOT NULL,
    extraction_model  TEXT CHECK (extraction_model IS NULL OR length(extraction_model) <= 200),
    review_status     TEXT NOT NULL DEFAULT 'unreviewed' CHECK (review_status IN
                        ('unreviewed','human_verified','disputed'))
);
INSERT INTO document_v4 SELECT
    doc_id, title, publisher, doc_type, source_tier, publish_date, url,
    file_sha256, ingest_date, extraction_model, review_status FROM document;
DROP TABLE document;
ALTER TABLE document_v4 RENAME TO document;

-- ENTITY (recreated: + length CHECKs; columns unchanged. aliases is a JSON
-- array — the serialized-length CHECK is a coarse flood guard; per-item bounds
-- (<=16 items x <=80 chars) live in pydantic.)
CREATE TABLE entity_v4 (
    entity_id             TEXT PRIMARY KEY CHECK (length(entity_id) <= 80),
    entity_type           TEXT NOT NULL CHECK (entity_type IN
                            ('process_node','chip','chiplet','package','ip_block')),
    vendor                TEXT NOT NULL CHECK (length(vendor) <= 80),
    name                  TEXT NOT NULL CHECK (length(name) <= 80),
    aliases               TEXT NOT NULL DEFAULT '[]' CHECK (length(aliases) <= 1500),
    node_density_mtx_mm2  REAL,
    node_transistor_type  TEXT CHECK (node_transistor_type IN
                            ('finfet','gaa_nanosheet','cfet')),
    node_backside_power   INTEGER,
    node_hvm_date_claimed TEXT,
    node_hvm_date_actual  TEXT,
    chip_process_node_ref TEXT REFERENCES entity(entity_id)
                            CHECK (chip_process_node_ref IS NULL OR length(chip_process_node_ref) <= 80),
    chip_transistor_count_b REAL,
    chip_die_size_mm2     REAL,
    chip_package_type     TEXT CHECK (chip_package_type IS NULL OR length(chip_package_type) <= 120),
    chip_memory_type      TEXT CHECK (chip_memory_type IS NULL OR length(chip_memory_type) <= 120),
    chip_memory_bw_gbps   REAL,
    chip_tdp_w            REAL,
    chip_launch_date      TEXT,
    attribute_citations   TEXT NOT NULL DEFAULT '{}'   -- 0002: per-attribute grounding (JSON map)
);
INSERT INTO entity_v4 SELECT
    entity_id, entity_type, vendor, name, aliases,
    node_density_mtx_mm2, node_transistor_type, node_backside_power,
    node_hvm_date_claimed, node_hvm_date_actual,
    chip_process_node_ref, chip_transistor_count_b, chip_die_size_mm2,
    chip_package_type, chip_memory_type, chip_memory_bw_gbps, chip_tdp_w,
    chip_launch_date, attribute_citations FROM entity;
DROP TABLE entity;
ALTER TABLE entity_v4 RENAME TO entity;

-- CLAIM (recreated: + length CHECKs; columns unchanged from 0003)
CREATE TABLE claim_v4 (
    claim_id              TEXT PRIMARY KEY CHECK (length(claim_id) <= 200),
    doc_id                TEXT NOT NULL REFERENCES document(doc_id),
    entity_id             TEXT NOT NULL REFERENCES entity(entity_id),
    claim_class           TEXT NOT NULL CHECK (claim_class IN
                            ('performance','efficiency','density','power',
                             'yield','cost','availability')),
    metric                TEXT NOT NULL CHECK (length(metric) <= 120),
    value                 REAL NOT NULL,
    unit                  TEXT NOT NULL CHECK (length(unit) <= 16),
    cmp_is_relative       INTEGER NOT NULL DEFAULT 0,
    cmp_baseline_entity   TEXT CHECK (cmp_baseline_entity IS NULL OR length(cmp_baseline_entity) <= 80),
    cmp_baseline_stated   INTEGER NOT NULL DEFAULT 0,
    cond_workload         TEXT CHECK (cond_workload IS NULL OR length(cond_workload) <= 120),
    cond_precision        TEXT CHECK (cond_precision IS NULL OR length(cond_precision) <= 120),
    cond_sparsity         INTEGER,
    cond_thermal_config   TEXT CHECK (cond_thermal_config IS NULL OR length(cond_thermal_config) <= 120),
    cond_stated_caveats   TEXT NOT NULL DEFAULT '[]' CHECK (length(cond_stated_caveats) <= 8500),
    completeness          TEXT NOT NULL CHECK (completeness IN
                            ('complete','missing_baseline',
                             'missing_conditions','marketing_only')),
    cite_page             INTEGER,
    cite_quote_span       TEXT NOT NULL CHECK (length(cite_quote_span) <= 2000),
    cite_location_type    TEXT NOT NULL CHECK (cite_location_type IN
                            ('body','table','figure','footnote','unknown'))
);
INSERT INTO claim_v4 SELECT
    claim_id, doc_id, entity_id, claim_class, metric, value, unit,
    cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated,
    cond_workload, cond_precision, cond_sparsity, cond_thermal_config,
    cond_stated_caveats, completeness, cite_page, cite_quote_span,
    cite_location_type FROM claim;
DROP TABLE claim;
ALTER TABLE claim_v4 RENAME TO claim;

CREATE INDEX IF NOT EXISTS idx_claim_doc    ON claim(doc_id);
CREATE INDEX IF NOT EXISTS idx_claim_entity ON claim(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_class  ON claim(claim_class);

-- ENTITY_CONFLICT (v4, NEW — see header (1))
CREATE TABLE entity_conflict (
    conflict_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL CHECK (kind IN
                    ('identity_field','attribute','alias_collision')),
    entity_id     TEXT NOT NULL REFERENCES entity(entity_id),
    doc_id        TEXT NOT NULL REFERENCES document(doc_id),  -- the offender
    field         TEXT NOT NULL CHECK (length(field) <= 80),
    stored_value  TEXT CHECK (stored_value IS NULL OR length(stored_value) <= 120),
    offered_value TEXT NOT NULL CHECK (length(offered_value) <= 120),
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_conflict_entity ON entity_conflict(entity_id);
CREATE INDEX idx_conflict_doc    ON entity_conflict(doc_id);

COMMIT;
PRAGMA foreign_keys = ON;
