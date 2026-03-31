"""Scanner CLI: list and run bug-scanning strategies."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from anypoc.project import Project, complete_project_name
from scanner.registry import all_strategies, get_strategy
from scanner.runner import run_scan_job
from scanner.strategies import (  # noqa: F401  -- triggers strategy registration
    commit_pr,
    focused,
    history,
)

app = typer.Typer(help="Bug-scanning strategies", no_args_is_help=True)
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_kv(pairs: list[str]) -> dict[str, str]:
    """Parse a list of `key=value` strings into a dict. Errors loudly on bad syntax."""
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise typer.BadParameter(f"Expected key=value, got {pair!r}. Use 'name=value' for each parameter.")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"Empty key in parameter {pair!r}.")
        if key in result:
            raise typer.BadParameter(f"Duplicate parameter {key!r}.")
        result[key] = value
    return result


def _resolve_source_code_dir(project: Optional[str], source_code_dir: Optional[Path]) -> Path:
    if source_code_dir is not None:
        resolved = source_code_dir
    elif project is not None:
        resolved = Path.home() / project
    else:
        raise typer.BadParameter(
            "Either --source-code-dir or --project must be provided to determine source code location"
        )
    if not resolved.exists():
        raise typer.BadParameter(f"Source code directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise typer.BadParameter(f"Source code path is not a directory: {resolved}")
    return resolved


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("list")
def list_strategies() -> None:
    """List all registered bug-scanning strategies."""
    strategies = all_strategies()
    if not strategies:
        console.print("[yellow]No strategies registered.[/yellow]")
        return

    table = Table(title="Bug-scanning strategies")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Parameters")

    for cls in strategies:
        param_lines = []
        for p in cls.params:
            marker = "" if p.required else f" (optional, default={p.default!r})"
            param_lines.append(f"{p.name}{marker}")
        table.add_row(cls.name, cls.description, "\n".join(param_lines) or "—")

    console.print(table)


@app.command("run")
def run_command(
    strategy: Annotated[str, typer.Argument(help="Strategy name (see `anypoc scan list`).")],
    params: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Strategy inputs as key=value pairs (e.g. time_range='last 6 months').",
        ),
    ] = None,
    project: Annotated[
        Optional[str],
        typer.Option(
            "--project",
            "-p",
            help="Project name. Determines output dir and source code dir.",
            autocompletion=complete_project_name,
        ),
    ] = None,
    source_code_dir: Annotated[
        Optional[Path],
        typer.Option("--source-code-dir", help="Repository to scan. Defaults to ~/{project}."),
    ] = None,
    spend_limit: Annotated[
        Optional[float],
        typer.Option(
            "--spend-limit",
            help="Maximum dollar spend for this run.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Wipe and recreate the scan job directory if it already exists.",
        ),
    ] = False,
) -> None:
    """Run a bug-scanning strategy as a scan job."""
    try:
        strategy_cls = get_strategy(strategy)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc

    raw_inputs = _parse_kv(params or [])

    if project is not None and not Project(project).exists():
        raise typer.BadParameter(f"Project '{project}' not found. Run `anypoc project init {project}` to create it.")

    resolved_source = _resolve_source_code_dir(project, source_code_dir)

    async def _go() -> None:
        await run_scan_job(
            strategy_cls,
            raw_inputs,
            project_name=project,
            source_code_dir=resolved_source,
            spend_limit=spend_limit,
            force=force,
        )

    asyncio.run(_go())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
