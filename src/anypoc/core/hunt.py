"""Hunt mode: scan for bugs and generate PoCs concurrently.

A single orchestration driver runs a bug-scan strategy and streams each
yielded report into a bounded PoC worker pool. Scanner sessions pause at
safe boundaries (via `BackpressureGate`) when the PoC pool is saturated,
so reports don't pile up unboundedly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.console import Console

from anypoc.core.manager import POCManager
from anypoc.project import complete_project_name
from anypoc.utils import logger
from scanner.backpressure import BackpressureGate
from scanner.registry import get_strategy
from scanner.runner import run_scan_job
from scanner.strategies import (  # noqa: F401  -- triggers strategy registration
    commit_pr,
    focused,
    history,
)
from scanner.types import BugReport

LOG_PREFIX = "[Hunt]"

app = typer.Typer(help="Scan + PoC generation in one pass", no_args_is_help=True)
console = Console()


def _parse_kv(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise typer.BadParameter(f"Expected key=value, got {pair!r}.")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"Empty key in parameter {pair!r}.")
        if key in result:
            raise typer.BadParameter(f"Duplicate parameter {key!r}.")
        result[key] = value
    return result


def _resolve_source_code_dir(project: str, source_code_dir: Optional[Path]) -> Path:
    resolved = source_code_dir if source_code_dir is not None else Path.home() / project
    if not resolved.exists() or not resolved.is_dir():
        raise typer.BadParameter(f"Source code directory does not exist or is not a directory: {resolved}")
    return resolved


async def run_hunt(
    *,
    strategy_name: str,
    raw_inputs: dict[str, str],
    project_name: str,
    source_code_dir: Path,
    spend_limit: Optional[float],
    force: bool,
    parallel: int,
    disable_knowledge: bool,
    readonly_knowledge: bool,
    skip_analysis: bool,
    memory_limit: Optional[str],
) -> dict[str, Any]:
    """Drive a scan strategy and stream reports into a PoC worker pool."""

    strategy_cls = get_strategy(strategy_name)
    manager = POCManager(project_name)

    gate = BackpressureGate(max_inflight=parallel)
    poc_sem = asyncio.Semaphore(parallel)
    pending: set[asyncio.Task] = set()
    poc_results: list[dict[str, Any]] = []

    async def _poc_worker(report_path: Path) -> None:
        try:
            async with poc_sem:
                logger.info(f"{LOG_PREFIX} PoC start: {report_path.stem}")
                result = await manager.run_single(
                    report_path,
                    in_container=False,
                    extract_knowledge=not disable_knowledge and not readonly_knowledge,
                    disable_knowledge=disable_knowledge,
                    skip_analysis=skip_analysis,
                    readonly_knowledge=readonly_knowledge,
                    memory_limit=memory_limit,
                )
                poc_results.append(result)
                logger.info(f"{LOG_PREFIX} PoC done:  {report_path.stem} -> {result.get('best_status')}")
        except Exception as exc:
            logger.error(f"{LOG_PREFIX} PoC worker failed for {report_path.stem}: {exc}")
        finally:
            await gate.complete()

    async def _on_report(report: BugReport, report_path: Path) -> None:
        await gate.register()
        task = asyncio.create_task(_poc_worker(report_path))
        pending.add(task)
        task.add_done_callback(pending.discard)

    await run_scan_job(
        strategy_cls,
        raw_inputs,
        project_name=project_name,
        source_code_dir=source_code_dir,
        spend_limit=spend_limit,
        force=force,
        on_report=_on_report,
        backpressure=gate,
    )
    logger.info(f"{LOG_PREFIX} Scan done; waiting for {len(pending)} PoC task(s) to finish")
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    return {
        "poc_results": poc_results,
        "total_reports": len(poc_results),
    }


@app.command("run")
def cli_run(
    strategy: Annotated[str, typer.Argument(help="Strategy name (see `anypoc scan list`).")],
    params: Annotated[
        Optional[list[str]],
        typer.Argument(help="Strategy inputs as key=value pairs."),
    ] = None,
    project: Annotated[
        Optional[str],
        typer.Option(
            "--project", "-p", help="Project name (required for PoC generation).", autocompletion=complete_project_name
        ),
    ] = None,
    source_code_dir: Annotated[
        Optional[Path],
        typer.Option("--source-code-dir", help="Repository to scan. Defaults to ~/{project}."),
    ] = None,
    spend_limit: Annotated[
        Optional[float],
        typer.Option("--spend-limit", help="Maximum dollar spend for the scan side of the run."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Wipe and recreate the scan job directory if it already exists."),
    ] = False,
    parallel: Annotated[
        int,
        typer.Option(
            "--parallel", "-n", help="Max concurrent in-flight PoC tasks. Also the scanner's backpressure bound."
        ),
    ] = 3,
    no_knowledge: Annotated[bool, typer.Option("--no-knowledge", help="Disable knowledge features.")] = False,
    read_only_knowledge: Annotated[
        bool,
        typer.Option("--read-only-knowledge", help="Use existing knowledge but skip extraction."),
    ] = False,
    skip_analysis: Annotated[bool, typer.Option("--skip-analysis", help="Skip bug analysis step.")] = False,
    memory_limit: Annotated[
        Optional[str],
        typer.Option("--memory-limit", "-m", help="Docker container memory limit (e.g. '64g')."),
    ] = None,
) -> None:
    """Run a scan strategy and generate PoCs for each bug as it's discovered."""
    if not project:
        raise typer.BadParameter("--project is required for hunt mode (PoC generation needs a project context).")
    try:
        get_strategy(strategy)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc

    raw_inputs = _parse_kv(params or [])
    resolved_source = _resolve_source_code_dir(project, source_code_dir)

    summary = asyncio.run(
        run_hunt(
            strategy_name=strategy,
            raw_inputs=raw_inputs,
            project_name=project,
            source_code_dir=resolved_source,
            spend_limit=spend_limit,
            force=force,
            parallel=parallel,
            disable_knowledge=no_knowledge,
            readonly_knowledge=read_only_knowledge,
            skip_analysis=skip_analysis,
            memory_limit=memory_limit,
        )
    )

    statuses = [r.get("best_status") for r in summary["poc_results"]]
    passed = statuses.count("passed")
    flaky = statuses.count("flaky")
    incomplete = statuses.count("incomplete")
    failed = len(statuses) - passed - flaky - incomplete
    console.print(
        f"\n[bold]Hunt complete[/bold]: {summary['total_reports']} report(s) — "
        f"[green]{passed} passed[/green], {flaky} flaky, {failed} failed, {incomplete} incomplete"
    )
