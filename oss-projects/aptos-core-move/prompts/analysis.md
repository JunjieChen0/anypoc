## Move Compiler and Runtime Acceptance Rules

Focus only on bugs in the **Move compiler and runtime**, specifically code under `third_party/move/`.

The bug must be demonstrably reachable through normal `aptos move` subcommand usage, such as:
- running `aptos move compile` on a crafted Move source package
- running `aptos move test` on a crafted Move package
- running `aptos move run-script` on a crafted Move script
- running `aptos move disassemble` or `aptos move decompile` on crafted bytecode

The execution path must trace into `third_party/move/` — the Move compiler, bytecode verifier, or Move VM. Bugs whose root cause lies outside this subtree (e.g., in aptos blockchain logic, consensus, storage, or networking code) are out of scope.

## Reject Conditions

Reject bug reports that require any of the following:
- standalone Rust harnesses that call Move VM or compiler APIs directly (not via `aptos move` CLI)
- network connectivity, a running Aptos node, or on-chain state
- custom blockchain modules or framework modifications
- OOM to trigger
- race conditions or timing-dependent behavior
- bugs that only appear outside the `third_party/move/` subtree

## What to Emphasize for Valid Bugs

For valid bugs, your analysis should clearly state:
- the exact `aptos move` command and crafted input that reproduces the bug
- the stack trace or panic location, confirming it falls within `third_party/move/`
- why the trigger is user-reachable (a developer compiling or testing Move code)
