"""History strategy: scan git history for bugs.

Three-phase agent flow:

  Phase 1 — Time-range planner agent
      Splits the user's natural-language `time_range` into chunks.

  Phase 2 — Per-chunk commit-selector agent
      For each chunk, an agent inspects git history within the window and
      reports bug-fix commits via the `report_commit` tool. The selected
      commits are persisted under `state/commits/<chunk>.json` so the strategy
      can resume.

  Phase 3 — Per-commit bug-hunter agent
      For each selected commit, a fresh agent inspects the commit's diff and
      the surrounding code, then reports any confirmed bugs via the
      `report_bug` tool. Each commit gets its own trajectory file so resume
      is per-commit.

The strategy uses `BugReportCollectorToolKit` from `_common.py` for phase 3.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

from caw import Agent, ToolGroup, ToolKit, tool

from anypoc.utils import logger
from anypoc.utils.trajectory import is_trajectory_complete
from scanner.registry import register_strategy
from scanner.strategies._common import (
    LOG_PREFIX,
    run_bug_hunt_session,
    sanitize_identifier,
)
from scanner.types import BugReport, BugScanStrategy, StrategyParam


# ---------------------------------------------------------------------------
# Commit collector toolkit (phase 2)
# ---------------------------------------------------------------------------


class CommitCollectorToolKit(
    ToolKit,
    server_name="commit_collector",
    display_name="Commit Collector",
    thread_safe=True,
):
    """Toolkit for the commit-selector agent. Validates and collects commit hashes."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self.commits: list[dict[str, str]] = []
        self.seen: set[str] = set()

    @tool(
        name="report_commit",
        description=(
            "Report a git commit hash as a bug-fix commit worth scanning. "
            "Pass the short or full hash. The collector verifies the commit exists."
        ),
    )
    def report_commit(self, commit_hash: str) -> str:
        cleaned = (commit_hash or "").strip()
        if not cleaned:
            return "Empty commit hash."
        record = self._verify(cleaned)
        if record is None:
            msg = f"Commit {cleaned} not found in repository."
            logger.warn(f"{LOG_PREFIX} {msg}")
            return msg
        if record["sha"] in self.seen:
            return f"Commit {record['sha']} already reported."
        self.seen.add(record["sha"])
        self.commits.append(record)
        logger.info(f"{LOG_PREFIX} Selected commit {record['sha']}: {record['subject']}")
        return f"Recorded commit {record['sha']}: {record['subject']}"

    def _verify(self, commit_hash: str) -> dict[str, str] | None:
        try:
            result = subprocess.run(
                ["git", "rev-list", "-1", "--format=%H%n%s", commit_hash],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            return None
        lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith("commit ")]
        if len(lines) < 2:
            return None
        return {"sha": lines[0].strip(), "subject": lines[1].strip()}


# ---------------------------------------------------------------------------
# History strategy
# ---------------------------------------------------------------------------


@register_strategy
class HistoryScanStrategy(BugScanStrategy):
    name: ClassVar[str] = "history"
    description: ClassVar[str] = (
        "Mine git history within a time range for bug-fix commits, then scan each "
        "commit for bugs introduced by or related to the fix."
    )
    params: ClassVar[list[StrategyParam]] = [
        StrategyParam(
            name="time_range",
            description="Natural-language time range, e.g. 'last 6 months' or '2023-01-01 to 2023-12-31'.",
        ),
        StrategyParam(
            name="commit_picker_instructions",
            description=(
                "Free-form instructions injected into the commit-selection agent. "
                "Use this to describe what kinds of commits/bugs are most interesting "
                "(e.g. 'prefer parser fixes over build fixes')."
            ),
            required=False,
        ),
        StrategyParam(
            name="bug_hunter_instructions",
            description=(
                "Free-form instructions injected into the per-commit bug-hunting agent. "
                "Use this to describe what bug types matter, which areas of the codebase "
                "to focus on, what to ignore, etc."
            ),
            required=False,
        ),
    ]

    async def run(self, inputs: dict[str, str]) -> AsyncIterator[BugReport]:
        time_range = inputs["time_range"]
        commit_picker_instructions = inputs.get("commit_picker_instructions") or None
        bug_hunter_instructions = inputs.get("bug_hunter_instructions") or None

        repo = self.ctx.source_code_dir
        if not (repo / ".git").exists():
            raise ValueError(f"Not a git repository: {repo}")

        # ---------------- Phase 1: plan chunks ----------------
        chunks = await self._plan_chunks(time_range)
        if not chunks:
            logger.warn(f"{LOG_PREFIX} Planner returned no chunks; nothing to scan.")
            return
        logger.info(f"{LOG_PREFIX} Planned {len(chunks)} chunk(s) for time range {time_range!r}")

        commits_state_dir = self.ctx.state_dir / "commits"
        commits_state_dir.mkdir(parents=True, exist_ok=True)

        # ---------------- Phase 2 + Phase 3 ----------------
        for chunk in chunks:
            if not self.ctx.spend_limiter.can_proceed():
                logger.info(f"{LOG_PREFIX} Spend limit reached, stopping before chunk {chunk['label']}")
                break

            chunk_label = chunk["label"]
            commits = await self._select_commits_for_chunk(chunk, commits_state_dir, commit_picker_instructions)
            if not commits:
                logger.info(f"{LOG_PREFIX} No commits selected for chunk {chunk_label}")
                continue

            for commit in commits:
                if not self.ctx.spend_limiter.can_proceed():
                    logger.info(f"{LOG_PREFIX} Spend limit reached, stopping before commit {commit['sha']}")
                    return
                await self.ctx.backpressure.acquire()
                async for report in self._scan_commit(commit, time_range, chunk_label, bug_hunter_instructions):
                    yield report

    # ------------------------------------------------------------------
    # Phase 1: time-range planner agent
    # ------------------------------------------------------------------

    async def _plan_chunks(self, time_range: str) -> list[dict[str, str]]:
        prompt = f"""Split the following time range into monthly chunks for a git history scan.

Time range: {time_range}

Output one chunk per line, no prose, no code fences. Format:
LABEL: YYYY-MM-DD to YYYY-MM-DD

Example:
2024-01: 2024-01-01 to 2024-01-31
2024-02: 2024-02-01 to 2024-02-29
"""
        traj_path = self.ctx.logs_dir / "phase1_planner.traj.json"

        def _run_planner() -> str:
            agent = Agent(name="History Time Planner", data_dir=None)
            with agent.start_session(traj_path=traj_path, metadata={"phase": "plan", "time_range": time_range}) as s:
                turn = s.send(prompt)
            return turn.result or ""

        try:
            raw = await asyncio.to_thread(_run_planner)
        except Exception as exc:
            logger.error(f"{LOG_PREFIX} Phase 1 planner failed: {exc}")
            raise
        finally:
            self.ctx.spend_limiter.record_cost_from_traj(traj_path)

        return _parse_chunk_lines(raw, fallback_label=time_range)

    # ------------------------------------------------------------------
    # Phase 2: per-chunk commit-selector agent
    # ------------------------------------------------------------------

    async def _select_commits_for_chunk(
        self,
        chunk: dict[str, str],
        commits_state_dir: Path,
        commit_picker_instructions: str | None,
    ) -> list[dict[str, str]]:
        chunk_label = chunk["label"]
        state_path = commits_state_dir / f"{sanitize_identifier(chunk_label)}.json"
        traj_path = self.ctx.logs_dir / f"phase2_commits_{sanitize_identifier(chunk_label)}.traj.json"

        # Resume: if both state file and a complete trajectory exist, reuse.
        if state_path.exists() and is_trajectory_complete(traj_path):
            try:
                cached = json.loads(state_path.read_text())
                logger.info(f"{LOG_PREFIX} Resuming chunk {chunk_label}: {len(cached)} commit(s) cached")
                return cached
            except (json.JSONDecodeError, OSError):
                pass

        toolkit = CommitCollectorToolKit(self.ctx.source_code_dir)
        extra_block = ""
        if commit_picker_instructions:
            extra_block = f"\nAdditional Instructions:\n{commit_picker_instructions}\n"
        prompt = f"""You are scanning git history for bug-fix commits in {self.ctx.source_code_dir}.

Time window: {chunk["start"]} to {chunk["end"]} (label: {chunk_label})
{extra_block}
Instructions:
1. Use Bash to list commits in the window with:
     git log --since={chunk["start"]} --until={chunk["end"]} --pretty=format:'%h %s'
2. Inspect promising commits with `git show <hash>` to read the diff and message.
3. For each commit that is clearly a bug fix worth scanning, call the report_commit
   tool with the short hash. The tool name may have an MCP prefix.
4. Do not modify the repository. Use only read-only git commands.
5. When you've finished examining the window, stop. Aim for quality over quantity.
"""

        def _run_selector() -> None:
            agent = Agent(
                name="Commit Selector",
                description="Identifies bug-fix commits within a time window.",
                system_prompt="",
                tools=ToolGroup.NO_INTERACTION,
                tool_servers=[toolkit],
                data_dir=None,
            )
            with agent.start_session(
                traj_path=traj_path,
                metadata={
                    "phase": "select_commits",
                    "chunk": chunk_label,
                    "chunk_start": chunk["start"],
                    "chunk_end": chunk["end"],
                },
            ) as session:
                session.send(prompt)

        logger.info(f"{LOG_PREFIX} Phase 2: selecting commits for chunk {chunk_label}")
        try:
            await asyncio.to_thread(_run_selector)
        except Exception as exc:
            logger.error(f"{LOG_PREFIX} Phase 2 chunk {chunk_label} failed: {exc}")
            return []
        finally:
            self.ctx.spend_limiter.record_cost_from_traj(traj_path)

        commits = toolkit.commits
        state_path.write_text(json.dumps(commits, indent=2))
        logger.info(f"{LOG_PREFIX} Chunk {chunk_label}: selected {len(commits)} commit(s)")
        return commits

    # ------------------------------------------------------------------
    # Phase 3: per-commit bug-hunter agent
    # ------------------------------------------------------------------

    async def _scan_commit(
        self,
        commit: dict[str, str],
        time_range: str,
        chunk_label: str,
        bug_hunter_instructions: str | None,
    ) -> AsyncIterator[BugReport]:
        sha = commit["sha"]
        subject = commit.get("subject", "")
        traj_name = f"phase3_bugs_{sha[:12]}"
        traj_path = self.ctx.logs_dir / f"{traj_name}.traj.json"

        if is_trajectory_complete(traj_path):
            logger.info(f"{LOG_PREFIX} Skipping commit {sha[:12]}: already scanned")
            return

        extra_block = ""
        if bug_hunter_instructions:
            extra_block = f"\nAdditional Instructions:\n{bug_hunter_instructions}\n"
        prompt = f"""You are inspecting a single bug-fix commit in {self.ctx.source_code_dir} for bugs.

Commit: {sha}
Subject: {subject}
{extra_block}
Instructions:
1. Read the commit using `git show {sha}` to understand what was fixed.
2. Identify the root cause of the bug the commit addresses.
3. Inspect the surrounding code (callers, sibling functions, related modules)
   to find OTHER places that have the same root cause but were NOT fixed.
4. For each genuine bug you find, call the report_bug tool with a complete
   markdown report. The tool name may have an MCP prefix (e.g. mcp__bug_reporter__report_bug).
   Start the body with a top-level `# Title` heading and include sections like:
     - Location (file:line)
     - Why this is a bug
     - How to confirm
5. Do not modify the repository. Use only read-only commands.
6. If you do not find any bugs, simply stop — it is fine to report nothing.
"""

        logger.info(f"{LOG_PREFIX} Phase 3: scanning commit {sha[:12]} ({subject})")
        try:
            async for report in run_bug_hunt_session(
                self.ctx,
                strategy_name=self.name,
                system_prompt="",
                user_prompt=prompt,
                traj_name=traj_name,
                base_metadata={
                    "time_range": time_range,
                    "chunk": chunk_label,
                    "seed_commit": sha,
                },
                agent_metadata={
                    "phase": "scan_commit",
                    "commit": sha,
                    "subject": subject,
                    "chunk": chunk_label,
                },
                agent_name="Commit Bug Hunter",
                agent_description="Inspects a bug-fix commit and reports related bugs.",
            ):
                yield report
        except Exception as exc:
            logger.error(f"{LOG_PREFIX} Phase 3 commit {sha[:12]} failed: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CHUNK_LINE_RE = re.compile(r"^\s*(?P<label>[^:]+?)\s*:\s*(?P<start>\S+)\s+to\s+(?P<end>\S+)\s*$")


def _parse_chunk_lines(text: str, fallback_label: str) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in (text or "").splitlines():
        match = _CHUNK_LINE_RE.match(line.strip())
        if not match:
            continue
        label = match.group("label").strip()
        start = match.group("start").strip()
        end = match.group("end").strip()
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        chunks.append({"label": label or start[:7], "start": start, "end": end})
    if not chunks and text and text.strip():
        # Last-resort fallback so we don't silently scan nothing.
        chunks.append({"label": "full-range", "start": fallback_label, "end": fallback_label})
    return chunks
