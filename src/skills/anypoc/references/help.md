# help

List every AnyPoC skill subcommand with a one-line description so the user can decide what to do next. This is a pure informational response — do not invoke any `anypoc` commands and do not ask follow-up questions.

Print the list below (verbatim is fine; stay concise and scannable):

## AnyPoC skill subcommands

- `/anypoc setup-project <name>` — interactively set up a new project (checks the prebuilt OSS-projects repo first, otherwise collects Dockerfile + prompts + build config from scratch, then builds the image).
- `/anypoc hunt <project>` — scan for bugs **and** generate PoCs concurrently in a single pass. Best default when you want end-to-end results.
- `/anypoc find-bugs <project>` — scan only; produces bug reports without generating PoCs. Use when you want to review findings before spending PoC budget.
- `/anypoc run-poc <project>` — generate PoCs from an existing scan's bug reports on disk. Use after `find-bugs`.
- `/anypoc retry-poc <project>` — rerun PoC generation on a specific bug (new attempt), optionally with extra guidance. Use when a previous PoC attempt failed or needs a hint.
- `/anypoc dashboard` — launch the AnyPoC web dashboard at http://localhost:8501. Browse discovered bugs, inspect PoCs, build commands interactively.
- `/anypoc status` — list active `anypoc` tmux sessions and summarize progress of an in-flight run.

After printing, invite the user to pick one by running the corresponding slash command, or to describe what they want to do in plain English.
