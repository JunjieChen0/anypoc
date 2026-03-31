"""Focused strategy: scan specific code locations or features described in NL.

Single-phase agent flow: the agent explores the repository according to the
user's scan instruction and reports any bugs it finds via the `report_bug` tool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar

from scanner.registry import register_strategy
from scanner.strategies._common import run_bug_hunt_session
from scanner.types import BugReport, BugScanStrategy, StrategyParam


@register_strategy
class FocusedScanStrategy(BugScanStrategy):
    name: ClassVar[str] = "focused"
    description: ClassVar[str] = "Scan specific files, functions, or features described in natural language."
    params: ClassVar[list[StrategyParam]] = [
        StrategyParam(
            name="instruction",
            description="Natural-language scan instruction describing what to look for, where, and what bug types matter.",
        ),
    ]

    async def run(self, inputs: dict[str, str]) -> AsyncIterator[BugReport]:
        instruction = inputs["instruction"]
        repo = self.ctx.source_code_dir

        user_prompt = f"""You are scanning the repository at {repo} for bugs.

Scan instruction:
{instruction}

Steps:
1. Explore the repository structure to orient yourself (list files, read READMEs, etc.).
2. Based on the scan instruction, identify the relevant files and code areas.
3. Read and analyze the code carefully, looking for bugs — security vulnerabilities,
   logic errors, race conditions, resource leaks, off-by-one errors, missing validation, etc.
4. For each genuine bug you find, call the report_bug tool with a complete markdown report.
   The tool name may have an MCP prefix (e.g. mcp__bug_reporter__report_bug).
   Start the body with a top-level `# Title` heading and include sections like:
     - Location (file:line)
     - Why this is a bug
     - How to confirm / reproduce
5. Do not modify the repository. Use only read-only commands.
6. If you do not find any bugs, simply stop — it is fine to report nothing.
"""

        async for report in run_bug_hunt_session(
            self.ctx,
            strategy_name=self.name,
            system_prompt="You are an expert code auditor. Find real, actionable bugs — not style nits or hypothetical issues.",
            user_prompt=user_prompt,
            traj_name="focused_scan",
            base_metadata={"instruction": instruction},
            agent_name="Focused Bug Scanner",
            agent_description="Explores targeted code areas and reports bugs via the report_bug tool.",
        ):
            yield report
