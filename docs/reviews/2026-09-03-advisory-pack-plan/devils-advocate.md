# devils-advocate — advisory pack plan

## Challenge
The three angle reviewers agree the suite is the gate. Consensus risk: **tests that only restate unit tests already in `test_gei7_review` / `test_gei9_corroborate`**, while missing the filesystem seam (ingest JSON → sidecar → extract → forget → refold) where WS-2a found real bugs (fold order, silent non-retraction).

## Disposition needed
At least one case MUST run the full `ingest_file` (NVD-shaped JSON) → `run_extract` (replay) → `forget` → postcondition path. Kind self-attest must poison sidecar/JSON keys the way GEI-11 already probes, then prove extract still stamps ingest kind.

If the suite is “analyze-only ClaimView toys,” this gate is theater.
