# hunt

Help the user build an `anypoc hunt run` command that scans for bugs AND generates PoCs in a single pass.

Hunt mode runs a scan strategy (same three as `anypoc scan`) and, as each bug report is produced, dispatches it to a bounded PoC worker pool concurrently. The scanner applies backpressure at safe session boundaries so reports don't pile up unboundedly when the PoC pool is saturated.

Use hunt when the user wants to discover bugs AND reproduce them in one run. If they only want bug reports (no PoCs), use the `find-bugs` skill for `anypoc scan`. If they already have reports on disk, use the `run-poc` skill for `anypoc poc`.

## Command

```
anypoc hunt run <strategy> -p <project> [key=value ...] [options]
```

## Strategies

Same three as `anypoc scan`. Pick one based on what the user wants to find.

### history
Mine git history within a time range for bug-fix commits, then scan each commit for related bugs. This is the strategy that benefits most from hunt mode — it produces many reports in batches, so the PoC pool can run in parallel with the scanner.
Parameters:
- `time_range` (required) — e.g. `"last 6 months"` or `"2024-01-01 to 2024-12-31"`.
- `commit_picker_instructions` (optional) — e.g. `"prefer parser fixes over build fixes"`.
- `bug_hunter_instructions` (optional) — e.g. `"focus on memory safety issues"`.

### focused
Scan specific files, functions, or features described in natural language.
Parameters:
- `instruction` (required) — what to look for, where, and what bug types matter.

### commit-pr
Scan a single git commit or pull request for bugs introduced by the change.
Parameters:
- `ref` (required) — commit SHA, branch, tag, or `pr/<number>`.
- `instruction` (optional) — what bug types to focus on.

Note: `focused` and `commit-pr` are one-shot LLM sessions, so hunt mode won't pause them mid-session. The scanner simply streams everything it finds into the PoC pool; the PoC pool's own concurrency cap (`--parallel`) still bounds downstream work. Hunt mode gives the biggest win with `history`, which has natural per-commit boundaries where the scanner can wait.

## Options

Scan-side:
- `--project / -p` (required) — project name. PoC generation needs a project context.
- `--source-code-dir` — repo to scan. Defaults to `~/<project>`.
- `--spend-limit $` — max dollar spend for the scan side of the run.
- `--force` — wipe and recreate the scan job directory if it already exists.

PoC-side / concurrency:
- `--parallel / -n N` (default `3`) — max concurrent in-flight PoC tasks. This is also the scanner's backpressure bound: the scanner pauses between sessions if this many PoCs are already in flight. Typical: `2`–`4`, bounded by host CPU / RAM.
- `--no-knowledge` — disable knowledge features entirely.
- `--read-only-knowledge` — use existing knowledge but skip extraction.
- `--skip-analysis` — skip bug analysis and treat every reported bug as valid.
- `--memory-limit / -m` (e.g. `64g`) — Docker container memory cap.

## Steps

Use the AskUserQuestion tool for each question below (if the AskUserQuestion tool is available). Ask one question at a time.

1. Ask the user which project they want to hunt in (`-p`).

   Verify the project exists by running `anypoc project status <name>` (exits non-zero if not initialized). If missing, immediately read [setup-project](setup-project.md) and follow its instructions to set up the project before continuing. Do not stop to ask the user whether to set it up — just proceed with the setup reference. Once setup completes, resume hunt from this step.

2. Ask what they want to hunt for. Recommend a strategy based on their answer:
   - Mine commit history for patterns → **history** (best fit for hunt mode).
   - Audit specific code areas → **focused**.
   - Review a specific commit or PR → **commit-pr**.
   Confirm the choice with AskUserQuestion (if the AskUserQuestion tool is available).

3. Ask for the strategy's required parameters. Ask about optional parameters only if the user's earlier answers suggest specific preferences.

4. Ask about concurrency (`--parallel`). Default is 3. Higher values mean more parallel PoC containers (more CPU/RAM). If the user has a big machine, 4 is reasonable; if they're unsure, stick with 3.

5. Ask about spend limit and knowledge handling only if the user hints at non-defaults (e.g. first-time run, debugging, tight budget).

6. Show the user the final command. Strategy parameters are positional `key=value` arguments. Quote values with spaces. Examples:

   ```
   anypoc hunt run history -p openssl time_range="last 6 months" --parallel 3
   ```

   ```
   anypoc hunt run focused -p sqlite instruction="audit the SQL parser for integer overflow bugs" --parallel 2
   ```

   ```
   anypoc hunt run commit-pr -p openssl ref=abc123 --parallel 2
   ```

7. Use AskUserQuestion (if the AskUserQuestion tool is available) to ask whether you should launch the run yourself (recommended for hunt since it's long-running) or just hand the user the commands to run themselves. Two options:

   - **Launch in tmux for me** — you run `tmux new-session -d -s anypoc-hunt-<project> '<the command>'` directly. Confirm the session name first; if a session named `anypoc-hunt-<project>` already exists, tell the user and ask whether to attach (`tmux attach -t anypoc-hunt-<project>`) or kill it first (`tmux kill-session -t anypoc-hunt-<project>`). After launching, tell the user the session name, attach command, and that they can detach with `Ctrl-b d`.
   - **Just give me the commands** — print BOTH:
     - Raw command (runs in the current terminal, attached):
       ```
       <the command>
       ```
     - Same command wrapped in detached tmux (recommended for hunt since runs are long — scan + multiple PoCs):
       ```
       tmux new-session -d -s anypoc-hunt-<project> '<the command>'
       ```
       Then attach with `tmux attach -t anypoc-hunt-<project>` (detach with `Ctrl-b d`).

   After the run is launched (either way), tell the user they can check progress with the `status` subcommand.
