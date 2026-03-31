#!/usr/bin/env python3
"""
POC Manager - Orchestrates POC generation for a project.

Manages batch processing of bug reports, Docker container execution,
and knowledge base integration.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from anypoc.core.generator import generate_poc
from anypoc.core.knowledge import KnowledgeManager
from anypoc.core.status import PipelineStatus, find_next_attempt_number, get_attempt_dir
from anypoc.infra.executor import PathMount, PlaygroundExecutor
from anypoc.project import Project, complete_project_name
from scanner.types import BugReport
from anypoc.utils import OUTPUT_DIR, logger
from anypoc.utils.spend_limit import SpendLimiter

LOG_PREFIX = "[POC Manager]"

console = Console()

# =============================================================================
# Metadata
# =============================================================================


@dataclass
class POCManagerMetadata:
    """Persistent metadata for POC manager state."""

    project_name: str
    created_at: str = ""
    updated_at: str = ""

    # Tracking which attempts have had knowledge extracted
    # Format: {"bug_report_stem": [1, 2, 3], ...}  (list of attempt numbers)
    knowledge_extracted_attempts: dict[str, list[int]] = field(default_factory=dict)

    # Summary statistics
    total_bug_reports: int = 0
    completed_reports: int = 0
    passed_reports: int = 0
    failed_reports: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def save(self, path: Path) -> None:
        """Save metadata to JSON file."""
        self.updated_at = datetime.now().isoformat()
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> POCManagerMetadata:
        """Load metadata from JSON file or create new."""
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(
                    project_name=data.get("project_name", ""),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                    knowledge_extracted_attempts=data.get("knowledge_extracted_attempts", {}),
                    total_bug_reports=data.get("total_bug_reports", 0),
                    completed_reports=data.get("completed_reports", 0),
                    passed_reports=data.get("passed_reports", 0),
                    failed_reports=data.get("failed_reports", 0),
                )
            except Exception as e:
                logger.warn(f"{LOG_PREFIX} Failed to load metadata: {e}")
        return cls(project_name="")


# =============================================================================
# POC Manager Class
# =============================================================================


class POCManager:
    """
    Orchestrates POC generation for a project.

    Responsibilities:
    - Manage bug reports queue (pending, in-progress, completed)
    - Execute POC generation in project Docker containers
    - Coordinate knowledge extraction after each attempt
    - Track which attempts have been used for knowledge extraction
    - Support parallel processing with configurable concurrency
    """

    def __init__(self, project_name: str):
        """
        Initialize POC Manager for a project.

        Args:
            project_name: Name of the project to manage

        Raises:
            ValueError: If project doesn't exist
        """
        self.project = Project(project_name)
        if not self.project.exists():
            raise ValueError(f"Project '{project_name}' not found at {self.project.config_dir}")

        # Directory structure
        self.poc_dir = self.project.poc_dir  # output/{project}/poc/
        self.knowledge_dir = OUTPUT_DIR / "knowledge"
        self.metadata_file = self.poc_dir / ".poc_manager_metadata.json"

        # Ensure directories exist
        self.poc_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

        # Load or create metadata
        self.metadata = POCManagerMetadata.load(self.metadata_file)
        self.metadata.project_name = project_name

        # Initialize knowledge manager with project context
        self.knowledge_manager = KnowledgeManager(self.knowledge_dir, project_name=project_name)

    # -------------------------------------------------------------------------
    # Bug Report Management
    # -------------------------------------------------------------------------

    def get_bug_reports(self) -> list[Path]:
        """Get all bug reports for this project."""
        return self.project.get_bug_reports()

    def get_pending_reports(self) -> list[Path]:
        """Get bug reports that don't have any POC attempts yet."""
        return self.project.filter_pending(self.get_bug_reports())

    def get_report_status(self, bug_report: Path) -> dict[str, Any]:
        """
        Get detailed status for a bug report including all attempts.

        Args:
            bug_report: Path to the bug report file

        Returns:
            Dictionary with bug report status and attempt details
        """
        output_dir = self.project.get_poc_output_dir(bug_report)

        attempts = []
        if output_dir.exists():
            for attempt_dir in sorted(output_dir.glob("attempt_*")):
                try:
                    attempt_num = int(attempt_dir.name.split("_")[1])
                except (IndexError, ValueError):
                    continue

                status_file = attempt_dir / "status.json"
                if status_file.exists():
                    status = PipelineStatus.load(attempt_dir)
                    attempts.append(
                        {
                            "attempt_number": attempt_num,
                            "directory": str(attempt_dir),
                            "final_status": status.get_final_status(),
                            "started_at": status.started_at,
                            "completed_at": status.completed_at,
                            "knowledge_extracted": self._is_knowledge_extracted(
                                bug_report.stem,
                                attempt_num,
                            ),
                        }
                    )

        return {
            "bug_report": str(bug_report),
            "stem": bug_report.stem,
            "output_dir": str(output_dir),
            "attempts": attempts,
            "best_status": self._get_best_status(attempts),
        }

    def _get_best_status(self, attempts: list[dict]) -> str:
        """Get the best status across all attempts."""
        if not attempts:
            return "pending"

        # Priority: passed > flaky > incomplete > failed
        statuses = [a["final_status"] for a in attempts]
        if "passed" in statuses:
            return "passed"
        if "flaky" in statuses:
            return "flaky"
        if "incomplete" in statuses:
            return "incomplete"
        return statuses[-1]  # Return latest status

    def _is_knowledge_extracted(self, bug_stem: str, attempt_number: int) -> bool:
        """Check if knowledge has been extracted from an attempt."""
        extracted = self.metadata.knowledge_extracted_attempts.get(bug_stem, [])
        return attempt_number in extracted

    def _mark_knowledge_extracted(self, bug_stem: str, attempt_number: int) -> None:
        """Mark an attempt as having had knowledge extracted."""
        if bug_stem not in self.metadata.knowledge_extracted_attempts:
            self.metadata.knowledge_extracted_attempts[bug_stem] = []
        if attempt_number not in self.metadata.knowledge_extracted_attempts[bug_stem]:
            self.metadata.knowledge_extracted_attempts[bug_stem].append(attempt_number)
            self.metadata.save(self.metadata_file)

    # -------------------------------------------------------------------------
    # POC Generation
    # -------------------------------------------------------------------------

    async def run_single(
        self,
        bug_report: Path,
        in_container: bool = False,
        extract_knowledge: bool = True,
        output_dir_override: Path | None = None,
        knowledge_dir_override: Path | None = None,
        disable_knowledge: bool = False,
        skip_analysis: bool = False,
        readonly_knowledge: bool = False,
        memory_limit: str | None = None,
        resume_from: int | None = None,
        help_context: str | None = None,
    ) -> dict[str, Any]:
        """
        Run POC generation for a single bug report.

        Args:
            bug_report: Path to the bug report file
            in_container: If True, we're running inside the container
            extract_knowledge: If True, extract knowledge after generation
            output_dir_override: Override output directory (used in container)
            knowledge_dir_override: Override knowledge directory (used in container)
            disable_knowledge: If True, disable all knowledge features (no knowledge
                provided to agent, no extraction)
            skip_analysis: If True, skip bug analysis and treat as valid
            readonly_knowledge: If True, provide existing knowledge to the generator
                but skip knowledge extraction after generation
            resume_from: Explicit attempt number to retry from. When set, the new
                attempt inherits context from that attempt's directory.
            help_context: Additional user-provided instructions for the retry.

        Returns:
            Status dictionary with attempt results
        """
        # Use override paths when running in container, otherwise derive from project
        output_dir = output_dir_override if output_dir_override else self.project.get_poc_output_dir(bug_report)
        knowledge_dir = knowledge_dir_override if knowledge_dir_override else self.knowledge_dir
        knowledge_manager = (
            KnowledgeManager(knowledge_dir, project_name=self.project.name)
            if knowledge_dir_override
            else self.knowledge_manager
        )
        current_attempt = find_next_attempt_number(output_dir)

        logger.info(f"{LOG_PREFIX} Processing {bug_report.stem} (attempt {current_attempt})")

        if in_container:
            # Running inside container - call generate_poc directly
            # Use mounted paths: paths file is at /home/playground/input/paths.md
            paths_file = Path("/home/playground/input/paths.md")
            await generate_poc(
                bug_report_path=bug_report,
                output_dir=output_dir,
                paths_file=paths_file,
                custom_prompts=self.project.get_custom_prompts(),
                knowledge_manager=knowledge_manager,
                disable_knowledge=disable_knowledge,
                skip_analysis=skip_analysis,
                resume_from=resume_from,
                help_context=help_context,
            )
        else:
            # Running on host - execute in container
            exit_code = self._execute_in_container(
                bug_report,
                output_dir,
                disable_knowledge=disable_knowledge,
                skip_analysis=skip_analysis,
                readonly_knowledge=readonly_knowledge,
                memory_limit=memory_limit,
                resume_from=resume_from,
                help_context=help_context,
            )
            if exit_code != 0:
                logger.warn(f"{LOG_PREFIX} Container execution failed with code {exit_code}")

            # Reload knowledge manager cache to pick up any ratings made inside container
            if not disable_knowledge:
                self.knowledge_manager.reload()

        # After generation, extract knowledge from the new attempt
        if extract_knowledge and not disable_knowledge:
            attempt_dir = get_attempt_dir(output_dir, current_attempt)
            if attempt_dir.exists():
                await self._extract_knowledge_from_attempt(bug_report.stem, attempt_dir)

        return self.get_report_status(bug_report)

    def _execute_in_container(
        self,
        bug_report: Path,
        output_dir: Path,
        disable_knowledge: bool = False,
        skip_analysis: bool = False,
        readonly_knowledge: bool = False,
        memory_limit: str | None = None,
        resume_from: int | None = None,
        help_context: str | None = None,
    ) -> int:
        """
        Execute POC generation in the project's Docker container.

        Args:
            bug_report: Path to the bug report file
            output_dir: Output directory for this bug report
            disable_knowledge: If True, disable all knowledge features
            skip_analysis: If True, skip bug analysis and treat as valid
            readonly_knowledge: If True, provide existing knowledge but skip extraction
            resume_from: Explicit attempt number to retry from.
            help_context: Additional user-provided instructions for the retry.

        Returns:
            Container exit code
        """
        project_image = self.project.get_image_info()

        # Prepare input directory
        input_dir = output_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        # Copy bug report (markdown with frontmatter — render body for the POC pipeline)
        bug_report_copy = input_dir / "bug_report.md"
        report = BugReport.from_file(bug_report)
        bug_report_copy.write_text(report.to_markdown())

        # Copy paths file
        paths_copy = input_dir / "paths.md"
        shutil.copy2(self.project.paths_file, paths_copy)

        # Create executor with appropriate mounts
        # The user-owned project config dir (paths.md, prompts, Dockerfile) is
        # mounted read-only into the standard ANYPOC_HOME location inside the
        # container so the installed anypoc package resolves the project by name.
        container_project_dir = f"/home/playground/.anypoc/projects/{self.project.name}"
        path_mounts = [
            PathMount("bug_report", "/home/playground/input/bug_report.md", "ro"),
            PathMount("paths", "/home/playground/input/paths.md", "ro"),
            PathMount("output", "/home/playground/output", "rw"),
            PathMount("project_config", container_project_dir, "ro"),
        ]
        path_values = {
            "bug_report": str(bug_report_copy),
            "paths": str(paths_copy),
            "output": str(output_dir),
            "project_config": str(self.project.config_dir),
        }

        if not disable_knowledge:
            path_mounts.append(PathMount("knowledge", "/home/playground/knowledge", "rw"))
            path_values["knowledge"] = str(self.knowledge_dir)

        executor = PlaygroundExecutor(
            image=project_image.full_name,
            path_mounts=path_mounts,
            memory_limit=memory_limit,
        )

        # Build container command
        cli_command = [
            "python3",
            "-m",
            "anypoc.core.manager",
            "run",
            self.project.name,
            "--bug-report",
            "/home/playground/input/bug_report.md",
            "--in-container",
            "--output-dir",
            "/home/playground/output",
        ]

        if disable_knowledge:
            cli_command.append("--no-knowledge")
        else:
            cli_command.extend(["--knowledge-dir", "/home/playground/knowledge"])

        if skip_analysis:
            cli_command.append("--skip-analysis")

        if readonly_knowledge:
            cli_command.append("--read-only-knowledge")

        if resume_from is not None:
            cli_command.extend(["--resume-from", str(resume_from)])

        if help_context:
            cli_command.extend(["--help-context", help_context])

        docker_cmd = executor.build_docker_command(cli_command, path_values)

        # Use the standard in-container anypoc home. The mounted project config
        # lives under <ANYPOC_HOME>/projects/<name>/ and the runtime user owns
        # the rest of the tree for internal state and caches.
        docker_run_idx = docker_cmd.index("run")
        docker_cmd[docker_run_idx + 1 : docker_run_idx + 1] = ["-e", "ANYPOC_HOME=/home/playground/.anypoc"]

        logger.debug(f"{LOG_PREFIX} Docker command: {' '.join(docker_cmd)}")
        result = subprocess.run(docker_cmd, check=False)
        return result.returncode

    # -------------------------------------------------------------------------
    # Batch Processing
    # -------------------------------------------------------------------------

    async def run_batch(
        self,
        bug_reports: list[Path] | None = None,
        max_reports: int | None = None,
        parallel: int = 1,
        in_container: bool = False,
        extract_knowledge: bool = True,
        disable_knowledge: bool = False,
        skip_analysis: bool = False,
        readonly_knowledge: bool = False,
        memory_limit: str | None = None,
        spend_limiter: SpendLimiter | None = None,
    ) -> dict[str, Any]:
        """
        Run POC generation for multiple bug reports.

        Args:
            bug_reports: List of bug reports to process (None = all pending)
            max_reports: Maximum number of reports to process
            parallel: Number of parallel workers
            in_container: If True, we're running inside the container
            extract_knowledge: If True, extract knowledge after each attempt
            disable_knowledge: If True, disable all knowledge features
            skip_analysis: If True, skip bug analysis and treat as valid
            readonly_knowledge: If True, provide existing knowledge but skip extraction
            spend_limiter: Optional spend limiter to enforce a dollar budget

        Returns:
            Summary of batch processing results
        """
        if bug_reports is None:
            bug_reports = self.get_pending_reports()

        if max_reports is not None:
            bug_reports = bug_reports[:max_reports]

        if not bug_reports:
            logger.info(f"{LOG_PREFIX} No bug reports to process")
            return {"processed": 0, "results": [], "summary": {"passed": 0, "flaky": 0, "failed": 0, "incomplete": 0}}

        logger.info(f"{LOG_PREFIX} Processing {len(bug_reports)} bug reports with {parallel} worker(s)")

        results = []

        if parallel == 1:
            # Sequential processing
            for i, report in enumerate(bug_reports, 1):
                if spend_limiter and not spend_limiter.can_proceed():
                    logger.info(f"{LOG_PREFIX} Spend limit reached after {i - 1} reports")
                    break
                logger.info(f"{LOG_PREFIX} [{i}/{len(bug_reports)}] Processing {report.stem}")

                # Snapshot the attempt counter so we only bill new work
                output_dir = self.project.get_poc_output_dir(report)
                attempt_before = find_next_attempt_number(output_dir)

                result = await self.run_single(
                    report,
                    in_container=in_container,
                    extract_knowledge=extract_knowledge,
                    disable_knowledge=disable_knowledge,
                    skip_analysis=skip_analysis,
                    readonly_knowledge=readonly_knowledge,
                    memory_limit=memory_limit,
                )
                results.append(result)

                if spend_limiter:
                    # Only record cost if a new attempt was actually created
                    attempt_after = find_next_attempt_number(output_dir)
                    if attempt_after > attempt_before:
                        trajs_dir = get_attempt_dir(output_dir, attempt_before) / "trajs"
                        spend_limiter.record_cost_from_dir(trajs_dir)
        else:
            # Parallel processing with asyncio
            semaphore = asyncio.Semaphore(parallel)
            pending: set[asyncio.Task] = set()

            async def process_one(report: Path) -> tuple[Path, dict, int, int]:
                async with semaphore:
                    output_dir = self.project.get_poc_output_dir(report)
                    attempt_before = find_next_attempt_number(output_dir)
                    r = await self.run_single(
                        report,
                        in_container=in_container,
                        extract_knowledge=extract_knowledge,
                        disable_knowledge=disable_knowledge,
                        skip_analysis=skip_analysis,
                        readonly_knowledge=readonly_knowledge,
                        memory_limit=memory_limit,
                    )
                    attempt_after = find_next_attempt_number(output_dir)
                    return report, r, attempt_before, attempt_after

            def _drain_done(done: set[asyncio.Task]) -> None:
                for t in done:
                    rpt, result, before, after = t.result()
                    results.append(result)
                    if spend_limiter and after > before:
                        trajs_dir = get_attempt_dir(self.project.get_poc_output_dir(rpt), before) / "trajs"
                        spend_limiter.record_cost_from_dir(trajs_dir)

            for report in bug_reports:
                if spend_limiter and not spend_limiter.can_proceed():
                    logger.info(f"{LOG_PREFIX} Spend limit reached, stopping")
                    break

                task = asyncio.create_task(process_one(report))
                pending.add(task)

                if len(pending) >= parallel:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    _drain_done(done)

            # Drain remaining
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                _drain_done(done)

        # Update metadata statistics
        self._update_statistics()

        return {
            "processed": len(results),
            "results": results,
            "summary": self._summarize_results(results),
        }

    def _update_statistics(self) -> None:
        """Update metadata statistics from current state."""
        all_reports = self.get_bug_reports()
        self.metadata.total_bug_reports = len(all_reports)

        completed = 0
        passed = 0
        failed = 0

        for report in all_reports:
            status = self.get_report_status(report)
            if status["attempts"]:
                completed += 1
                best = status["best_status"]
                if best == "passed":
                    passed += 1
                elif best not in ("pending", "incomplete"):
                    failed += 1

        self.metadata.completed_reports = completed
        self.metadata.passed_reports = passed
        self.metadata.failed_reports = failed
        self.metadata.save(self.metadata_file)

    def _summarize_results(self, results: list[dict]) -> dict[str, int]:
        """Summarize batch processing results."""
        statuses = [r["best_status"] for r in results]
        return {
            "total": len(results),
            "passed": statuses.count("passed"),
            "flaky": statuses.count("flaky"),
            "failed": len([s for s in statuses if s not in ("passed", "flaky", "pending", "incomplete")]),
            "incomplete": statuses.count("incomplete"),
        }

    # -------------------------------------------------------------------------
    # Knowledge Integration
    # -------------------------------------------------------------------------

    async def _extract_knowledge_from_attempt(
        self,
        bug_stem: str,
        attempt_dir: Path,
        extractor_traj_dir: Path | None = None,
        force: bool = False,
    ) -> Any:
        """
        Extract knowledge from a single attempt and invoke evolve.

        Args:
            bug_stem: Stem of the bug report file
            attempt_dir: Directory of the attempt
            extractor_traj_dir: Directory to save extractor trajectories (None = generation_dir/trajs)
            force: If True, re-extract even if already processed.

        Returns:
            KnowledgeExtractionSummary if extraction succeeded, else None.
        """
        try:
            attempt_number = int(attempt_dir.name.split("_")[1])
        except (IndexError, ValueError):
            logger.warn(f"{LOG_PREFIX} Invalid attempt directory: {attempt_dir}")
            return None

        if not force and self._is_knowledge_extracted(bug_stem, attempt_number):
            logger.debug(f"{LOG_PREFIX} Knowledge already extracted from {attempt_dir}")
            return None

        # Check if trajectory exists
        traj_path = attempt_dir / "trajs" / "poc_generation.traj.json"
        if not traj_path.exists():
            logger.debug(f"{LOG_PREFIX} No trajectory found at {traj_path}")
            return None

        # Load status to determine success
        status = PipelineStatus.load(attempt_dir)
        was_successful = status.get_final_status() == "passed"

        # Extract knowledge
        logger.info(f"{LOG_PREFIX} Extracting knowledge from {attempt_dir}")
        try:
            summary = self.knowledge_manager.extract_from_generation(
                generation_dir=attempt_dir,
                was_successful=was_successful,
                extractor_traj_dir=extractor_traj_dir,
            )

            if summary:
                logger.info(
                    f"{LOG_PREFIX} Extracted: {len(summary.reported_ids)} new, "
                    f"{len(summary.updated_ids)} updated, {len(summary.ratings)} ratings"
                )

            # Mark as extracted
            self._mark_knowledge_extracted(bug_stem, attempt_number)
            return summary

        except Exception as e:
            logger.error(f"{LOG_PREFIX} Knowledge extraction failed: {e}")
            return None

    async def extract_pending_knowledge(
        self,
        limit: int | None = None,
        extractor_traj_dir: Path | None = None,
        force: bool = False,
        spend_limiter: SpendLimiter | None = None,
    ) -> dict[str, Any]:
        """
        Extract knowledge from all attempts that haven't been processed yet.

        Args:
            limit: Maximum number of attempts to process. None or 0 means unlimited.
            extractor_traj_dir: Directory to save extractor trajectories (None = generation_dir/trajs)
            force: If True, re-extract even from already-processed attempts.
            spend_limiter: Optional spend limiter to enforce a dollar budget.

        Returns:
            Summary of extraction results
        """
        extracted = []
        skipped = []
        errors = []
        budget_exhausted = False

        for report in self.get_bug_reports():
            # Check if we've hit the limit
            if limit and len(extracted) >= limit:
                break
            if budget_exhausted:
                break

            output_dir = self.project.get_poc_output_dir(report)
            if not output_dir.exists():
                continue

            for attempt_dir in sorted(output_dir.glob("attempt_*")):
                # Check if we've hit the limit
                if limit and len(extracted) >= limit:
                    break
                if spend_limiter and not spend_limiter.can_proceed():
                    logger.info(f"{LOG_PREFIX} Spend limit reached during knowledge extraction")
                    budget_exhausted = True
                    break

                try:
                    attempt_num = int(attempt_dir.name.split("_")[1])
                except (IndexError, ValueError):
                    continue

                if not force and self._is_knowledge_extracted(report.stem, attempt_num):
                    skipped.append(str(attempt_dir))
                    continue

                try:
                    summary = await self._extract_knowledge_from_attempt(
                        report.stem, attempt_dir, extractor_traj_dir, force=force
                    )
                    extracted.append(str(attempt_dir))
                    if spend_limiter and summary and getattr(summary, "extractor_traj_path", None):
                        spend_limiter.record_cost_from_traj(summary.extractor_traj_path)
                except Exception as e:
                    logger.error(f"{LOG_PREFIX} Failed to extract from {attempt_dir}: {e}")
                    errors.append({"dir": str(attempt_dir), "error": str(e)})

        # Run knowledge evolution after batch extraction
        evolve_result = await self.knowledge_manager.evolve()

        return {
            "extracted": extracted,
            "skipped": skipped,
            "errors": errors,
            "evolve_result": evolve_result,
        }

    async def evolve_knowledge(
        self,
        min_rating_threshold: float = -2.0,
        min_iterations: int = 3,
    ) -> dict[str, Any]:
        """
        Run knowledge evolution to archive low-rated entries.

        Args:
            min_rating_threshold: Archive entries below this average rating
            min_iterations: Only evaluate entries with at least this many ratings

        Returns:
            Evolution results
        """
        return await self.knowledge_manager.evolve(
            min_rating_threshold=min_rating_threshold,
            min_iterations_to_evaluate=min_iterations,
        )


# =============================================================================
# CLI
# =============================================================================

app = typer.Typer(help="POC generation management")


@app.command("run")
def cli_run(
    project_name: Annotated[str, typer.Argument(help="Project name", autocompletion=complete_project_name)],
    bug_report: Annotated[
        Optional[str], typer.Option("--bug-report", "-b", help="Single bug report to process")
    ] = None,
    num_reports: Annotated[Optional[int], typer.Option("--num-reports", "-n", help="Max reports to process")] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-p", help="Parallel workers")] = 1,
    in_container: Annotated[bool, typer.Option("--in-container", hidden=True, help="Running inside container")] = False,
    no_knowledge: Annotated[
        bool,
        typer.Option("--no-knowledge", help="Disable all knowledge features (no knowledge provided, no extraction)"),
    ] = False,
    read_only_knowledge: Annotated[
        bool,
        typer.Option(
            "--read-only-knowledge",
            help="Provide existing knowledge to the generator but skip knowledge extraction after generation",
        ),
    ] = False,
    output_dir: Annotated[
        Optional[str], typer.Option("--output-dir", "-o", hidden=True, help="Output directory (for container use)")
    ] = None,
    knowledge_dir: Annotated[
        Optional[str],
        typer.Option("--knowledge-dir", "-k", hidden=True, help="Knowledge directory (for container use)"),
    ] = None,
    skip_analysis: Annotated[
        bool,
        typer.Option("--skip-analysis", help="Skip bug analysis step and treat all bugs as valid"),
    ] = False,
    memory_limit: Annotated[
        Optional[str],
        typer.Option(
            "--memory-limit",
            "-m",
            help="Docker container memory limit (e.g. '64g', '32g'). Defaults to 1/4 of host RAM.",
        ),
    ] = None,
    spend_limit: Annotated[
        Optional[float],
        typer.Option(
            "--spend-limit",
            help="Maximum dollar spend. Stops before starting a task that would exceed this limit.",
        ),
    ] = None,
    resume_from: Annotated[
        Optional[int],
        typer.Option("--resume-from", hidden=True, help="Attempt number to retry from (container passthrough)"),
    ] = None,
    help_context: Annotated[
        Optional[str],
        typer.Option("--help-context", hidden=True, help="Retry guidance for the agent (container passthrough)"),
    ] = None,
):
    """
    Run POC generation for a project.

    Examples:
        # Process all pending reports
        p poc run firefox

        # Process single report
        p poc run firefox --bug-report scans/history-abc12345/reports/my-bug.md

        # Process with parallelism
        p poc run firefox --parallel 4 --num-reports 10

        # Run without knowledge features
        p poc run firefox --no-knowledge

        # Use existing knowledge but don't extract new knowledge
        p poc run firefox --read-only-knowledge

        # Skip bug analysis
        p poc run firefox --skip-analysis
    """
    try:
        manager = POCManager(project_name)
    except ValueError as e:
        logger.error(f"{LOG_PREFIX} {e}")
        raise typer.Exit(1)

    disable_knowledge = no_knowledge
    readonly_knowledge = read_only_knowledge

    # Parse override paths for container use
    output_dir_override = Path(output_dir) if output_dir else None
    knowledge_dir_override = Path(knowledge_dir) if knowledge_dir else None

    if bug_report:
        # Single report mode
        report_path = Path(bug_report).expanduser().resolve()
        if not report_path.exists():
            logger.error(f"{LOG_PREFIX} Bug report not found: {report_path}")
            raise typer.Exit(1)

        result = asyncio.run(
            manager.run_single(
                report_path,
                in_container=in_container,
                extract_knowledge=not disable_knowledge and not readonly_knowledge,
                output_dir_override=output_dir_override,
                knowledge_dir_override=knowledge_dir_override,
                disable_knowledge=disable_knowledge,
                skip_analysis=skip_analysis,
                readonly_knowledge=readonly_knowledge,
                memory_limit=memory_limit,
                resume_from=resume_from,
                help_context=help_context,
            )
        )
        _print_report_status(result)
    else:
        # Batch mode — always create a limiter so overall/project limits are enforced
        limiter = SpendLimiter("poc_run", project_name=project_name, command_limit=spend_limit)
        result = asyncio.run(
            manager.run_batch(
                max_reports=num_reports,
                parallel=parallel,
                in_container=in_container,
                extract_knowledge=not disable_knowledge and not readonly_knowledge,
                disable_knowledge=disable_knowledge,
                skip_analysis=skip_analysis,
                readonly_knowledge=readonly_knowledge,
                memory_limit=memory_limit,
                spend_limiter=limiter,
            )
        )
        _print_batch_summary(result)


@app.command("retry")
def cli_retry(
    project_name: Annotated[str, typer.Argument(help="Project name", autocompletion=complete_project_name)],
    bug_report: Annotated[str, typer.Option("--bug-report", "-b", help="Bug report to retry")],
    from_attempt: Annotated[
        Optional[int],
        typer.Option(
            "--from-attempt",
            "-f",
            help="Attempt number to retry from. Defaults to the latest attempt on disk.",
        ),
    ] = None,
    help_context: Annotated[
        Optional[str],
        typer.Option(
            "--help-context",
            "-c",
            help="Additional instructions for the retry (e.g. what to change, what the agent missed).",
        ),
    ] = None,
    no_knowledge: Annotated[
        bool,
        typer.Option("--no-knowledge", help="Disable all knowledge features"),
    ] = False,
    read_only_knowledge: Annotated[
        bool,
        typer.Option("--read-only-knowledge", help="Use existing knowledge but skip extraction"),
    ] = False,
    skip_analysis: Annotated[
        bool,
        typer.Option("--skip-analysis", help="Skip bug analysis and treat as valid"),
    ] = False,
    memory_limit: Annotated[
        Optional[str],
        typer.Option("--memory-limit", "-m", help="Docker container memory limit (e.g. '64g')."),
    ] = None,
):
    """
    Retry POC generation for a bug report, creating a new attempt.

    The new attempt inherits context from the prior attempt (help_needed.md,
    generation summary, playground/poc file listings) and any extra instructions
    passed via --help-context.

    Examples:
        # Retry the latest attempt (e.g. after a help_needed flag)
        anypoc poc retry firefox -b scans/history-abc/reports/my-bug.md

        # Retry with extra guidance
        anypoc poc retry firefox -b scans/.../my-bug.md -c "try triggering via malformed UTF-8 input"

        # Retry from a specific attempt
        anypoc poc retry firefox -b scans/.../my-bug.md --from-attempt 2
    """
    try:
        manager = POCManager(project_name)
    except ValueError as e:
        logger.error(f"{LOG_PREFIX} {e}")
        raise typer.Exit(1)

    report_path = Path(bug_report).expanduser().resolve()
    if not report_path.exists():
        logger.error(f"{LOG_PREFIX} Bug report not found: {report_path}")
        raise typer.Exit(1)

    output_dir = manager.project.get_poc_output_dir(report_path)
    if from_attempt is None:
        latest = find_next_attempt_number(output_dir) - 1
        if latest < 1:
            logger.error(f"{LOG_PREFIX} No existing attempts to retry for {report_path.stem}")
            raise typer.Exit(1)
        from_attempt = latest

    logger.info(f"{LOG_PREFIX} Retrying {report_path.stem} from attempt {from_attempt}")

    disable_knowledge = no_knowledge
    readonly_knowledge = read_only_knowledge

    result = asyncio.run(
        manager.run_single(
            report_path,
            in_container=False,
            extract_knowledge=not disable_knowledge and not readonly_knowledge,
            disable_knowledge=disable_knowledge,
            skip_analysis=skip_analysis,
            readonly_knowledge=readonly_knowledge,
            memory_limit=memory_limit,
            resume_from=from_attempt,
            help_context=help_context,
        )
    )
    _print_report_status(result)


@app.command("status")
def cli_status(
    project_name: Annotated[str, typer.Argument(help="Project name", autocompletion=complete_project_name)],
    bug_report: Annotated[
        Optional[str], typer.Option("--bug-report", "-b", help="Show status for specific report")
    ] = None,
):
    """Show POC generation status for a project."""
    try:
        manager = POCManager(project_name)
    except ValueError as e:
        logger.error(f"{LOG_PREFIX} {e}")
        raise typer.Exit(1)

    if bug_report:
        report_path = Path(bug_report).expanduser().resolve()
        if not report_path.exists():
            logger.error(f"{LOG_PREFIX} Bug report not found: {report_path}")
            raise typer.Exit(1)

        status = manager.get_report_status(report_path)
        _print_report_status(status)
    else:
        _print_project_status(manager)


# =============================================================================
# Output Helpers
# =============================================================================


def _print_report_status(status: dict) -> None:
    """Print status for a single bug report."""
    console.print(f"\n[bold]Bug Report:[/bold] {status['stem']}")
    console.print(f"[dim]Output:[/dim] {status['output_dir']}")
    console.print(f"[bold]Best Status:[/bold] {status['best_status']}")

    if status["attempts"]:
        table = Table(title="Attempts")
        table.add_column("#", style="cyan")
        table.add_column("Status")
        table.add_column("Knowledge Extracted")
        table.add_column("Completed")

        for a in status["attempts"]:
            table.add_row(
                str(a["attempt_number"]),
                a["final_status"],
                "Yes" if a["knowledge_extracted"] else "No",
                a["completed_at"] or "-",
            )
        console.print(table)
    else:
        console.print("[dim]No attempts yet[/dim]")


def _print_project_status(manager: POCManager) -> None:
    """Print overall project status."""
    meta = manager.metadata

    # Update stats before printing
    manager._update_statistics()

    console.print(f"\n[bold]Project:[/bold] {meta.project_name}")
    console.print(f"[dim]POC Directory:[/dim] {manager.poc_dir}")
    console.print(f"[dim]Knowledge Directory:[/dim] {manager.knowledge_dir}")

    console.print("\n[bold]Statistics:[/bold]")
    console.print(f"  Total bug reports: {meta.total_bug_reports}")
    console.print(f"  Completed: {meta.completed_reports}")
    console.print(f"  Passed: {meta.passed_reports}")
    console.print(f"  Failed: {meta.failed_reports}")
    console.print(f"  Pending: {meta.total_bug_reports - meta.completed_reports}")

    # Show pending reports
    pending = manager.get_pending_reports()
    if pending:
        console.print(f"\n[bold]Pending Reports ({len(pending)}):[/bold]")
        for report in pending[:10]:
            console.print(f"  - {report.stem}")
        if len(pending) > 10:
            console.print(f"  ... and {len(pending) - 10} more")


def _print_batch_summary(result: dict) -> None:
    """Print batch processing summary."""
    summary = result["summary"]

    console.print("\n[bold]Batch Processing Complete[/bold]")
    console.print(f"  Processed: {result['processed']}")
    console.print(f"  Passed: {summary['passed']}")
    console.print(f"  Flaky: {summary['flaky']}")
    console.print(f"  Failed: {summary['failed']}")
    console.print(f"  Incomplete: {summary['incomplete']}")


# =============================================================================
# Entry Point
# =============================================================================


def main():
    app()


if __name__ == "__main__":
    main()
