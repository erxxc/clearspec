# devils-advocate — advisory pack precommit

## Challenge
Plan DA required a full ingest→forget seam. The suite includes it. Remaining hole: **ReplayModelClient may not receive the exact `document_text()` string** the extract pipeline builds from operator JSON (`{"text": ...}` wrapping). If the replay key mismatches, `test_forget_refold_poisoned_nvd_json` fails loud — good — but then the gate is blocked until the replay mapping matches extract's source view.

## Disposition
Treat a red forget_poison test as a must-fix before sign-off, not an xfail. If extract wraps JSON differently, fix the test's ReplayModelClient mapping to the real document_text, do not weaken the forget postcondition.
