# dashboard

Help the user launch the AnyPoC web dashboard.

The dashboard is a long-running Vite dev server (plus a backing API server and CAW trajectory viewer). By default it runs in the foreground and blocks the terminal, but it also has a built-in `--headless` mode that detaches into the background and writes logs to a file. Your job is to figure out whether the user needs any non-default options, then either print a ready-to-run command or launch it.

## Command

```
anypoc dashboard [--port N] [--install] [--output-dir PATH] [--headless] [--log-file PATH]
```

Options:
- `--port / -p` (default `8501`) — port the dev server listens on. Change this if 8501 is already in use or the user wants to run multiple dashboards.
- `--install / -i` — run `npm install` before starting. Needed on first run, after pulling new frontend dependencies, or if the previous start failed with missing modules.
- `--output-dir / -o` — directory the dashboard watches for scan/PoC results. Defaults to the standard AnyPoC output directory; only override if the user keeps results somewhere non-standard.
- `--headless / -H` — fork into the background, detach from the terminal, and redirect all output to `--log-file`. Prints the PID, log path, and URL before exiting. Stop it later with `kill <pid>`.
- `--log-file / -l` (default `<repo>/output/logs/dashboard.log`, where `<repo>` is the anypoc checkout) — where headless mode writes its log. Each run appends a timestamped header so you can distinguish runs. Ignored when not in headless mode.

There is also `anypoc dashboard build`, which builds the frontend for production instead of launching the dev server. Only use it if the user explicitly asks to build (not run) the dashboard.

## Steps

Use the AskUserQuestion tool for each question below (if the AskUserQuestion tool is available). Ask one question at a time, and skip questions whose answer is already obvious from the user's request.

1. Ask whether the user wants to launch with defaults or customize options. If they want defaults, skip to step 3 with the command `anypoc dashboard`.

2. If customizing, ask only about the options that matter to them:
   - Port — only ask if they hinted at a conflict or want a specific port.
   - `--install` — ask if this is their first time running the dashboard, they just pulled changes, or a previous start failed on missing modules.
   - `--output-dir` — ask only if they mentioned a non-standard results location.
   - `--log-file` — only ask if the user mentioned wanting logs in a specific place; otherwise the default is fine.

3. Show the user the final command, e.g.:

   ```
   anypoc dashboard
   ```

   ```
   anypoc dashboard --port 9000 --install
   ```

4. Use AskUserQuestion (if the AskUserQuestion tool is available) to ask the user how they want to run it. Offer three options:
   - **Copy it** — just leave the command for them to run manually in the foreground.
   - **Headless** — add `--headless` and run it yourself. Preferred for "just keep it running" cases because the dashboard's built-in headless mode handles logging and detachment directly (no tmux needed).
   - **tmux** — run it in a detached tmux session. Useful if the user wants to attach later and watch live output, or if headless mode fails for some reason.

5. If the user chose **headless**, execute the command directly (it returns immediately):
   ```
   anypoc dashboard --headless [other options]
   ```
   The command's own output will list the PID, log path, and URL. Relay that to the user verbatim, plus:
   - To tail the log: `tail -f output/logs/dashboard.log` (run from the anypoc repo root, or use whatever `--log-file` they chose).
   - To stop it: `kill <pid>`.

6. If the user chose **tmux**, **do not execute `tmux new-session` yourself** — give the user the command to run. Present:

   ```
   tmux new-session -d -s anypoc-dashboard '<the command>'
   ```

   Then tell the user:
   - Attach: `tmux attach -t anypoc-dashboard` (detach with `Ctrl-b d`).
   - Open **http://localhost:\<port\>** in their browser (use whatever port was chosen; default 8501).
   - Stop: `tmux kill-session -t anypoc-dashboard`.
   - If a session named `anypoc-dashboard` already exists, the user should either attach or kill it first.
