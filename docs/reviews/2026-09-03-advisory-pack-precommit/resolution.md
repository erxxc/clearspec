# Resolution — advisory pack (precommit)

Human adjudicator: Adversarial Review (GEI-12).

## Verdicts as returned
| Role | Verdict | One-line |
|---|---|---|
| injection-attacker | CONDITIONAL | Seam + display + kind OK; want green CI |
| schema-purist | APPROVE | Decisions held; helper empty-cve is track |
| pragmatist-shipper | APPROVE | Scoped suite; prove-existing |
| devils-advocate | (challenge) | Replay key must match document_text or fail loud |

## Agreements
- Named hostile suite is the ENFORCE artifact for the advisory pack.
- Full-chain forget_poison is mandatory (not optional).
- No v4 edits; never auto-resolve.

## Named conflicts
### Conflict 1 — CONDITIONAL vs APPROVE before CI
- **Positions:** injection-attacker wants green proof; others approve the diff shape.
- **Cost:** Approving blind risks a broken forget_poison; waiting costs a review cycle.
- **Decision (human):** **proceed-with-conditions** — PR may open; Adversarial Review sign-off (APPROVE merge) only after `uv run pytest tests/test_gei12_hostile.py` is green (or documented equivalent CI). Failures in forget_poison / kind stamp are must-fix, not xfail.
- **Rationale:** Matches DA challenge and WS-2a gate discipline.
- **Accepted by:** Adversarial Review

## Devil's-advocate challenge
- **Disposition:** Condition above — replay/document_text mismatch fails loud; fix test mapping, never weaken forget postcondition.

## Residual risks accepted
- Verbatim quote_span storage — revisit when evidence UI ships.
- Live advisory injection — deferred with named trigger (key + --run-live advisory case).
- `advisory_group_key` empty-cve stringify — track; engine path covered.

## Outcome
**proceed-with-conditions** — merge after offline hostile suite green; Adversarial Review comments APPROVE on the PR when green. Do not ping Eric unless that gate would block M0 and needs human escalation.
