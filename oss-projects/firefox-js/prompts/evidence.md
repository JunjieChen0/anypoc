Evidence and reproduction are valid only if execution uses the JS shell with `--fuzzing-safe`.

## Required Checks

- Confirm the reproduced command line explicitly includes `--fuzzing-safe`.
- If the PoC/evidence only works when `--fuzzing-safe` is removed, treat it as out of scope.
- Ensure the trigger path is user-reachable through normal JS input/CLI usage, not internal-only APIs.

## Rejection Guidance

Reject or downgrade confidence when:
- evidence relies on unrealistic internal invocation patterns
- evidence depends on heavy source modifications to force the bug
- command logs are incomplete and do not prove `--fuzzing-safe` usage

## Evidence Quality

For accepted evidence, prefer:
- exact command lines (including `--fuzzing-safe`)
- crash/assertion/sanitizer output tied to the executed PoC
- concise explanation of why the trigger is practical for a real user-controlled input scenario
