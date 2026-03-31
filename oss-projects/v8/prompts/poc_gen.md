## V8 JS Engine PoC Rules

Goal: produce practical, user-reachable PoCs for V8 bugs, not artificial internal demonstrations.

## Reachability and Realism Requirements

- Prefer PoCs triggered by normal JavaScript input and normal `d8` CLI usage.
- The trigger should be understandable to triagers as a realistic user-controlled path.
- Avoid bugs that depend on obscure, highly internal, or unrealistic invocation patterns.

## Disallowed PoC Style

- No usage of `--allow-natives-syntax` flag
- No standalone C/C++ harnesses that call V8 internals directly.
- No PoCs that require heavy source rewrites or complex engine surgery.
- No fake/demo-only scripts that do not actually trigger the real bug.

## Source Modification Policy

- Keep codebase edits minimal and temporary for debugging only.
- Final PoC must not depend on large or invasive code modifications.
- If you temporarily instrument code, ensure final reproduction evidence is captured from a reasonable run path through `d8`.

## Practical Output Expectations

- Keep the final PoC minimal and reliable.
- Include explicit `d8` run commands.
- Prefer reproducibility and clear user-triggerability over fragile/internal tricks.

## Build Notes

If you need to rebuild V8 after local edits:

```bash
cd /opt/v8/v8
tools/dev/v8gen.py x64.release -- is_asan=true is_lsan=true
autoninja -C out.gn/x64.release d8
```
