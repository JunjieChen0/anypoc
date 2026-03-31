# run-poc

Help the user build an `anypoc poc run` command to generate proof-of-concept exploits for bugs that have already been found by a scan.

`anypoc poc` consumes bug reports that earlier `anypoc scan` runs wrote to disk. It runs each bug through a Docker-isolated generator that attempts to produce a working PoC (crash input, exploit script, etc.) and extracts knowledge from each attempt to improve future runs.

If the user wants to find bugs AND generate PoCs in one pass (without running scan first), recommend the `hunt` skill instead.

A `poc run` processes each bug report exactly once. To rerun a bug (whether because the agent flagged `help_needed` or because the user wants to change something), use the `retry-poc` skill — retries are user-triggered and unbounded.

## Command

```
anypoc poc run <project> [options]
```

Positional:
- `project` (required) — project name. The command reads bug reports from `output/<project>/scans/*/reports/*.md`.

## Common modes

**Batch over all pending reports (default):**
```
anypoc poc run <project> [--parallel N] [--num-reports M] [--spend-limit $]
```

**Single report:**
```
anypoc poc run <project> --bug-report <path-to-report.md>
```

## Options

- `--bug-report / -b PATH` — process just one report instead of all pending ones. Takes a path to a `.md` file under `output/<project>/scans/...`.
- `--num-reports / -n N` — cap how many pending reports to process in batch mode.
- `--parallel / -p N` (default `1`) — number of bug reports to process concurrently. Each worker runs a separate Docker container, so this is bounded by the host's CPU / memory budget. Typical: `2`–`4`.
- `--no-knowledge` — disable all knowledge features. No prior knowledge is provided to the generator and no new knowledge is extracted. Use when starting fresh or debugging.
- `--read-only-knowledge` — provide existing knowledge but skip extraction afterwards. Use when iterating on the generator without polluting the knowledge base.
- `--skip-analysis` — skip the bug-analysis step and treat every reported bug as valid. Use when you trust the scanner's output.
- `--memory-limit / -m` (e.g. `64g`) — Docker container memory cap. Defaults to about a quarter of host RAM.
- `--spend-limit $` — max dollar spend for this batch run.

## Steps

Use the AskUserQuestion tool for each question below (if the AskUserQuestion tool is available). Ask one question at a time and skip questions whose answer is already obvious from the user's request.

1. Ask the user which project they want to generate PoCs for. Tab-completion / existing projects are under `projects/`.

   Verify the project exists by running `anypoc project status <name>` (exits non-zero if not initialized). If missing, immediately read [setup-project](setup-project.md) and follow its instructions to set up the project before continuing. Do not stop to ask the user whether to set it up — just proceed with the setup reference. Once setup completes, resume run-poc from this step.

2. Ask whether they want to run on **all pending bug reports** or **a single specific report**.
   - If single: ask for the bug-report path. If they don't know the path, suggest running `anypoc poc status <project>` first to list pending reports.
   - If all pending: ask whether they want to cap the number (`--num-reports`) or process everything.

3. Ask about parallelism only if they're running in batch mode. Default is sequential (1). Typical values are 2–4.

4. Ask about knowledge handling only if the user hints at something non-default:
   - First-time run on a new project → suggest defaults (knowledge on).
   - Debugging the generator / noisy knowledge base → `--no-knowledge` or `--read-only-knowledge`.
   - They trust the scanner and want faster iteration → `--skip-analysis`.

5. Ask whether they want a spend limit.

6. Show the user the final command. Examples:

   ```
   anypoc poc run openssl --parallel 2
   ```

   ```
   anypoc poc run sqlite --bug-report output/sqlite/scans/history-abc12345/reports/my-bug.md
   ```

   ```
   anypoc poc run firefox --parallel 3 --num-reports 10 --spend-limit 50
   ```

7. Use AskUserQuestion (if the AskUserQuestion tool is available) to ask whether you should launch the run yourself or just hand the user the commands to run themselves. Two options:

   - **Launch in tmux for me** — you run `tmux new-session -d -s anypoc-poc-<project> '<the command>'` directly. If a session named `anypoc-poc-<project>` already exists, tell the user and ask whether to attach (`tmux attach -t anypoc-poc-<project>`) or kill it first (`tmux kill-session -t anypoc-poc-<project>`). After launching, tell the user the session name, attach command, and that they can detach with `Ctrl-b d`.
   - **Just give me the commands** — print BOTH:
     - Raw command (runs in the current terminal, attached):
       ```
       <the command>
       ```
     - Same command wrapped in detached tmux (runs in the background so the user can keep working):
       ```
       tmux new-session -d -s anypoc-poc-<project> '<the command>'
       ```
       Then attach with `tmux attach -t anypoc-poc-<project>` (detach with `Ctrl-b d`).

   After the run is launched (either way), tell the user they can check progress with the `status` subcommand.
