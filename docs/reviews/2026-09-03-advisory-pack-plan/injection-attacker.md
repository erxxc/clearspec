# injection-attacker — advisory pack plan

**Verdict: CONDITIONAL**

## Findings
1. **Self-attested kind is the #1 advisory injection.** A hostile NVD/GHSA JSON or model proposal that emits `source_record_kind=cisa_kev|nvd_cna|ghsa_reviewed` must never become persist truth. Validate strip + ingest stamp are claimed; the suite must prove stamp-over-self-attest on the full ingest→extract path, not only unit validate.
2. **Display / evidence fields.** `workaround_text`, `quote_span`, and conflict offered/stored values are adversary-authored. CLI already avoids echoing workaround_text; prove ANSI/OSC/bidi cannot survive any advisory `report` line (cve_id, claim_class, set_relation, flags, favored_tier, conflict values).
3. **Forget/refold is the retraction primitive.** A poisoned NVD-shaped JSON that folds in must be fully retractable; silent survival after `forget` is a ship-blocker. Also watchlist revival of quarantined advisory doc_ids must stay refused.

## Risk others will miss
Grounding is fidelity, not trust: a self-consistent hostile advisory can ground a false range. Cross-doc floors (never-overwrite, grouping conflict-as-product, H1-style publisher floor for advisory) are the real defense — the suite must keep conflict visible, never auto-resolve away the second claim.
