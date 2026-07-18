# Swarm review gates — audit trail

A **gate** is an adversarial review run before a workstream is committed. A swarm
of biased reviewers each attacks the target from one angle, an advocate attacks
their consensus, and the main session (the orchestrator) merges the raw opinions
into a resolution. The raw opinions **and** the resolution are committed with the
workstream.

Why commit the raw opinions and not just the decision: it makes the record
auditable. Later you can tell **"the swarm caught this and we accepted the risk"**
apart from **"nobody looked."** The resolution is a lightweight decision record —
findings and disposition — not a rubber stamp.

## Reviewers

Defined in `.claude/agents/` (they travel with the repo). They are invoked
**only** explicitly as part of a gate — never proactively.

| Role | Bias (overweights) | Blind spot |
|---|---|---|
| `injection-attacker` | prompt-injection, data-exfil, hostile input | usability / delivery |
| `schema-purist` | schema fidelity, normalization, validation rigor | shipping |
| `pragmatist-shipper` | simplicity, DoD completion, deleting redundancy | security |
| `devils-advocate` | attacks the *consensus* (runs last, reads the others) | — |

The reviewers are deliberately in tension — `injection-attacker` wants more
defensive validation; `pragmatist-shipper` wants to delete validation that
duplicates the schema. **That conflict is the signal**, not noise to be averaged
away.

## Gate procedure

1. Create a run directory: `docs/reviews/YYYY-MM-DD-<workstream>-<plan|precommit>/`
   (e.g. `2026-07-17-extraction-plan/`). Two gate points per workstream:
   `-plan` (before writing code, target = the plan) and `-precommit` (before
   committing, target = the diff).
2. Copy `_templates/manifest.md` into it and fill it in (what was reviewed, git
   ref, roles invoked).
3. Invoke the three angle reviewers, giving each the target and its own output
   path (`<role>.md` in the run dir). Each writes its **full** opinion to that
   file and returns only a verdict line + one-sentence summary.
4. Invoke `devils-advocate` last, pointing it at the run directory so it reads
   the others; it writes `devils-advocate.md`.
5. The **main session** writes `resolution.md` from `_templates/resolution.md`,
   per the merge rules below.
6. Commit the whole run directory with the workstream.

## Merge rules (for `resolution.md`)

- **Agreements are highlighted** — where all reviewers concur, say so plainly.
- **Conflicts are named, with their cost — never averaged.** A split verdict is
  recorded as a split, with what each side costs. Do not blend "block" and
  "approve" into "conditional" to make the tension disappear.
- **Every named conflict records the human's decision and rationale.** The
  orchestrator does not silently adjudicate between its own reviewers — it
  surfaces the conflict and the human makes the call, which is written down.
- **Residual risks are listed as accepted**, with the reason and a revisit
  trigger — so an accepted risk is visibly accepted, not forgotten.

## Layout

```
docs/reviews/
  _templates/
    manifest.md
    resolution.md
  2026-07-17-extraction-plan/
    manifest.md          # what was reviewed (plan|diff), git ref, roles invoked
    injection-attacker.md
    schema-purist.md
    pragmatist-shipper.md
    devils-advocate.md
    resolution.md        # merge: agreements, named conflicts, decision + why
  2026-07-17-extraction-precommit/
    ...
```

Run directories are created per gate. This repo ships the convention and the
templates only — reviewer opinions are never pre-written, so an empty gate is
unambiguously "nobody looked."
