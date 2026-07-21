-- 0003 — v3 schema (schema/extraction_schema_v3.yaml). Append-only: do NOT edit 0001/0002.
--
-- (1) 'weakly_corroborated' becomes a valid corroboration VERDICT value — but as an
--     analyze output (AnalysisReport), NOT a stored column (see (3)).
-- (2) DROPS the foreign key on cmp_baseline_entity. A baseline can be a
--     cross-document reference an earlier doc introduced, or a dangling one
--     (a competitor node never ingested) — per P2 the claim is KEPT and analyze
--     flags `unresolved_baseline`, so the reference must NOT be FK-enforced.
--     (entity_id keeps its FK — a claim's own subject must be a stored entity.)
-- (3) DROPS the persisted corr_status / corr_related_claim_ids columns that 0002
--     carried. Corroboration is a per-GROUP verdict computed derive-on-read over
--     the whole store on every `report`; a per-ROW column for it was uniformly
--     'uncorroborated' regardless of the true verdict (indistinguishable from
--     "never analyzed") and pre-advertised a write-back path with two conflicting
--     truths. The store now holds NO per-row verdict — the AnalysisReport is the
--     sole source of truth. (Decision B2, analyze GATE-2 resolution. The model
--     keeps a derived, non-persisted `corroboration` field; nothing writes it here.)
--
-- SQLite can't alter a CHECK/FK in place, so recreate the claim table (nothing
-- references claim by foreign key). The column count changed, so the carry-forward
-- lists all 19 surviving columns explicitly (no `SELECT *`).

CREATE TABLE claim_v3 (
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
    cmp_baseline_entity   TEXT,   -- no FK: cross-doc / dangling baselines allowed (P2)
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
                            ('body','table','figure','footnote','unknown'))
    -- no corr_status / corr_related_claim_ids: analyze is derive-on-read (see header (3)).
);

INSERT INTO claim_v3 (
    claim_id, doc_id, entity_id, claim_class, metric, value, unit,
    cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated,
    cond_workload, cond_precision, cond_sparsity, cond_thermal_config,
    cond_stated_caveats, completeness, cite_page, cite_quote_span, cite_location_type
)
SELECT
    claim_id, doc_id, entity_id, claim_class, metric, value, unit,
    cmp_is_relative, cmp_baseline_entity, cmp_baseline_stated,
    cond_workload, cond_precision, cond_sparsity, cond_thermal_config,
    cond_stated_caveats, completeness, cite_page, cite_quote_span, cite_location_type
FROM claim;

DROP TABLE claim;
ALTER TABLE claim_v3 RENAME TO claim;

CREATE INDEX IF NOT EXISTS idx_claim_doc    ON claim(doc_id);
CREATE INDEX IF NOT EXISTS idx_claim_entity ON claim(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_class  ON claim(claim_class);
