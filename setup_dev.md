# AnyPoC dev setup (agent instructions)

You are a coding agent setting up anypoc for a contributor who will work on the codebase itself — running tests, installing pre-commit hooks, iterating on the CLI. This is a superset of [setup.md](setup.md). Execute the steps in order from the cloned repo root.

---

## 1. Ensure Docker is installed and running

Same as [setup.md §1](setup.md#1-ensure-docker-is-installed-and-running). Required: the integration tests exercise the container path.

## 2. Ensure uv is installed

The dev workflow assumes uv (the dev extras and lockfile-pinned environment depend on it). Check:

```bash
command -v uv >/dev/null 2>&1
```

If uv is missing, install it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then re-source the shell (or instruct the user to open a new shell) so `uv` is on PATH. Do not proceed until `uv --version` works.

## 3. Sync the dev environment

From the repo root:

```bash
uv sync --all-extras     # installs anypoc + runtime + dev extras (pytest, ruff, mypy, prek)
```

Verify:

```bash
.venv/bin/anypoc --help >/dev/null
.venv/bin/pytest --version >/dev/null
.venv/bin/prek --version >/dev/null
```

## 4. Install pre-commit hooks

prek is the project's hook runner (it ships in the `dev` extras). Run once after sync:

```bash
.venv/bin/prek install
```

This wires the lint / type-check / format checks into `git commit`.

## 5. Set up direnv if available

Check:

```bash
command -v direnv >/dev/null 2>&1
```

If yes, write a `.envrc` (only if one doesn't already exist) that auto-activates the venv, then allow it:

```bash
[ -f .envrc ] || printf 'source .venv/bin/activate\n' > .envrc
direnv allow
```

If direnv is not installed, skip — the contributor will activate the venv manually.

## 6. Install the bundled agent skills

Run:

```bash
.venv/bin/anypoc install-skills
```

Same behavior as the end-user flow: auto-detects Claude Code / Codex and symlinks the skills directory.

## 7. Ask the user about shell completion

Completion is useful while iterating on the CLI but isn't required. Ask the user with AskUserQuestion (or, if not available in your harness, a plain question) which shell they want completion installed for, with options:

- `zsh`
- `bash`
- `fish`
- `none` (skip)

Based on the answer, run the corresponding command:

```bash
# zsh
.venv/bin/anypoc --install-completion zsh
[ -d ~/.zfunc ] && chmod 755 ~/.zfunc

# bash
.venv/bin/anypoc --install-completion bash

# fish
.venv/bin/anypoc --install-completion fish
```

If they pick `none`, skip this step.

## 8. Build the shared base image

Required for dev — the integration tests and most manual smoke tests run against built images:

```bash
.venv/bin/anypoc infra build
```

Takes 5–10 minutes. Produces `anypoc-base:latest` and `anypoc-common:latest` (~5 GB combined).

---

After step 8, the dev environment is ready. Tell the user:
- The venv is at `.venv/`; pre-commit hooks are wired.
- Run the test suite with `pytest` (or `pytest -x` to stop on first failure, `pytest -k <expr>` to filter).
- The infra-touching tests require `anypoc-base:latest` to exist — already built in step 8.
