# setup-project

You are helping the user set up the AnyPoC project "$1".

AnyPoC is a tool that finds bugs in open-source software and generates proof-of-concept exploits. Each project targets a specific software and needs a build environment (Dockerfile) and custom prompts that guide the AI agents through analysis, PoC generation, and evidence checking.

== Step 1: Check the in-tree OSS-projects bundle for an existing config ==

Prebuilt project configs ship inside the anypoc repo under `oss-projects/`. Before doing anything else, check whether `$1` already has one. All paths in this step are relative to the anypoc repo root — `setup-project` should be run from inside the cloned anypoc checkout.

1. Check whether `oss-projects/$1/` exists.

2. If it exists, use AskUserQuestion (if the AskUserQuestion tool is available) to ask the user whether to:
   - **Copy the prebuilt config (Recommended)** — skip the interactive questions and use the existing Dockerfile + prompts.
   - **Run interactive setup anyway** — ignore the prebuilt config and collect answers from scratch.

   If the user picks copy:
   - Run `anypoc project init $1` to create the config directory and templates.
   - Overwrite the newly-created config dir with the bundled files, e.g. `cp -r oss-projects/$1/. <config_dir>/` (use the config dir path printed by `anypoc project init`).
   - Skip Steps 2 and 3 and jump straight to Step 4 (build).

   If the user picks interactive setup, continue with Step 1b below.

== Step 1b: Initialize the project ==

Run: `anypoc project init $1`

This creates the project config directory with template files. Read its output to learn the config directory path.

== Step 2: Gather information from the user ==

Use the AskUserQuestion tool (if the AskUserQuestion tool is available) to ask the following questions one by one. Ask follow-ups if an answer is ambiguous.

1. What is the project's git repository URL? What build system does it use (cmake, autoconf, meson, etc.)? Any special build dependencies?

2. What counts as valid evidence for proving a bug? What constitutes a valid PoC? (crash, sanitizer report, unexpected output, etc.) How should the PoC be structured? (standalone C file, Python script, crafted input file, etc.) Any specific oracles? (ASan, UBSan, MSan, assertion failures, etc.)

3. Anything that should make a bug report be rejected during PoC analysis? For example, areas of the codebase where PoC reproduction is unreliable (experimental features, deprecated code, test-only code, etc.) or other constraints the analyzer should enforce.

== Step 3: Write all the files ==

Once you have the user's answers, write all files below. Keep prompts concise and actionable -- they are injected into agent system prompts as project-specific instructions.

Build environment:
- Dockerfile -- Dockerfile that clones source, installs deps, and builds with sanitizers. Must use user "playground" with home `/home/playground`. Clone the source directly into the WORKDIR `/opt/<name>` (use `git clone <url> .`) — do NOT introduce an extra `src/` subdirectory. The source tree should live at `/opt/<name>/`, not `/opt/<name>/src/`.

  **Picking the base image.** Read both `src/anypoc/infra/base.Dockerfile` and `src/anypoc/infra/common.Dockerfile` and pick whichever is the smallest image that already covers this project's build/debug needs. Default to `FROM zzjas/anypoc-common:latest` — it ships the heavy C/C++/Rust toolchain (cmake, ninja, autoconf, clang, llvm, gdb/lldb, valgrind, rustup with stable, sanitizer env, etc.), which is what most native projects need. Only use `FROM zzjas/anypoc-base:latest` when the project genuinely needs nothing beyond what base provides (git, curl, build-essential, python3, vim, jq, the anypoc venv) — for example, a pure-Python project, or a project that installs its entire toolchain itself. When in doubt, prefer common; the slightly larger image is cheaper than re-discovering missing tooling mid-build.
- paths.md -- source code path and built binary path inside the container. Source path should be `/opt/<name>` (not `/opt/<name>/src`).

PoC prompts (prompts/):
These guide agents that validate bugs and generate exploits.
- analysis.md -- how to determine if a reported bug is real vs. false positive
- poc_gen.md -- how to craft a minimal, working proof-of-concept
- evidence.md -- how to independently reproduce and validate a PoC

Exclusion rules from question 3 should be incorporated into the PoC prompts (e.g., analysis.md should reject bugs in excluded areas).

Leave a prompt file empty if the user has no specific guidance for that step.
Do not write bug_report_format.md -- it already has a default template.

== Step 4: Build the Docker image ==

Run: `anypoc project build $1`

If the build fails, read the error, fix the Dockerfile, and retry. Keep iterating until the build succeeds. If a failure requires information or a decision from the user (e.g., which version to pin, which optional features to enable), use AskUserQuestion (if the AskUserQuestion tool is available) to ask them.
