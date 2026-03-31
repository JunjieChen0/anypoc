"""Knowledge extraction helpers and summary types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import CODE_FILTER_MAX_BUG_REPORT_CHARS


@dataclass(frozen=True)
class KnowledgeExtractionSummary:
    """Summary of a knowledge extraction run."""

    generation_dir: Path
    trajectory_path: Path
    knowledge_dir: Path
    extractor_traj_path: Path | None
    agent_response: str
    reported_ids: list[str]
    updated_ids: list[str]
    ratings: list[tuple[str, float]]
    was_successful: bool


def _build_extractor_system_prompt(
    generation_dir: Path,
    knowledge_dir: Path,
    was_successful: bool,
) -> str:
    """Build the system prompt for the knowledge extraction agent."""
    success_note = "successful" if was_successful else "unsuccessful"

    return f"""You are a trajectory analyzer that extracts reusable knowledge from PoC-generation runs.

Inputs:
- PoC generation directory: {generation_dir}
- Knowledge base directory: {knowledge_dir}
- Generation outcome: {success_note}

Your tasks:
1. Review the compressed trajectory skeleton in the prompt to understand the overall flow.
2. Use `get_trajectory_turns` to inspect specific turns in detail when needed.
3. Extract reusable knowledge that would help future work on this codebase.
   This includes: build/compilation commands, useful CLI invocations, internal tool usage,
   test framework patterns, code structure insights, and PoC forms/types (e.g. standalone HTML,
   HTML+JS using specific APIs, or a server+debugger harness).
   - For `code/` entries: capture general facts about the code, APIs, invariants, pitfalls,
     or reusable debugging hints. **Do NOT** record bug-specific root causes, PoC steps,
     crash logs, or details that only apply to this one bug.
4. Compare against existing knowledge already stored in the knowledge base.
5. For each relevant knowledge item:
   - If it is NEW: call report_new_knowledge with a path, markdown content, and keywords
   - If it ALREADY exists and you can add meaningful new information: call update_knowledge

## Inspecting the Trajectory

The trajectory is provided in compressed format showing each turn on one line.
To see full details of specific turns, use:
- `get_trajectory_turns([5])` - Get full content of turn 5
- `get_trajectory_turns([3, 4, 5, 6])` - Get full content of turns 3-6

Focus on:
- Unique commands executed (Bash tool calls) - these reveal build steps, test invocations, and tool usage
- Assistant messages describing intent - these explain what the agent was trying to achieve and why

## Reporting Knowledge

When calling report_new_knowledge, provide:
- path: A category path like "build/cmake_flags.md" or "command_line_tools/gdb_basics.md"
- content: Plain markdown (no YAML front matter - it is injected automatically)
- keywords: A list of keywords for search and discovery

Enforced categories - paths MUST start with one of:

Shared (cross-project):
- command_line_tools/ - General CLI tools (gdb, valgrind, strace, etc.)
  E.g., "gdb_conditional_breakpoints.md", "ubsan_tee_exit_code_pitfall.md". NOT project-specific tools.
- language_specific/  - Language knowledge (subdirs: c/, cpp/, rust/)
  E.g., "c/signed_char_ctype_ub.md", "rust/repr_c_ffi_struct_layout.md". General language pitfalls, NOT project APIs.

Per-project (auto-prefixed with project name):
- build/            - Build system, compilation, flags
  E.g., "cmake_flags.md", "targeted_ubsan_single_file.md". How to compile the project or components.
- internal_tools/   - Project's specific tools and scripts
  E.g., "clang_ast_dump.md", "chromium_remote_debug.md", "firefox_marionette.md".
  Tools shipped WITH the project. NOT general CLI tools.
- test_frameworks/  - Testing approaches and harnesses
  E.g., "standalone_test_binaries.md". How to run the project's tests.
  NOT PoC formats (use poc_forms/).
- code/             - Knowledge about specific code paths or APIs
  E.g., "coroutine_ir_structure.md", "btree_cursor_invalidation.md".
  General code facts/invariants. NOT bug-specific root causes or crash logs.
- poc_forms/        - PoC formats and what user capabilities they represent (NOT bug patterns)
  E.g., "html_js_poc.md", "remote_debug_script_poc.md", "sql_query_poc.md", "mochitest_poc.md".
  General PoC format/shapes. NOT steps to reproduce a specific bug.
  Focus on forms that demonstrate user-triggerable scenarios, instead of
  internal tests that simulate unrealistic conditions.

Invalid paths will be rejected.

Important:
- Knowledge from {success_note} runs is tracked separately.
  This helps identify which knowledge actually leads to success.
- Be specific and actionable in your knowledge entries.
- Do NOT directly write, edit, or create any knowledge files on disk.
  You MUST use the provided tools (report_new_knowledge, update_knowledge, etc.)
  to create and manage knowledge entries. Never use Write, Edit, or Bash to
  modify files under the knowledge base directory.
"""


def _build_extraction_prompt(
    generation_dir: Path,
    traj_path: Path,
    knowledge_dir: Path,
    existing_index: str,
    compressed_trajectory: str,
    trajectory_summary: dict[str, Any],
    was_successful: bool,
) -> str:
    """Build the prompt for knowledge extraction."""
    outcome = "SUCCESSFUL" if was_successful else "UNSUCCESSFUL"

    # Format summary
    summary_lines = []
    if trajectory_summary.get("total_turns"):
        summary_lines.append(f"- Total turns: {trajectory_summary['total_turns']}")
    if trajectory_summary.get("user_messages"):
        summary_lines.append(f"- User messages: {trajectory_summary['user_messages']}")
    if trajectory_summary.get("assistant_messages"):
        summary_lines.append(f"- Assistant messages: {trajectory_summary['assistant_messages']}")
    if trajectory_summary.get("tool_calls"):
        summary_lines.append(f"- Tool calls: {trajectory_summary['tool_calls']}")
    if trajectory_summary.get("tool_errors"):
        summary_lines.append(f"- Tool errors: {trajectory_summary['tool_errors']}")
    if trajectory_summary.get("tool_usage"):
        usage_str = ", ".join(f"{k}: {v}" for k, v in trajectory_summary["tool_usage"].items())
        summary_lines.append(f"- Tool usage: {usage_str}")
    if trajectory_summary.get("duration_ms"):
        summary_lines.append(f"- Duration: {trajectory_summary['duration_ms'] / 1000:.1f}s")
    if trajectory_summary.get("total_cost_usd"):
        summary_lines.append(f"- Cost: ${trajectory_summary['total_cost_usd']:.2f}")
    summary_text = "\n".join(summary_lines) if summary_lines else "(no summary available)"

    return f"""You are analyzing a PoC generation run and extracting reusable knowledge.

## Generation Outcome: {outcome}

## Paths
- Generation directory: {generation_dir}
- Trajectory file: {traj_path}
- Knowledge base directory: {knowledge_dir}

{existing_index}

## Trajectory Summary
{summary_text}

## Compressed Trajectory Skeleton

The trajectory is shown in compressed format. Each line represents one turn:
- `[N] user: "text..." (Nc)` - User message with character count
- `[N] asst: "text..." (Nc)` - Assistant message with character count
- `[N] ToolName: {{input...}} -> ok/Error (Nc)` - Tool call with status and result size

```
{compressed_trajectory}
```

## How to Inspect Turn Details

To see the full content of specific turns, use the `get_trajectory_turns` tool:
- `get_trajectory_turns([5])` - Get details for turn 5
- `get_trajectory_turns([3, 4, 5, 6])` - Get details for turns 3-6

This returns complete input/output for each requested turn.

## Instructions

1. Review the compressed trajectory skeleton above to understand the overall flow.
2. Use `get_trajectory_turns` to inspect interesting turns in detail:
   - Unique commands executed (Bash calls) - reveal build steps, test invocations, tool usage
   - Assistant messages describing intent - explain what the agent was trying to achieve
3. Extract reusable knowledge that would help future work on this codebase.
4. For each piece of knowledge:
   - Choose a category path like "build/cmake_flags.md" or "command_line_tools/valgrind_usage.md"
   - Write plain markdown content (no YAML front matter needed - it is injected automatically)
   - Call report_new_knowledge with the path, content, and a list of keywords

For `code/` knowledge specifically:
- Only capture general facts about the codebase, APIs, invariants, pitfalls, or reusable hints.
- Do NOT write bug-specific details, PoC steps, crash logs, or root-cause narratives tied to this run.

For `poc_forms/` knowledge specifically:
- Capture general PoC formats/shapes and what user capabilities they represent
  (e.g., crafted input files, HTML/JS pages, network payloads, server+client harnesses).
- Focus on forms that demonstrate user-triggerable scenarios, instead of
  internal tests that simulate unrealistic conditions.
- Do NOT document steps to reproduce a specific bug.

Remember: This was a {outcome.lower()} generation. Focus on extracting knowledge that:
{"- Contributed to the success" if was_successful else "- Could help future runs succeed"}
{"- Could be applied to future work on this codebase" if was_successful else "- Identifies pitfalls to avoid"}
"""


def _find_project_root_from_generation(generation_dir: Path) -> Path | None:
    """Locate the project output root directory (containing scans/ and poc/)."""
    for parent in generation_dir.parents:
        if parent.name == "poc":
            return parent.parent
    return None


def _load_bug_report_for_generation(generation_dir: Path) -> tuple[str | None, str | None]:
    """Load bug report content for a generation directory if available."""
    bug_id = generation_dir.parent.name if generation_dir.parent else ""
    if not bug_id:
        return None, None
    project_root = _find_project_root_from_generation(generation_dir)
    if project_root is None:
        return None, None
    scans_dir = project_root / "scans"
    if not scans_dir.exists():
        return None, None
    candidates = sorted(scans_dir.glob(f"*/reports/{bug_id}.*"))
    if not candidates:
        return None, None
    preferred_exts = (".json", ".md", ".txt")
    selected = None
    for ext in preferred_exts:
        for candidate in candidates:
            if candidate.suffix.lower() == ext:
                selected = candidate
                break
        if selected:
            break
    if selected is None:
        selected = candidates[0]
    try:
        content = selected.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return str(selected), None
    if len(content) > CODE_FILTER_MAX_BUG_REPORT_CHARS:
        content = content[:CODE_FILTER_MAX_BUG_REPORT_CHARS].rstrip() + "\n...[truncated]..."
    return str(selected), content
