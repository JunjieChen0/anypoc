# status

Help the user inspect the status of active AnyPoC runs by surveying tmux sessions and reporting on a chosen one.

## Steps

1. List all tmux sessions whose name starts with `anypoc-` (hunt, scan, poc, dashboard):

   ```
   tmux ls 2>/dev/null | awk -F: '/^anypoc-/ {print $1}'
   ```

   If there are no matching sessions, tell the user there are no active AnyPoC runs and stop.

2. Show the list to the user. If there is more than one, use AskUserQuestion (if the AskUserQuestion tool is available) to ask which session to inspect (one option per session, plus an option to inspect all of them briefly). If there is exactly one, skip the question and inspect it directly.

3. For each session the user picked, gather basic status:

   a. Capture the tail of the pane:
      ```
      tmux capture-pane -t <session> -p | tail -80
      ```

   b. Parse the session name to infer kind and project:
      - `anypoc-hunt-<project>` → hunt run
      - `anypoc-scan-<project>` → scan run
      - `anypoc-poc-<project>` → poc run
      - `anypoc-dashboard` → dashboard (no project)

   c. If the session maps to a project, peek at the output directory for additional signal (paths are relative to the anypoc repo root):
      ```
      ls -1t output/<project> 2>/dev/null | head -5
      ```
      If a job directory exists, you can also list its contents (`ls` on the most recent job dir) to count bug reports / PoC attempts.

   d. **Scan commit-progress (hunt/scan sessions only).** Find the most recent scan job and report how many commits have been scanned vs. are still pending. The `history` strategy writes per-chunk commit lists to `state/commits/<chunk>.json` and one trajectory file per scanned commit at `logs/phase3_bugs_<sha>.traj.json` — cross-reference the two. Example one-shot script:

      ```
      python3 - <<'PY'
      import json, os, glob
      scans = sorted(glob.glob('output/<project>/scans/*'), key=os.path.getmtime)
      if not scans:
          print('no scan job yet'); raise SystemExit
      job = scans[-1]
      manifest = json.load(open(f'{job}/manifest.json'))
      print(f"job={os.path.basename(job)} strategy={manifest.get('strategy')} status={manifest.get('status')}")
      state_dir = f'{job}/state/commits'
      logs_dir = f'{job}/logs'
      if not os.path.isdir(state_dir):
          print('(no per-commit state — non-history strategy or pre-phase-2)'); raise SystemExit
      scanned = {f.split('phase3_bugs_')[1].rstrip('.traj.json') for f in os.listdir(logs_dir) if f.startswith('phase3_bugs_')}
      total_done = total_pending = 0
      for chunk in sorted(os.listdir(state_dir)):
          entries = json.load(open(f'{state_dir}/{chunk}'))
          shas = [e['sha'][:12] for e in entries]
          done = sum(1 for s in shas if s in scanned)
          pending = len(shas) - done
          total_done += done; total_pending += pending
          print(f"  {chunk}: {done}/{len(shas)}" + (f"  next: {[s for s in shas if s not in scanned][:3]}" if pending else '  ✓'))
      print(f"total: {total_done}/{total_done + total_pending} commits scanned, {total_pending} pending")
      PY
      ```

      For `focused` and `commit-pr` strategies there is no per-commit state — just skip this sub-step (the python block already detects that and exits).

      Also count bug reports produced so far:
      ```
      ls output/<project>/scans/<job>/reports/ 2>/dev/null | wc -l
      ```

4. Summarize for the user in a few lines per session:
   - Session name, kind (hunt/scan/poc/dashboard), and project (if any).
   - Whether it looks healthy, stuck, or errored — base this on the captured pane (look for stack traces, `Error:`, `Traceback`, non-zero exits, or a pane that is silent for a long time vs. actively producing output).
   - The most recent meaningful line(s) of output (1-3 lines is usually enough).
   - For hunt/scan runs: per-chunk commit progress (scanned / total, next few pending shas), bug-report count, scanner cost if visible in `output/.cost`.
   - For poc runs: number of reports processed and how many have a completed attempt.
   - How to attach: `tmux attach -t <session>` (detach with `Ctrl-b d`).

Keep the summary tight. The goal is a quick "what's going on" snapshot, not a full log dump. If the user wants more, they can attach.
