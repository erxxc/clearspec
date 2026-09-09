# GEI-12 plan — advisory pack adversarial precommit gate

## Why
WS-2a/WS-2b gated the foundry pack with a named hostile suite + swarm. The advisory pack (schema v5, prompt, operator ingest, grouping) is now on main. M0 does not close without the same ENFORCE posture for NVD/GHSA/KEV-shaped input.

## Shape
1. Plan gate (this directory)
2. Named hostile suite `tests/test_gei12_hostile.py` — construct-in-test, offline, real chain
3. Precommit gate on the suite (+ any min fixes) diff
4. Adversarial Review sign-off before M0 advisory pack is considered gated

## Attack table (ENFORCE)
| Case | Attack | Expect |
|---|---|---|
| self_attest_kind | proposal/JSON claims nvd_cna/cisa_kev | stripped; ingest stamp wins |
| spoofed_nvd | wrong package / ungrounded version bound | drop or conflict |
| never_overwrite | early hostile package attrs vs later honest | conflict; stored kept |
| display | ANSI/OSC/bidi in advisory display fields | `_ansi_safe` / no raw workaround echo |
| forget_poison | poisoned NVD JSON then forget | postcondition; clean fold; quarantine |
| cna_cpe | same URL two kinds | two docs; contradicted group; both members |
| empty_cve | null/empty cve_id | no group collapse |
| marketing_only | equal ranges vs clean | not corroborated |
| kev_vs_range | exploit_status vs affected_range | no cross-class speak |
| golden_regression | GEI-9 goldens | contradicted assessments pinned |
| flag_budget | new advisory flags | ≤1 new class beyond known set |

WS-2a `test_hostile.py` remains foundry-shaped; this suite must not reuse honest goldens as hostile builders.
