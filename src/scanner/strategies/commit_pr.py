"""Commit / PR strategy: scan a single commit or PR for introduced bugs.

Single-phase agent flow: the agent reads the diff for the given ref, analyzes
the changes and surrounding code, and reports any bugs introduced by or
exposed by the change via the `report_bug` tool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar

from scanner.registry import register_strategy
from scanner.strategies._common import run_bug_hunt_session
from scanner.types import BugReport, BugScanStrategy, StrategyParam


@register_strategy
class CommitPRScanStrategy(BugScanStrategy):
    name: ClassVar[str] = "commit-pr"
    description: ClassVar[str] = "Scan a single git commit or pull request for bugs introduced by the change."
    params: ClassVar[list[StrategyParam]] = [
        StrategyParam(
            name="ref",
            description="Commit SHA, branch, tag, or 'pr/<number>' to scan.",
        ),
        StrategyParam(
            name="instruction",
            description="Scan instruction — what bug types to focus on, what to ignore, additional context, etc.",
            required=False,
            default="",
        ),
    ]

    async def run(self, inputs: dict[str, str]) -> AsyncIterator[BugReport]:
        ref = inputs["ref"]
        instruction = inputs.get("instruction") or ""
        repo = self.ctx.source_code_dir

        instruction_block = ""
        if instruction:
            instruction_block = f"\nAdditional scan instruction:\n{instruction}\n"

        user_prompt = f"""You are scanning a commit/PR in the repository at {repo} for bugs.

Ref to scan: {ref}
{instruction_block}
Steps:
1. Read the change using `git show {ref}` (or `git diff main...{ref}` for a branch/PR)
   to understand what was modified.
2. Identify what the change does — new feature, bug fix, refactor, etc.
3. Read the surrounding code (callers, sibling functions, related modules) to understand
   the full context of the change.
4. Look for bugs INTRODUCED by this change:
   - Direct bugs in the new/modified code (logic errors, missing edge cases, security issues, etc.)
   - Semantic breakage: did the change alter behavior that other code depends on?
   - Missing updates: are there callers or related code that should have been updated
     to match the new semantics but weren't?
5. For each genuine bug you find, call the report_bug tool with a complete markdown report.
   The tool name may have an MCP prefix (e.g. mcp__bug_reporter__report_bug).
   Start the body with a top-level `# Title` heading and include sections like:
     - Location (file:line)
     - Why this is a bug
     - Relationship to the commit/PR
     - How to confirm / reproduce
6. Do not modify the repository. Use only read-only commands.
7. If you do not find any bugs, simply stop — it is fine to report nothing.
"""

        async for report in run_bug_hunt_session(
            self.ctx,
            strategy_name=self.name,
            system_prompt="You are an expert code reviewer. Find real bugs introduced by or exposed by the given change — not pre-existing issues unrelated to the diff.",
            user_prompt=user_prompt,
            traj_name=f"commit_pr_{ref.replace('/', '_')[:40]}",
            base_metadata={"ref": ref, "instruction": instruction},
            agent_metadata={"ref": ref},
            agent_name="Commit/PR Bug Scanner",
            agent_description="Inspects a commit or PR diff and reports bugs introduced by the change.",
        ):
            yield report
