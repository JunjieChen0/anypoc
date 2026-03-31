# retry-poc

Help the user rerun PoC generation for a single bug report that already has at least one attempt on disk. A retry creates a new `attempt_N+1/` directory that inherits context from the prior attempt (its `help_needed.md`, generation summary, and file listings from `poc/` and `playground/`) plus any extra instructions the user passes in.

Use retry when:
- The agent flagged `help_needed` on a prior attempt and the user wants to continue with more guidance.
- The user wants to rerun a bug with a different angle, a hint, or a correction — without editing the bug report itself.
- A prior attempt errored or produced a weak PoC and the user wants another pass.

Retries are fully user-controlled — there is no max-attempts cap. Each invocation creates exactly one new attempt.

If the user wants to process many reports, send them to the `run-poc` skill instead. If they have no prior attempts on this bug yet, send them to `run-poc` (single-report mode).

## Command

```
anypoc poc retry <project> --bug-report <path-to-report.md> [options]
```

Positional / required:
- `project` — project name.
- `--bug-report / -b PATH` (required) — path to the `.md` bug report under `output/<project>/scans/...`.

## Options

- `--from-attempt / -f N` — attempt number to retry from. Defaults to the latest attempt on disk.
- `--help-context / -c TEXT` — extra instructions appended to the retry context (e.g. "focus on malformed UTF-8 input", "the previous PoC segfaulted in the wrong frame, try X instead"). This is the main lever for steering a retry.
- `--no-knowledge` — disable knowledge features entirely.
- `--read-only-knowledge` — use existing knowledge but skip extraction afterwards.
- `--skip-analysis` — skip the bug-analysis step.
- `--memory-limit / -m` — Docker container memory cap (e.g. `64g`).

## Steps

Use the AskUserQuestion tool for each question below (if the AskUserQuestion tool is available). Ask one question at a time and skip questions whose answer is already obvious.

1. Ask the user which project the bug belongs to. Verify it exists by running `anypoc project status <name>`. If missing, immediately read [setup-project](setup-project.md) and follow its instructions to set up the project before continuing. Do not stop to ask the user whether to set it up — just proceed with the setup reference. Once setup completes, resume retry-poc from this step.

2. Ask for the bug-report path. **This is required.** If the user doesn't know the path, suggest running `anypoc poc status <project>` to list reports, then look under `output/<project>/<bug-stem>/attempt_*/` for existing attempts. Verify the path exists before continuing.

3. Confirm there is at least one existing attempt for that bug. If the bug's output dir has no `attempt_*/` subdirs yet, retry is the wrong command — redirect the user to the `run-poc` skill.

4. Ask whether the user wants to retry from the latest attempt (default) or a specific `--from-attempt` number. If the last attempt has status `help_needed`, mention that and recommend retrying from it.

5. Ask for `--help-context`. This is the most useful retry knob. Encourage the user to write 1–3 sentences describing what to change, what to try differently, or what the previous attempt missed. If the prior attempt was `help_needed`, the agent's `help_needed.md` is already included automatically — the user's `--help-context` supplements it. It is fine to skip if the user just wants to rerun as-is.

6. Ask about knowledge handling only if the user hints at non-defaults (debugging, noisy knowledge base).

7. Show the user the final command. Quote the help-context value. Examples:

   ```
   anypoc poc retry firefox -b output/firefox/scans/history-abc12345/reports/my-bug.md
   ```

   ```
   anypoc poc retry sqlite -b output/sqlite/scans/.../my-bug.md -c "the previous PoC relied on a debug assertion; try to trigger the out-of-bounds read directly"
   ```

   ```
   anypoc poc retry openssl -b output/openssl/scans/.../my-bug.md --from-attempt 2 -c "start from attempt 2's PoC and add the missing cleanup step"
   ```

8. Use AskUserQuestion (if the AskUserQuestion tool is available) to ask whether you should launch the retry yourself or just hand the user the commands to run themselves. Two options:

   - **Launch in tmux for me** — you run `tmux new-session -d -s anypoc-retry-<bug-stem> '<the command>'` directly. If a session named `anypoc-retry-<bug-stem>` already exists, tell the user and ask whether to attach (`tmux attach -t anypoc-retry-<bug-stem>`) or kill it first (`tmux kill-session -t anypoc-retry-<bug-stem>`). After launching, tell the user the session name, attach command, and that they can detach with `Ctrl-b d`.
   - **Just give me the commands** — print BOTH:
     - Raw command (runs in the current terminal, attached):
       ```
       <the command>
       ```
     - Same command wrapped in detached tmux (for long retries):
       ```
       tmux new-session -d -s anypoc-retry-<bug-stem> '<the command>'
       ```
       Then attach with `tmux attach -t anypoc-retry-<bug-stem>` (detach with `Ctrl-b d`).

   After the retry is launched (either way), the user can inspect the new attempt with `anypoc poc status <project> --bug-report <path>`.
