<div align="center">
<img src="src/dashboard/dashboard/public/anypoc.png" alt="AnyPoC" style="height: 8em"/>

**Automatically find and reproduce software vulnerabilities with AI-powered proof-of-concept generation.**

<a href="https://arxiv.org/abs/2604.11950"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2604.11950-b31b1b.svg?style=flat-square" /></a>
<a href="https://buglist-a2470.web.app/tool/anypoc"><img alt="Bugs Found" src="https://img.shields.io/endpoint?url=https://buglist-a2470.web.app/badge/bugs-found?tool=anypoc&style=flat-square" /></a>
<a href="https://buglist-a2470.web.app/tool/anypoc"><img alt="Bugs Confirmed" src="https://img.shields.io/endpoint?url=https://buglist-a2470.web.app/badge/bugs-confirmed?tool=anypoc&style=flat-square" /></a>
<a href="https://buglist-a2470.web.app/tool/anypoc"><img alt="Bugs Fixed" src="https://img.shields.io/endpoint?url=https://buglist-a2470.web.app/badge/bugs-fixed?tool=anypoc&style=flat-square" /></a>

[✨ Key Features](#-key-features) | [🚀 Setup](#-setup) | [🤖 Using AnyPoC](#-using-anypoc) | [📚 How it works](#-how-it-works) | [🙏 Credits](#-credits)

</div>

## ✨ Key Features

- **Real bugs, real PoCs.** Findings come with a reproducible Proof-of-Concept — verified, not hallucinated.
- **Sandboxed.** Agents auto-figure out the Docker image, so crashing binaries never touch your host.
- **Agent-agnostic.** Orchestrates your trusted Claude Code or Codex under the hood.

AnyPoC has found 130+ bugs across large real-world systems like Firefox, OpenSSL, FFmpeg, and more — see the running list [here](https://buglist-a2470.web.app/tool/anypoc).

## 🚀 Setup

Clone the repo, then let your coding agent handle the rest:

```bash
claude "Setup AnyPoC following setup.md"
# or
codex "Setup AnyPoC following setup.md"
```


## 🤖 Using AnyPoC

AnyPoC is designed to be driven by a coding agent like Claude Code or Codex through **skills** — you describe what you want in natural
language and the skill figures out the right `anypoc` invocation for you. Under the hood, the skill shells out to your locally installed `claude` or `codex` CLI, so it uses whichever account/credentials you've already set up — no separate API key for AnyPoC.

The examples below use Claude Code's `/anypoc` slash-command syntax. In Codex, use `$anypoc` instead of `/anypoc` — everything else is the same.

The first time you run AnyPoC against a project, it will walk you through setting up the project's Docker environment (Dockerfile, source paths, build flags) interactively with your guidance. Subsequent runs reuse that setup.

### Generate a PoC for an existing bug report

If you already have a bug report and just want AnyPoC to reproduce it, point the skill at it. The report can be a local file, a URL (issue tracker, advisory, blog post), or just pasted text:

```
/anypoc generate a PoC for firefox using the bug report at ./reports/spidermonkey-oob-read.md
```

AnyPoC spins up the project's Docker image, has its analyzer agent confirm the bug is plausible, generates a minimal PoC, and re-runs it from scratch to record the evidence.

### Hunt for bugs

AnyPoC can also discover bugs from scratch. Give it a project and a high-level description of what to look for:

```
/anypoc hunt firefox use the last 6 months of commit history to find memory-safety bugs in SpiderMonkey
```

This uses the commit-history strategy: the scanner walks git history for bug-fix commits, extracts the underlying patterns, scans the codebase for related vulnerabilities, and streams each bug report into a PoC worker pool — all in one pass.

To view the progress and detected bugs:

```
/anypoc dashboard
```

> [!NOTE]
>
> We are continuously improving AnyPoC and working on more sophisticated bug scanning. Stay tuned for updates!

### Discover more

To find out what AnyPoC can do for you (setup a new project, find bugs without PoCs, retry a specific PoC, launch the dashboard, check status...):

```
/anypoc help
```

## 📚 How it works

<details>
<summary><b>Scanner</b> — how bugs are discovered</summary>

The scanner is the "find" half of AnyPoC. It accepts one of three strategies and produces structured bug reports:

- **history** — Mines git log for bug-fix commits within a time range, extracts the underlying vulnerability patterns, then scans the current codebase for code that looks similar to the pre-fix versions. Best when you want breadth and don't know where to look.
- **focused** — Takes a natural-language description of what to audit (a file, a module, a feature, a class of bug) and drives an LLM session scoped to that area. Best when you already have a hypothesis.
- **commit-pr** — Reviews a single commit or pull request for bugs introduced by the change. Best for pre-merge review or post-mortem of a specific change.

Each strategy emits `BugReport`s incrementally, so downstream consumers (PoC generation, the dashboard) can start working before the scan is finished.

</details>

<details>
<summary><b>PoC generation</b> — how bugs are reproduced</summary>

PoC generation is the "reproduce" half. For each bug report it runs a three-stage pipeline inside a project-specific Docker container:

1. **Analysis** — An analyzer agent reads the report plus the relevant source and decides whether the bug is real or a false positive. Reports rejected here never consume PoC-generation budget.
2. **Generation** — A generator agent crafts a minimal proof-of-concept (crafted input, standalone program, script, …) following the project's `poc_gen.md` guidance, iterating against the target binary until it triggers the bug.
3. **Evidence checking** — An independent agent re-runs the PoC from scratch to confirm reproduction and records the evidence (sanitizer output, crash backtrace, unexpected output) against the project's oracle rules.

In `hunt` mode the scanner and a bounded PoC worker pool run concurrently: as reports are emitted they're dispatched to workers, with backpressure pausing the scanner at safe session boundaries when the pool is saturated.

</details>

<details>
<summary><b>CLI reference</b> — if you'd rather use <code>anypoc</code> directly and compose commands yourself</summary>

### Dashboard

```bash
anypoc dashboard
```

Then open **http://localhost:8501** in your browser.

### Finding Bugs

The pipeline has four steps:

#### Step 1: Generate Sources 📥

Extract potential vulnerability patterns from the project's commit history:

```bash
anypoc scan source commits \
  -p firefox \
  --time-range "from 2024-01-01 to 2024-12-31" \
  --description "memory errors; integer overflow; buffer overflow"
```

#### Step 2: Extract Patterns 🧩

Analyze those sources to create bug patterns:

```bash
anypoc scan pattern -p firefox
```

#### Step 3: Scan for Bugs 🐛

Scan the codebase looking for similar vulnerabilities:

```bash
anypoc scan bug -p firefox
```

#### Step 4: Generate POCs 💥

Automatically generate proof-of-concept exploits:

```bash
anypoc poc run firefox
```

Check progress:

```bash
anypoc poc status firefox
```

### Adding a New Project (manual)

#### 1. Initialize your project

```bash
anypoc project init myproject
```

This creates a project folder with everything you need:

```
projects/myproject/
├── Dockerfile         # How to build the target
├── paths.md           # Where to find source code & binaries
└── prompts/           # Custom prompts for poc generation (optional)
```

#### 2. Configure the Dockerfile

Edit `projects/myproject/Dockerfile` to:
- Clone or copy the source code
- Install any dependencies
- Build with sanitizers (ASan, UBSan, etc.) for better bug detection

#### 3. Set up paths

Edit `projects/myproject/paths.md` to tell the system where to find the source code and binaries inside the container.

#### 4. Build the Docker images

```bash
anypoc project build myproject
```

#### 5. Start hunting

```bash
anypoc scan source commits -p myproject --time-range "last 6 months"
anypoc scan pattern -p myproject
anypoc scan bug -p myproject
anypoc poc run myproject
```

</details>


## 🙏 Credits

If AnyPoC helped you find/confirmed bugs, please [open an issue](https://github.com/zzjas/anypoc/issues/new) to tell us about them so we can keep track of bugs found by AnyPoC.

If your research paper uses AnyPoC, please cite:

```bibtex
@article{zhao2026anypoc,
  title={AnyPoC: Universal Proof-of-Concept Test Generation for Scalable LLM-Based Bug Detection},
  author={Zhao, Zijie and Yang, Chenyuan and Wang, Weidong and Yang, Yihan and Zhang, Ziqi and Zhang, Lingming},
  journal={arXiv preprint arXiv:2604.11950},
  year={2026}
}
```

Thanks to:

- All maintainers who reviewed our bug reports
- [Claude Code](https://github.com/anthropics/claude-code)
- [Codex](https://github.com/openai/codex)
