## Firefox JS Engine PoC Rules

Goal: produce practical, user-reachable PoCs for Firefox JS engine bugs, not artificial internal demonstrations.

## Mandatory Execution Constraint

- Whenever you run the JS shell binary, you MUST include `--fuzzing-safe`.
- Treat this as required for all validation runs and final PoC execution commands.
- If a candidate only triggers without `--fuzzing-safe`, it is out of scope.

## Reachability and Realism Requirements

- Prefer PoCs that are triggered by normal JS input and normal CLI usage.
- The trigger should be understandable to triagers as a realistic user-controlled path.
- Avoid bugs that depend on obscure, highly internal, or unrealistic invocation patterns.

## Disallowed PoC Style

- No standalone C/C++ harnesses that call SpiderMonkey internals directly.
- No PoCs that require heavy source rewrites or complex engine surgery.
- No fake/demo-only scripts that do not actually trigger the real bug.

## Source Modification Policy

- Keep codebase edits minimal and temporary for debugging only.
- Final PoC must not depend on large or invasive code modifications.
- If you temporarily instrument code, ensure the final reproduction evidence is captured from a reasonable run path and still uses `--fuzzing-safe`.

## Practical Output Expectations

- Keep the final PoC minimal and reliable.
- Include explicit run commands that contain `--fuzzing-safe`.
- Prefer reproducibility and clear user-triggerability over fragile/internal tricks.
