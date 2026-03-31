## V8 JS Engine Acceptance Rules

Focus only on **reasonable, user-reachable** V8 JS engine bugs.

The bug must be demonstrably reachable through normal JS shell usage, such as:
- running the `d8` binary on a crafted JS input file
- invoking `d8` with normal CLI arguments

The run path must stay within V8 engine scope (`src/` codebase), and execution should avoid unrealistic debug-only/internal-only setups.

## Reject Conditions

Reject bug reports that require any of the following:
- for experimental feature
- overly complex internal-only APIs or unrealistic privileged internals not expected for normal user input
- custom standalone C/C++ harnesses that directly call V8 internals
- large or invasive source code modifications to make the bug trigger
- unrealistic environment assumptions unrelated to normal `d8` usage (e.g. requires OOM, hardware failure)

Small temporary instrumentation for investigation is acceptable, but a valid bug must still be reproducible without relying on major code changes.

## What to Emphasize for Valid Bugs

For valid bugs, your analysis should clearly state:
- why the trigger is user-reachable in a realistic workflow
- why the issue remains meaningful without special internal-only harnesses
