# AnyPoC setup (agent instructions)

You are a coding agent setting up anypoc for a user who just ran `git clone`. Execute the steps in order from the cloned repo root. After each step, verify before moving to the next. Skip a step only if its verification command already passes.

Before running any command, briefly explain to the user what you are about to do and why.

If the user mentioned wanting to develop on anypoc itself (run tests, install hooks, work on the codebase), use [setup_dev.md](setup_dev.md) instead — it's a superset of this guide.

---

## 1. Ensure Docker is installed and running

Check:

```bash
docker info >/dev/null 2>&1
```

If exit code is non-zero, Docker is missing or its daemon is not running. Detect the user's OS with `uname -s` and tell them how to install:

- `Linux` → point to `https://docs.docker.com/engine/install/`. For Ubuntu/Debian the one-liner is `curl -fsSL https://get.docker.com | sh` followed by `sudo usermod -aG docker $USER` and a re-login.
- `Darwin` → point to `https://docs.docker.com/desktop/install/mac-install/`.
- Windows (detected via `MINGW`/`MSYS`/`CYGWIN` in `uname -s`, or by user mention) → tell the user **anypoc has never been tested on Windows** and is not supported by this guide. Ask them to install Docker, Python 3.10+, and (optionally) uv themselves, set up a venv, and run `pip install -e .` manually. Then stop — do not attempt the rest of this guide on Windows.

Do not attempt to install Docker yourself. Stop and ask the user to install it, then re-run this step. Do not proceed to step 2 until `docker info` exits 0.

## 2. Install anypoc into a Python environment

anypoc must be installed **editable** from this checkout. The runtime mounts `src/` into containers and locates the repo via `pyproject.toml`; a non-editable install breaks both.

First check whether uv is available:

```bash
command -v uv >/dev/null 2>&1
```

**If uv is installed**, use it:

```bash
uv sync                  # creates .venv/ and installs anypoc + runtime deps from uv.lock
```

**If uv is not installed**, fall back to plain pip:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Do not prompt the user to install uv — pip works fine for end users.

After install, check whether `direnv` is available:

```bash
command -v direnv >/dev/null 2>&1
```

If yes, write a `.envrc` (only if one doesn't already exist) that auto-activates the venv, then allow it:

```bash
[ -f .envrc ] || printf 'source .venv/bin/activate\n' > .envrc
direnv allow
```

If direnv is not installed, skip the `.envrc` step — the user will activate the venv manually with `source .venv/bin/activate`.

Verify anypoc is callable:

```bash
.venv/bin/anypoc --help >/dev/null
```

Do not proceed to step 3 if this fails.

## 3. Install the bundled agent skills

Run:

```bash
.venv/bin/anypoc install-skills
```

This auto-detects whether the user has Claude Code and/or Codex installed locally and symlinks the bundled `/anypoc` skill set into the appropriate directory (`~/.claude/skills` and/or `~/.agents/skills`). Do **not** pass `--install-completion` here — completion install is reserved for the dev setup.

If the command reports no agents detected, tell the user and stop — they need either Claude Code or Codex on the host before skills are useful.

---

After step 3, setup is complete. Tell the user:

- They will not need to run the `anypoc` CLI directly. The skills installed in step 3 handle everything — building the shared base image, setting up project Docker images, running scans/hunts/PoCs, launching the dashboard, checking status. The user just talks to Claude Code or Codex in natural language.
- To use anypoc in **Claude Code**: open Claude Code in this repo and invoke the `/anypoc` slash command. Example: `/anypoc hunt firefox use the last 6 months of commit history to find memory-safety bugs`. Other examples: `/anypoc setup-project openssl`, `/anypoc dashboard`, `/anypoc status`.
- To use anypoc in **Codex**: same skill set, different invocation prefix. Use `$anypoc` instead of `/anypoc`. Example: `$anypoc hunt firefox ...`.
- The first time the user runs a hunt, the skill will walk them through any one-time setup (building the base image, copying a project config from `oss-projects/`, building the project image). They do not need to do this in advance.
- The full set of subcommands is documented inline in the skills — the user can run `/anypoc help` (Claude Code) or `$anypoc help` (Codex) to list them.
