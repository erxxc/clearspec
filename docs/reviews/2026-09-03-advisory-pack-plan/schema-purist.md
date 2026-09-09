# schema-purist — advisory pack plan

**Verdict: CONDITIONAL**

## Findings
1. **Class-conditional payloads must stay SQL+pydantic enforced.** Range claims require structured `version_range`; foundry value/unit NOT NULL; advisory kind NOT NULL at persist. Hostile suite should include a shape-rejection case for ungrounded exclusive+1 bounds (already in validate) and empty-cve grouping refusal at analyze.
2. **v4 yaml must remain unedited.** Gate artifacts and tests must not touch `extraction_schema_v4.yaml`.
3. **Grouping key is representation, not a resolver.** `advisory_group_key` must not pick winners; empty `cve_id` must not collapse unrelated claims. Align helper semantics with `analyze_claims` or document that only analyze is authoritative.

## Risk others will miss
Multi-interval PAN-OS-style ranges vs single NVD intervals: set math must stay equal/subset/overlap/disjoint — never ±10%. Flag budget must not invent a “resolved” status.
