# find-bugs

Help the user build an `anypoc scan run` command to find bugs in a project.

AnyPoC has three bug-scanning strategies. Your job is to ask the user a few questions, pick the right strategy, and output a ready-to-run command.

## Strategies

### history
Mine git history within a time range for bug-fix commits, then scan each commit for related bugs.
Parameters:
- `time_range` (required) — natural-language time range, e.g. "last 6 months" or "2024-01-01 to 2024-12-31"
- `commit_picker_instructions` (optional) — guidance for which commits to pick (e.g. "prefer parser fixes over build fixes")
- `bug_hunter_instructions` (optional) — guidance for the per-commit bug hunter (e.g. "focus on memory safety issues")

### focused
Scan specific files, functions, or features described in natural language.
Parameters:
- `instruction` (required) — what to look for, where, and what bug types matter

### commit-pr
Scan a single git commit or pull request for bugs introduced by the change.
Parameters:
- `ref` (required) — commit SHA, branch, tag, or "pr/<number>"
- `instruction` (optional) — what bug types to focus on, additional context

## Common options

All strategies also accept:
- `--project / -p` (required) — project name
- `--source-code-dir` — path to the repo (defaults to ~/{project})
- `--spend-limit` — max dollar spend for this run
- `--force` — wipe and recreate the scan job directory if it already exists

## Steps

Use the AskUserQuestion tool for each question below (if the AskUserQuestion tool is available). Ask one question at a time.

1. Ask the user what project they want to scan (`-p`).

   Verify the project exists by running `anypoc project status <name>` (exits non-zero if not initialized). If missing, immediately read [setup-project](setup-project.md) and follow its instructions to set up the project before continuing. Do not stop to ask the user whether to set it up — just proceed with the setup reference. Once setup completes, resume find-bugs from this step.

2. Ask what they want to scan for. Based on their answer, recommend a strategy:
   - If they want to mine commit history for patterns: **history**
   - If they want to audit specific code areas or features: **focused**
   - If they want to review a specific commit or PR: **commit-pr**
   Use AskUserQuestion (if the AskUserQuestion tool is available) to confirm the strategy choice with the user.

3. Ask for the strategy-specific required parameters. For optional parameters, ask only if the user's earlier answers suggest they have specific preferences (don't ask about every optional param mechanically).

4. Ask if they want to set a spend limit or any other options.

5. Show the user the final command. Format:

```
anypoc scan run <strategy> -p <project> [key=value ...] [--spend-limit N] [--force]
```

Strategy parameters are passed as positional `key=value` arguments. Quote values that contain spaces. For example:

```
anypoc scan run history -p openssl time_range="last 6 months" commit_picker_instructions="prefer memory-safety fixes"
```

```
anypoc scan run focused -p sqlite instruction="audit the SQL parser for integer overflow and buffer overread bugs"
```

```
anypoc scan run commit-pr -p openssl ref=abc123
```

6. Use AskUserQuestion (if the AskUserQuestion tool is available) to ask whether you should launch the run yourself or just hand the user the commands to run themselves. Two options:

   - **Launch in tmux for me** — you run `tmux new-session -d -s anypoc-scan-<project> '<the command>'` directly. If a session named `anypoc-scan-<project>` already exists, tell the user and ask whether to attach (`tmux attach -t anypoc-scan-<project>`) or kill it first (`tmux kill-session -t anypoc-scan-<project>`). After launching, tell the user the session name, attach command, and that they can detach with `Ctrl-b d`.
   - **Just give me the commands** — print BOTH:
     - Raw command (runs in the current terminal, attached):
       ```
       <the command>
       ```
     - Same command wrapped in detached tmux (runs in the background so the user can keep working):
       ```
       tmux new-session -d -s anypoc-scan-<project> '<the command>'
       ```
       Then attach with `tmux attach -t anypoc-scan-<project>` (detach with `Ctrl-b d`).

   After the run is launched (either way), tell the user they can check progress with the `status` subcommand.
