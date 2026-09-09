# GEI-14 — curated JSON parser_role mapping

Curated JSON watchlist sources only (NVD API, GHSA, CISA KEV). HTML discovery
and vendor HTML pages stay deferred.

| `doc_type`   | `parser_role`                         | Attested `source_record_kind` |
|--------------|---------------------------------------|-------------------------------|
| `nvd_record` | `cna` / `cpe` / `catalog` / `exploit_field` | `nvd_cna` / `nvd_cpe` / `nvd_catalog` / `nvd_exploit_field` |
| `ghsa`       | `reviewed` / `unreviewed` / `exploit_field` | `ghsa_reviewed` / `ghsa_unreviewed` / `ghsa_exploit_field` |
| `cisa_kev`   | `kev`                                 | `cisa_kev`                    |

Rules:
- Configure `parser_role` on the `[[sources]]` row in `config.toml`.
- Sidecar stores `doc_type` + `publisher` + `parser_role` — **never** `source_record_kind`.
- Extract stamps kind via `attested_kind(doc_type, parser_role)` / `kind_from_operator_sidecar`.
- Identity uses `identity_doc_id(url, kind)` so NVD CNA vs CPE at the same URL stay distinct.
- Fetch reuses WS-2b `fetch_url` / `_fetch` (HTTPS-only every hop, size/redirect caps).
