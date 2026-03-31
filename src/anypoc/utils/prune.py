#!/usr/bin/env python3
"""
Prune incomplete/errored runs from project output directories.

Usage:
    python -m anypoc.utils.prune <project> [--task TASK] [--dry-run]
    python -m anypoc.utils.prune all [--task poc]
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Callable, Iterator, Optional

import typer
from rich.console import Console
from rich.table import Table

from anypoc.project import Project, complete_project_name, get_all_projects
from anypoc.utils.trajectory import is_trajectory_complete

console = Console()


# =============================================================================
# Scan items — one dataclass per task, yielded by each iterator
# =============================================================================


@dataclass
class ScanJobTrajItem:
    """A trajectory file inside a scan job, plus the bug reports written by it."""

    job_dir: Path
    traj_json: Path
    related_reports: list[Path]

    @property
    def name(self) -> str:
        return f"{self.job_dir.name}/{self.traj_json.stem.replace('.traj', '')}"


@dataclass
class PocRunItem:
    """One run directory under poc/ (e.g. poc/<bug-name>/)."""

    run_dir: Path
    attempt_dirs: list[Path]

    @property
    def name(self) -> str:
        return self.run_dir.name


# =============================================================================
# Iterators — yield scan items for each task directory
# =============================================================================


def iter_scan_traj_items(task_dir: Path) -> Iterator[ScanJobTrajItem]:
    """Yield one ScanJobTrajItem per *.traj.json in any scan job's logs/.

    `task_dir` is the project's `scans/` directory; each subdir is one scan job.
    Bug reports are loosely associated with the job (not individual trajs), so
    we attach the whole job's reports to every traj item from that job — the
    filter decides whether to include them.
    """
    if not task_dir.is_dir():
        return

    for job_dir in sorted(task_dir.iterdir()):
        if not job_dir.is_dir() or job_dir.name.startswith("."):
            continue
        logs_dir = job_dir / "logs"
        reports_dir = job_dir / "reports"
        if not logs_dir.is_dir():
            continue
        related_reports = sorted(reports_dir.glob("*.md")) if reports_dir.is_dir() else []
        for traj_json in sorted(logs_dir.glob("*.traj.json")):
            yield ScanJobTrajItem(
                job_dir=job_dir,
                traj_json=traj_json,
                related_reports=related_reports,
            )


def iter_poc_runs(task_dir: Path) -> Iterator[PocRunItem]:
    """Yield one PocRunItem per subdirectory of poc/."""
    for run_dir in sorted(task_dir.iterdir()):
        if not run_dir.is_dir() or run_dir.name.startswith("."):
            continue
        attempt_dirs = sorted(d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("attempt_"))
        yield PocRunItem(run_dir=run_dir, attempt_dirs=attempt_dirs)


# =============================================================================
# Filters — each takes a scan item and returns paths to delete
# =============================================================================


def filter_incomplete_scan_traj(item: ScanJobTrajItem) -> list[Path]:
    """Delete just the incomplete traj file."""
    if not is_trajectory_complete(item.traj_json):
        return [item.traj_json]
    return []


filter_incomplete_scan_traj.description = "Incomplete scan traj files only"  # type: ignore[attr-defined]


def filter_incomplete_scan_job(item: ScanJobTrajItem) -> list[Path]:
    """If any traj in this job is incomplete, delete the whole scan job dir."""
    if not is_trajectory_complete(item.traj_json):
        return [item.job_dir]
    return []


filter_incomplete_scan_job.description = "Incomplete scan jobs (whole job dir)"  # type: ignore[attr-defined]


def filter_empty_runs(item: PocRunItem) -> list[Path]:
    if not item.attempt_dirs:
        return [item.run_dir]
    return []


filter_empty_runs.description = "Empty run dirs (no attempt_X)"  # type: ignore[attr-defined]


def _read_status(attempt_dir: Path) -> dict:
    status_file = attempt_dir / "status.json"
    try:
        return json.loads(status_file.read_text())
    except (json.JSONDecodeError, IOError, OSError):
        return {}


def filter_analysis_error(item: PocRunItem) -> list[Path]:
    for attempt_dir in item.attempt_dirs:
        status = _read_status(attempt_dir)
        if status.get("analysis", {}).get("status") != "pending":
            continue
        traj_file = attempt_dir / "trajs" / "bug_analyzer.traj.json"
        if traj_file.exists() and not is_trajectory_complete(traj_file):
            return [item.run_dir]
    return []


filter_analysis_error.description = "Errored analysis trajectories (whole run dir)"  # type: ignore[attr-defined]


def filter_poc_generation_error(item: PocRunItem) -> list[Path]:
    for attempt_dir in item.attempt_dirs:
        status = _read_status(attempt_dir)
        if status.get("generation", {}).get("status") != "pending":
            continue
        traj_file = attempt_dir / "trajs" / "poc_generation.traj.json"
        if not traj_file.exists():
            if status.get("analysis", {}).get("status") != "rejected":
                return [item.run_dir]
        elif is_trajectory_complete(traj_file):
            return [item.run_dir]
    return []


filter_poc_generation_error.description = "Errored poc_generation trajectories (whole run dir)"  # type: ignore[attr-defined]


def filter_rust_cache(item: PocRunItem) -> list[Path]:
    targets: list[Path] = []
    for cargo_toml in item.run_dir.rglob("Cargo.toml"):
        target_dir = cargo_toml.parent / "target"
        if target_dir.is_dir():
            targets.append(target_dir)
    return targets


filter_rust_cache.description = "Rust build cache (target/ dirs)"  # type: ignore[attr-defined]


# =============================================================================
# Registry — edit here to enable/disable prune behaviors (one line per combo)
# =============================================================================


@dataclass
class RegistryEntry:
    task: str
    iterator: Callable[[Path], Iterator[Any]]
    filter_fn: Callable[[Any], list[Path]]

    @property
    def description(self) -> str:
        return getattr(self.filter_fn, "description", self.filter_fn.__name__)


PRUNE_REGISTRY: list[RegistryEntry] = [
    RegistryEntry("scans", iter_scan_traj_items, filter_incomplete_scan_job),
    RegistryEntry("poc", iter_poc_runs, filter_empty_runs),
    RegistryEntry("poc", iter_poc_runs, filter_analysis_error),
    RegistryEntry("poc", iter_poc_runs, filter_poc_generation_error),
    RegistryEntry("poc", iter_poc_runs, filter_rust_cache),
]

VALID_TASKS: list[str] = sorted({e.task for e in PRUNE_REGISTRY})


# =============================================================================
# Core — collect, display, confirm, delete
# =============================================================================


@dataclass
class FilterResult:
    entry: RegistryEntry
    paths: list[Path] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.paths)


def _collect(projects: list[Project], tasks: list[str]) -> list[FilterResult]:
    """Run all active registry entries over the given projects/tasks."""
    active = [e for e in PRUNE_REGISTRY if e.task in tasks]
    results = {id(e): FilterResult(entry=e) for e in active}

    for project in projects:
        # Cache iterator output per (task, iterator) to avoid redundant I/O
        item_cache: dict[tuple[str, Any], list[Any]] = {}

        for entry in active:
            task_dir = project.output_dir / entry.task
            if not task_dir.is_dir():
                continue

            cache_key = (entry.task, entry.iterator)
            if cache_key not in item_cache:
                item_cache[cache_key] = list(entry.iterator(task_dir))

            for item in item_cache[cache_key]:
                paths = entry.filter_fn(item)
                results[id(entry)].paths.extend(paths)

    return list(results.values())


def _dedup(paths: list[Path]) -> list[Path]:
    """Remove paths that are descendants of other paths in the list."""
    unique = sorted(set(paths))
    return [p for p in unique if not any(p != a and p.is_relative_to(a) for a in unique)]


def _human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _print_stats(results: list[FilterResult]) -> None:
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Task", style="cyan")
    table.add_column("Filter")
    table.add_column("Paths", justify="right", style="yellow")

    total = 0
    for r in results:
        total += r.count
        table.add_row(r.entry.task, r.entry.description, str(r.count))

    table.add_section()
    table.add_row("", "[bold]Total[/bold]", f"[bold]{total}[/bold]")
    console.print(table)


def run_prune(projects: list[Project], tasks: list[str], dry_run: bool) -> None:
    results = _collect(projects, tasks)
    total = sum(r.count for r in results)

    if total == 0:
        console.print("[green]Nothing to prune.[/green]")
        return

    if dry_run:
        for r in results:
            if r.paths:
                console.print(f"\n[bold cyan]{r.entry.task}[/bold cyan] / {r.entry.description}:")
                for p in sorted(r.paths):
                    console.print(f"  {p}")
        console.print()

    _print_stats(results)

    if dry_run:
        console.print("\n[dim][DRY RUN] No files deleted.[/dim]")
        return

    try:
        confirm = input("\nProceed with deletion? [y/N]: ").strip().lower()
    except EOFError:
        confirm = "n"

    if confirm != "y":
        console.print("[yellow]Aborted.[/yellow]")
        return

    all_paths = _dedup([p for r in results for p in r.paths])
    deleted = 0
    for path in all_paths:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            deleted += 1
        except (OSError, IOError) as e:
            console.print(f"[red]Error deleting {path}: {e}[/red]")

    console.print(f"\n[green]Deleted {deleted} path(s).[/green]")


# =============================================================================
# CLI
# =============================================================================

app = typer.Typer(help="Prune incomplete/errored runs from project output directories")


@app.callback(invoke_without_command=True)
def prune(
    project: Annotated[
        str,
        typer.Argument(help="Project name or 'all'", autocompletion=complete_project_name),
    ],
    task: Annotated[
        Optional[str],
        typer.Option("--task", "-t", help=f"Task to prune: {', '.join(VALID_TASKS)} (default: all)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be deleted without deleting"),
    ] = False,
) -> None:
    """Prune incomplete/errored runs from project output directories."""
    if project == "all":
        projects = get_all_projects()
        if not projects:
            console.print("[red]No projects found.[/red]")
            raise typer.Exit(1)
    else:
        p = Project(project)
        if not p.output_dir.is_dir():
            console.print(f"[red]No output directory for project '{project}'.[/red]")
            raise typer.Exit(1)
        projects = [p]

    if task is None:
        tasks = VALID_TASKS
    elif task in VALID_TASKS:
        tasks = [task]
    else:
        console.print(f"[red]Unknown task '{task}'. Valid: {', '.join(VALID_TASKS)}[/red]")
        raise typer.Exit(1)

    run_prune(projects, tasks, dry_run=dry_run)


if __name__ == "__main__":
    app()
