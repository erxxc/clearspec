# pragmatist-shipper — advisory pack plan

**Verdict: APPROVE** (with suite as DoD)

## Findings
1. Ship the named suite; do not reopen GEI-7/9 design. Prefer fail-loud tests that prove existing defenses over new product code.
2. Reuse GEI-11 golden helpers for the honest regression pin; construct hostile JSON in-test.
3. Skip live/network; offline ENFORCE is enough for M0 gate. `@live` advisory injection can wait for a named trigger.

## Risk others will miss
Over-building a second foundry-style 20-case suite delays M0. Cap at the ticket-named surfaces + golden regression + flag budget.
