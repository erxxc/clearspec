# schema-purist — advisory pack precommit

**Verdict: APPROVE**

## Findings
1. v4 yaml untouched. Suite does not edit schema.
2. Empty-cve, CNA/CPE two-doc, KEV-vs-range, and set-relation contradiction pins match GEI-6/9 decisions.
3. Flag budget documents allowlist; no new resolver status invented.

## Risk others will miss
`advisory_group_key` helper still stringifies empty CVE; engine path is what the empty-cve test exercises. Track, not block.
