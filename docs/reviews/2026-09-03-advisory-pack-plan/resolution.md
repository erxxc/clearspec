# Resolution — advisory pack (plan)

Merge of reviewer opinions. Human adjudicator: Adversarial Review (GEI-12).

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | CONDITIONAL | Prove kind stamp, display, forget on NVD JSON |
| schema-purist | CONDITIONAL | Keep v4 frozen; empty-cve + set math; no resolver |
| pragmatist-shipper | APPROVE | Suite is DoD; prefer prove-existing over new code |
| devils-advocate | (challenge) | Must include full ingest→forget filesystem seam |

## Agreements
- Named hostile suite is the ENFORCE artifact; swarm shape matches WS-2a/WS-2b.
- Offline only for M0; do not edit v4 yaml; never auto-resolve.
- Conflict-as-product: both members persist.

## Named conflicts
### Conflict 1 — breadth of suite vs ship speed
- **Positions:** injection-attacker wants deep display+forget coverage; pragmatist wants a capped table.
- **Cost:** deep suite delays M0; thin suite misses WS-2a-class fold bugs.
- **Decision (human):** Adopt the ticket attack table (11 cases) including mandatory full-chain forget_poison + sidecar/JSON self-attest. No expansion beyond table without a new finding.
- **Rationale:** Matches GEI-12 text and DA challenge.
- **Accepted by:** Adversarial Review

## Devil's-advocate challenge
- **Question:** Will tests only restate unit tests and skip the filesystem seam?
- **Disposition:** Required case `test_forget_refold_poisoned_nvd_json` + self-attest on ingest→extract path.

## Residual risks accepted
- Homoglyph / confusable CVE or package names — revisit when live corpus shows a case (same trigger as WS-2a textnorm).
- Live model advisory injection (`@live`) — deferred; offline validate+replay is M0 gate.
- `quote_span` stored verbatim — accepted; any future evidence UI must use `_ansi_safe`.

## Outcome
**proceed-with-conditions** — land `tests/test_gei12_hostile.py` covering the attack table; run precommit swarm on that diff; Adversarial Review sign-off required before M0 advisory pack gate is closed.
