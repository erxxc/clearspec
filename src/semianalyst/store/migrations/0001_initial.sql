-- 0001_initial — canonical relational schema, flattened from
-- schema/extraction_schema_v1.yaml. Nested schema blocks (entity.node,
-- entity.chip, claim.comparison/conditions/citation/corroboration) become
-- prefixed columns; list/map fields are stored as JSON text.
--
-- Migrations are append-only. Never edit an applied migration in place —
-- add a new numbered file (see store/db.py).

-- DOCUMENT — one row per ingested release.
CREATE TABLE IF NOT EXISTS document (
    doc_id            TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    publisher         TEXT NOT NULL,
    doc_type          TEXT NOT NULL CHECK (doc_type IN
                        ('foundry_announcement','conference_paper',
                         'vendor_whitepaper','product_brief')),
    source_tier       INTEGER NOT NULL CHECK (source_tier IN (1,2,3)),
    publish_date      TEXT,
    url               TEXT NOT NULL,
    file_sha256       TEXT NOT NULL,   -- detects silent revisions of the same URL
    ingest_date       TEXT NOT NULL,
    extraction_model  TEXT,            -- model + prompt version, for re-runs
    review_status     TEXT NOT NULL DEFAULT 'unreviewed' CHECK (review_status IN
                        ('unreviewed','human_verified','disputed'))
);

-- ENTITY — the thing a claim is about. node_* columns null for chips and
-- vice-versa. One row per real thing (aliases resolved before insert).
CREATE TABLE IF NOT EXISTS entity (
    entity_id             TEXT PRIMARY KEY,
    entity_type           TEXT NOT NULL CHECK (entity_type IN
                            ('process_node','chip','chiplet','package','ip_block')),
    vendor                TEXT NOT NULL,
    name                  TEXT NOT NULL,
    aliases               TEXT NOT NULL DEFAULT '[]',   -- JSON array
    -- node-level attributes
    node_density_mtx_mm2  REAL,
    node_transistor_type  TEXT CHECK (node_transistor_type IN
                            ('finfet','gaa_nanosheet','cfet')),
    node_backside_power   INTEGER,     -- 0/1
    node_hvm_date_claimed TEXT,
    node_hvm_date_actual  TEXT,
    -- chip-level attributes
    chip_process_node_ref TEXT REFERENCES entity(entity_id),  -- node join key
    chip_transistor_count_b REAL,
    chip_die_size_mm2     REAL,
    chip_package_type     TEXT,
    chip_memory_type      TEXT,
    chip_memory_bw_gbps   REAL,
    chip_tdp_w            REAL,
    chip_launch_date      TEXT
);

-- CLAIM — the atomic unit. One row per quantitative assertion.
CREATE TABLE IF NOT EXISTS claim (
    claim_id              TEXT PRIMARY KEY,
    doc_id                TEXT NOT NULL REFERENCES document(doc_id),
    entity_id             TEXT NOT NULL REFERENCES entity(entity_id),
    claim_class           TEXT NOT NULL CHECK (claim_class IN
                            ('performance','efficiency','density','power',
                             'yield','cost','availability')),
    metric                TEXT NOT NULL,
    value                 REAL NOT NULL,
    unit                  TEXT NOT NULL,
    -- comparison: relative claims keep the ratio + baseline; never absolutized.
    cmp_is_relative       INTEGER NOT NULL DEFAULT 0,  -- 0/1
    cmp_baseline_entity   TEXT REFERENCES entity(entity_id),
    cmp_baseline_stated   INTEGER NOT NULL DEFAULT 0,  -- 0/1
    -- conditions
    cond_workload         TEXT,
    cond_precision        TEXT,
    cond_sparsity         INTEGER,     -- 0/1/null
    cond_thermal_config   TEXT,
    cond_stated_caveats   TEXT NOT NULL DEFAULT '[]',   -- JSON array
    completeness          TEXT NOT NULL CHECK (completeness IN
                            ('complete','missing_baseline',
                             'missing_conditions','marketing_only')),
    -- citation (hallucination control)
    cite_page             INTEGER,
    cite_quote_span       TEXT NOT NULL,
    cite_location_type    TEXT NOT NULL CHECK (cite_location_type IN
                            ('body','table','figure','footnote')),
    -- corroboration (the divergence detector)
    corr_status           TEXT NOT NULL DEFAULT 'uncorroborated' CHECK (corr_status IN
                            ('uncorroborated','corroborated','contradicted')),
    corr_related_claim_ids TEXT NOT NULL DEFAULT '[]'   -- JSON array of claim_ids
);

CREATE INDEX IF NOT EXISTS idx_claim_doc    ON claim(doc_id);
CREATE INDEX IF NOT EXISTS idx_claim_entity ON claim(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_class  ON claim(claim_class);

-- MACRO_SNAPSHOT — thin EDGAR layer (Phase 2). Synthetic PK; natural key
-- (vendor, period) is unique.
CREATE TABLE IF NOT EXISTS macro_snapshot (
    macro_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor            TEXT NOT NULL,
    period            TEXT NOT NULL,
    capex_usd_m       REAL,
    segment_revenue   TEXT NOT NULL DEFAULT '{}',   -- JSON map segment -> USD
    inventory_days    REAL,
    rd_spend_usd_m    REAL,
    filing_url        TEXT,
    UNIQUE (vendor, period)
);
