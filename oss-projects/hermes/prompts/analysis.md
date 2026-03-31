## Hermes JS Engine Acceptance Rules

Focus only on **reasonable, user-reachable** Hermes JavaScript engine bugs.

The bug must be demonstrably reachable through normal Hermes CLI usage, such as:
- running the `hermes` binary on a crafted JavaScript input file
- running the `hermes` binary on crafted Hermes bytecode input (`.hbc`) produced through normal workflows
- invoking `hermes` with normal CLI arguments

The vulnerable path must stay within Hermes engine implementation scope:
- `lib/`
- related engine headers under `include/hermes/` when directly involved in the bug path

## Reject Conditions

Reject bug reports that require any of the following:
- custom standalone C/C++ harnesses that directly call Hermes embedding APIs/runtime internals
- React Native host integration setup or other embedding-only paths instead of normal `hermes` CLI execution
- large or invasive source code modifications to make the bug trigger
- unrealistic environment assumptions unrelated to normal `hermes` shell usage

Small temporary instrumentation for investigation is acceptable, but a valid bug must still be reproducible without relying on major code changes.

## What to Emphasize for Valid Bugs

For valid bugs, your analysis should clearly state:
- why the trigger is user-reachable in a realistic CLI workflow
- the concrete command style to reproduce using `hermes`
- why the issue remains meaningful without custom embedding harnesses or internal-only APIs
