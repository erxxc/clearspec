# injection-attacker — advisory pack precommit

**Verdict: CONDITIONAL**

## Findings
1. **Filesystem seam present.** `test_forget_refold_poisoned_nvd_json` runs ingest_file → extract(replay) → forget and asserts cisa_kev self-attest in JSON does not persist. Good — not theater.
2. **Display.** `test_advisory_display_sanitizer` proves `_ansi_safe` + no workaround_text interpolation. Residual: quote_span still stored verbatim (accepted residual from WS-2a).
3. **Kind stamp.** Self-attest strip + ingest stamp covered. Want CI green confirmation before unconditional approve.

## Risk others will miss
Never-overwrite test uses post-validate persist path (shaped models). That is correct for store K2, but does not prove validate grounding of hostile purl strings — acceptable split: store attack vs validate attack already covered by spoofed bound case.
