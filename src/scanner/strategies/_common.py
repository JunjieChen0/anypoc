"""Shared building blocks for bug-scan strategies.

Two pieces:

1. `BugReportCollectorToolKit` — a `caw` toolkit exposing `report_bug(markdown)`.
   Persists each accepted report as a single `.md` file with frontmatter and
   pushes a `BugReport` onto an asyncio queue. Stamps caller-supplied metadata
   on every report so strategies don't have to thread it through prompts.

2. `run_scan_session` — wraps the boilerplate of:
     - building a one-shot caw Agent with the toolkit attached
     - opening a session with a trajectory file
     - sending the user prompt asynchronously
     - draining the report queue concurrently and yielding BugReports
     - recording cost into the strategy's spend limiter
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from caw import Agent, ToolGroup, ToolKit, tool

from anypoc.utils import logger
from scanner.types import BugReport, StrategyContext

LOG_PREFIX = "[Scanner]"


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def sanitize_identifier(value: str, max_len: int = 100) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip())
    sanitized = sanitized.strip("-._")
    if not sanitized:
        sanitized = "report"
    return sanitized[:max_len]


def short_hash(content: str, length: int = 6) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Bug report collector toolkit
# ---------------------------------------------------------------------------


def _extract_title(markdown: str, fallback: str) -> str:
    """Pull the first H1 from a markdown body, falling back to a default."""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


class BugReportCollectorToolKit(
    ToolKit,
    server_name="bug_reporter",
    display_name="Bug Report Collector",
    thread_safe=True,
):
    """Stateful collector exposing one tool: `report_bug(markdown_body)`.

    Each accepted call writes a `.md` file under `reports_dir` and enqueues a
    `BugReport` on `queue` so the strategy can yield it upward.
    """

    def __init__(
        self,
        *,
        strategy_name: str,
        reports_dir: Path,
        base_metadata: Mapping[str, str] | None = None,
        max_reports: int | None = None,
    ) -> None:
        self.strategy_name = strategy_name
        self.reports_dir = reports_dir
        self.base_metadata: dict[str, str] = {str(k): str(v) for k, v in (base_metadata or {}).items()}
        self.max_reports = max_reports

        self.report_count = 0
        self.queue: asyncio.Queue[BugReport] = asyncio.Queue()
        self.seen_identifiers: set[str] = set()
        reports_dir.mkdir(parents=True, exist_ok=True)

    @tool(
        name="report_bug",
        description=(
            "Submit a bug report as a markdown body (no code fences, no frontmatter). "
            "Start with a top-level `# Title` heading and include any sections you find useful "
            "(e.g. Location, Why this is a bug, How to confirm). The collector adds metadata "
            "automatically and saves the file."
        ),
    )
    async def report_bug(self, markdown_body: str) -> str:
        body = (markdown_body or "").strip()
        if not body:
            return "Empty markdown body. Provide a real bug report."

        title = _extract_title(body, fallback=f"{self.strategy_name} bug")
        slug = sanitize_identifier(title)
        identifier = f"{slug}-{short_hash(body)}"

        # Collisions can happen if the same body is submitted twice; adjust the suffix.
        counter = 1
        while identifier in self.seen_identifiers:
            identifier = f"{slug}-{short_hash(body + str(counter))}"
            counter += 1
        self.seen_identifiers.add(identifier)

        report = BugReport(
            identifier=identifier,
            title=title,
            strategy=self.strategy_name,
            metadata=dict(self.base_metadata),
            body=body,
        )
        path = self.reports_dir / f"{identifier}.md"
        report.to_file(path)
        self.queue.put_nowait(report)
        self.report_count += 1
        logger.info(f"{LOG_PREFIX} Saved bug report {identifier} -> {path}")

        if self.max_reports is not None and self.report_count >= self.max_reports:
            return (
                f"Bug report saved as {identifier}. "
                f"STOP: reached the maximum number of reports ({self.max_reports}). "
                f"Do not call report_bug again. Wrap up immediately."
            )
        return f"Bug report saved as {identifier}"


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


async def run_bug_hunt_session(
    ctx: StrategyContext,
    *,
    strategy_name: str,
    system_prompt: str,
    user_prompt: str,
    traj_name: str,
    base_metadata: Mapping[str, str],
    agent_metadata: Mapping[str, Any] | None = None,
    max_reports: int | None = None,
    agent_name: str = "Bug Scanner",
    agent_description: str = "Explores the repository and reports bugs via the report_bug tool.",
) -> AsyncIterator[BugReport]:
    """Run a single bug-hunting agent session and stream out bug reports.

    The agent is given the `BugReportCollectorToolKit` plus read-only repo tools.
    Reports are yielded as soon as the agent calls `report_bug`, in parallel
    with the agent run. Cost is recorded against `ctx.spend_limiter` on exit.
    """

    toolkit = BugReportCollectorToolKit(
        strategy_name=strategy_name,
        reports_dir=ctx.reports_dir,
        base_metadata=base_metadata,
        max_reports=max_reports,
    )

    agent = Agent(
        name=agent_name,
        description=agent_description,
        system_prompt=system_prompt,
        tools=ToolGroup.NO_INTERACTION,
        tool_servers=[toolkit],
        data_dir=None,
    )

    traj_path = ctx.logs_dir / f"{traj_name}.traj.json"
    logger.info(f"{LOG_PREFIX} Starting agent session {traj_name}")

    queue = toolkit.queue
    try:
        with agent.start_session(
            traj_path=traj_path,
            metadata=dict(agent_metadata or {}),
        ) as session:
            send_task = asyncio.create_task(session.send_async(user_prompt))
            while not send_task.done():
                try:
                    report = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield report
                except asyncio.TimeoutError:
                    continue
            await send_task
            while not queue.empty():
                yield queue.get_nowait()
    finally:
        ctx.spend_limiter.record_cost_from_traj(traj_path)
