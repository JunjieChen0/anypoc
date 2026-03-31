## Firefox JS Engine Acceptance Rules

Focus only on **reasonable, user-reachable** Firefox JS engine bugs.

The bug must be demonstrably reachable through normal JS shell usage, such as:
- running the `js` binary on a crafted JS input file
- invoking `js` with normal CLI arguments

The run path must stay within the JS engine scope (`js/` codebase), and any execution path must be valid with:
- `--fuzzing-safe`

If a bug is only reproducible without `--fuzzing-safe`, treat it as out of scope and reject it.

## Reject Conditions

Reject bug reports that require any of the following:
- overly complex internal-only APIs or unrealistic privileged internals not expected for normal user input
- custom standalone C/C++ harnesses that directly call engine internals
- large or invasive source code modifications to make the bug trigger
- unrealistic environment assumptions unrelated to normal JS shell usage

Specific types of bug reports to immediately reject:
- Involves using the flag `--disable-main-thread-denormals`
- Involves parsing ISO style date with lowercase characters
- About GVN not clearing GuardRangeBailouts
- Anything about debugger
- Anything about stale assertion
- Anything related to OOM -- either triggered by OOM or handling OOM


Small temporary instrumentation for investigation is acceptable, but a valid bug must still be reproducible without relying on major code changes.

## What to Emphasize for Valid Bugs

For valid bugs, your analysis should clearly state:
- why the trigger is user-reachable in a realistic workflow
- the concrete command style to reproduce using `--fuzzing-safe`
- why the issue is still meaningful under the `--fuzzing-safe` execution model
