-- 0005 — v5 advisory pack (schema/extraction_schema_v5.yaml). Append-only:
-- do NOT edit 0001-0004. v4 yaml is unedited; foundry rows carry forward.
--
-- (1) Expand document.doc_type / entity.entity_type / claim.claim_class /
--     claim.completeness CHECKs for the advisory pack. Foundry values stay.
-- (2) Entity gains package/product/cve attribute columns (citation-grounded
--     in pydantic; LENGTH CHECKs here). Software `package` reuses the v1
--     entity_type 'package' (semiconductor package vs software package are
--     distinguished by which attribute block is populated).
-- (3) Claim gains cve_id (grouping key), source_record_kind (NVD CNA vs NVD
--     CPE even when they share a URL), structured version_range JSON,
--     exploit_status, workaround_text. value/unit become nullable so a range
--     is never stuffed into a float/display string.
-- (4) NEVER AUTO-RESOLVE: this migration adds storage. No trigger, generated
--     column, or unique constraint picks a winning source_record_kind.
-- JSON version_range flood guard: 32 intervals x 2 bounds x 80 chars x 6-byte
-- escape -> 40000 (schema-purist F2 rule, same as v4 aliases/caveats).

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE document_v5 (
    doc_id            TEXT PRIMARY KEY CHECK (length(doc_id) <= 120),
    title             TEXT NOT NULL CHECK (length(title) <= 300),
    publisher         TEXT NOT NULL CHECK (length(publisher) <= 120),
    doc_type          TEXT NOT NULL CHECK (doc_type IN
                        ('foundry_announcement','conference_paper',
                         'vendor_whitepaper','product_brief',
                         'nvd_record','ghsa','vendor_advisory',
                         'cisa_kev','researcher_writeup')),
    source_tier       INTEGER NOT NULL CHECK (source_tier IN (1,2,3)),
    publish_date      TEXT,
    url               TEXT NOT NULL CHECK (length(url) <= 2000),
    file_sha256       TEXT NOT NULL CHECK (length(file_sha256) = 64),
    ingest_date       TEXT NOT NULL,
    extraction_model  TEXT CHECK (extraction_model IS NULL OR length(extraction_model) <= 200),
    review_status     TEXT NOT NULL DEFAULT 'unreviewed' CHECK (review_status IN
                        ('unreviewed','human_verified','disputed'))
);
INSERT INTO document_v5 SELECT
    doc_id, title, publisher, doc_type, source_tier, publish_date, url,
    file_sha256, ingest_date, extraction_model, review_status FROM document;
DROP TABLE document;
ALTER TABLE document_v5 RENAME TO document;

CREATE TABLE entity_v5 (
    entity_id             TEXT PRIMARY KEY CHECK (length(entity_id) <= 80),
    entity_type           TEXT NOT NULL CHECK (entity_type IN
                            ('process_node','chip','chiplet','package','ip_block',
                             'cve','product','advisory')),
    vendor                TEXT NOT NULL CHECK (length(vendor) <= 80),
    name                  TEXT NOT NULL CHECK (length(name) <= 80),
    aliases               TEXT NOT NULL DEFAULT '[]' CHECK (length(aliases) <= 8000),
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
    attribute_citations   TEXT NOT NULL DEFAULT '{}',
    pkg_ecosystem         TEXT CHECK (pkg_ecosystem IS NULL OR length(pkg_ecosystem) <= 80),
    pkg_name              TEXT CHECK (pkg_name IS NULL OR length(pkg_name) <= 80),
    pkg_purl              TEXT CHECK (pkg_purl IS NULL OR length(pkg_purl) <= 512),
    pkg_cpe               TEXT CHECK (pkg_cpe IS NULL OR length(pkg_cpe) <= 256),
    product_ecosystem     TEXT CHECK (product_ecosystem IS NULL OR length(product_ecosystem) <= 80),
    product_name          TEXT CHECK (product_name IS NULL OR length(product_name) <= 80),
    product_purl          TEXT CHECK (product_purl IS NULL OR length(product_purl) <= 512),
    product_cpe           TEXT CHECK (product_cpe IS NULL OR length(product_cpe) <= 256),
    cve_id                TEXT CHECK (cve_id IS NULL OR length(cve_id) <= 32),
    cve_cwe               TEXT CHECK (cve_cwe IS NULL OR length(cve_cwe) <= 32)
);
INSERT INTO entity_v5 (
    entity_id, entity_type, vendor, name, aliases,
    node_density_mtx_mm2, node_transistor_type, node_backside_power,
    node_hvm_date_claimed, node_hvm_date_actual,
    chip_process_node_ref, chip_transistor_count_b, chip_die_size_mm2,
    chip_package_type, chip_memory_type, chip_memory_bw_gbps, chip_tdp_w,
    chip_launch_date, attribute_citations
) SELECT
    entity_id, entity_type, vendor, name, aliases,
    node_density_mtx_mm2, node_transistor_type, node_backside_power,
    node_hvm_date_claimed, node_hvm_date_actual,
    chip_process_node_ref, chip_transistor_count_b, chip_die_size_mm2,
    chip_package_type, chip_memory_type, chip_memory_bw_gbps, chip_tdp_w,
    chip_launch_date, attribute_citations FROM entity;
DROP TABLE entity;
ALTER TABLE entity_v5 RENAME TO entity;

CREATE TABLE claim_v5 (
    claim_id              TEXT PRIMARY KEY CHECK (length(claim_id) <= 200),
    doc_id                TEXT NOT NULL REFERENCES document(doc_id),
    entity_id             TEXT NOT NULL REFERENCES entity(entity_id),
    claim_class           TEXT NOT NULL CHECK (claim_class IN
                            ('performance','efficiency','density','power',
                             'yield','cost','availability',
                             'affected_range','patched_in','cvss',
                             'exploit_status','workaround')),
    metric                TEXT NOT NULL CHECK (length(metric) <= 120),
    value                 REAL,
    unit                  TEXT CHECK (unit IS NULL OR length(unit) <= 16),
    cmp_is_relative       INTEGER NOT NULL DEFAULT 0,
    cmp_baseline_entity   TEXT CHECK (cmp_baseline_entity IS NULL OR length(cmp_baseline_entity) <= 80),
    cmp_baseline_stated   INTEGER NOT NULL DEFAULT 0,
    cond_workload         TEXT CHECK (cond_workload IS NULL OR length(cond_workload) <= 120),
    cond_precision        TEXT CHECK (cond_precision IS NULL OR length(cond_precision) <= 120),
    cond_sparsity         INTEGER,
    cond_thermal_config   TEXT CHECK (cond_thermal_config IS NULL OR length(cond_thermal_config) <= 120),
    cond_stated_caveats   TEXT NOT NULL DEFAULT '[]' CHECK (length(cond_stated_caveats) <= 50000),
    completeness          TEXT NOT NULL CHECK (completeness IN
                            ('complete','missing_baseline','missing_conditions',
                             'marketing_only','missing_range','missing_product')),
    cite_page             INTEGER,
    cite_quote_span       TEXT NOT NULL CHECK (length(cite_quote_span) <= 2000),
    cite_location_type    TEXT NOT NULL CHECK (cite_location_type IN
                            ('body','table','figure','footnote','unknown')),
    cve_id                TEXT CHECK (cve_id IS NULL OR length(cve_id) <= 32),
    source_record_kind    TEXT CHECK (source_record_kind IS NULL OR source_record_kind IN
                            ('nvd_cna','nvd_cpe','nvd_catalog',
                             'ghsa_reviewed','ghsa_unreviewed',
                             'vendor_json','vendor_cna','vendor_acknowledgement',
                             'vendor_cvss','cisa_kev',
                             'nvd_exploit_field','ghsa_exploit_field',
                             'peer_research')),
    version_range         TEXT CHECK (version_range IS NULL OR length(version_range) <= 40000),
    exploit_status        TEXT CHECK (exploit_status IS NULL OR exploit_status IN
                            ('known_exploited','no_known_exploit','disputed')),
    workaround_text       TEXT CHECK (workaround_text IS NULL OR length(workaround_text) <= 500)
);
INSERT INTO claim_v5 (
    claim_id, doc_id, entity_id, claim_class, metric, value, unit,
    cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated,
    cond_workload, cond_precision, cond_sparsity, cond_thermal_config,
    cond_stated_caveats, completeness, cite_page, cite_quote_span,
    cite_location_type
) SELECT
    claim_id, doc_id, entity_id, claim_class, metric, value, unit,
    cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated,
    cond_workload, cond_precision, cond_sparsity, cond_thermal_config,
    cond_stated_caveats, completeness, cite_page, cite_quote_span,
    cite_location_type FROM claim;
DROP TABLE claim;
ALTER TABLE claim_v5 RENAME TO claim;

CREATE INDEX IF NOT EXISTS idx_claim_doc    ON claim(doc_id);
CREATE INDEX IF NOT EXISTS idx_claim_entity ON claim(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_class  ON claim(claim_class);
CREATE INDEX IF NOT EXISTS idx_claim_advisory_group ON claim(cve_id, entity_id, claim_class);

COMMIT;
PRAGMA foreign_keys = ON;
