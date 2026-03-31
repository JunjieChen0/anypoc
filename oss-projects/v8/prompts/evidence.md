Evidence and reproduction are valid only if execution uses the V8 shell (`d8`) with concrete command logs.

## Required Checks

- Confirm the reproduced command line explicitly invokes `d8`.
- Ensure the trigger path is user-reachable through normal JS input/CLI usage, not internal-only APIs.
- Confirm results include crash/assertion/sanitizer output tied to the executed PoC.

## Rejection Guidance

Reject or downgrade confidence when:
- evidence relies on unrealistic internal invocation patterns
- evidence depends on heavy source modifications to force the bug
- command logs are incomplete and do not prove the `d8` execution path

## Evidence Quality

For accepted evidence, prefer:
- exact command lines for reproduction
- crash/assertion/sanitizer output tied to the executed PoC
- concise explanation of why the trigger is practical for a real user-controlled input scenario
