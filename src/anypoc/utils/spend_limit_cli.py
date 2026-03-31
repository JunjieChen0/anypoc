"""CLI for managing spend limits and viewing cost history."""

from __future__ import annotations

from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from anypoc.project import complete_project_name
from anypoc.utils.spend_limit import GlobalCostStore, ProjectCostStore

console = Console()

app = typer.Typer(help="Spend limit management")


@app.command("set")
def set_limit(
    amount: Annotated[float, typer.Argument(help="Dollar limit to set")],
    project: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--project", help="Set a project limit (otherwise sets overall)", autocompletion=complete_project_name
        ),
    ] = None,
) -> None:
    """Set a spend limit. Without --project, sets the overall limit."""
    store = GlobalCostStore.load()
    if project:
        store.set_project_limit(project, amount)
        store.save()
        console.print(f"Project '{project}' spend limit set to ${amount:.2f}")
    else:
        store.overall_limit = amount
        store.save()
        console.print(f"Overall spend limit set to ${amount:.2f}")


@app.command("clear")
def clear_limit(
    project: Annotated[
        Optional[str],
        typer.Option("-p", "--project", help="Clear a project limit", autocompletion=complete_project_name),
    ] = None,
    overall: Annotated[bool, typer.Option("--overall", help="Clear the overall limit")] = False,
) -> None:
    """Remove a spend limit (does not reset spend counters)."""
    store = GlobalCostStore.load()
    if project:
        store.set_project_limit(project, None)
        store.save()
        console.print(f"Project '{project}' spend limit cleared")
    elif overall:
        store.overall_limit = None
        store.save()
        console.print("Overall spend limit cleared")
    else:
        console.print("[yellow]Specify --overall or --project NAME[/yellow]")
        raise typer.Exit(1)


@app.command("reset")
def reset_spend(
    project: Annotated[
        Optional[str],
        typer.Option("-p", "--project", help="Reset spend for a project", autocompletion=complete_project_name),
    ] = None,
    overall: Annotated[bool, typer.Option("--overall", help="Reset the overall spend counter")] = False,
) -> None:
    """Reset spend counters (does not change limits)."""
    if project:
        pstore = ProjectCostStore.load(project)
        pstore.reset()
        pstore.save()
        console.print(f"Project '{project}' spend counters reset")
    elif overall:
        store = GlobalCostStore.load()
        store.overall_total_cost = 0.0
        store.save()
        console.print("Overall spend counter reset")
    else:
        console.print("[yellow]Specify --overall or --project NAME[/yellow]")
        raise typer.Exit(1)


@app.command("show")
def show_limits(
    project: Annotated[
        Optional[str],
        typer.Option(
            "-p", "--project", help="Show details for a specific project", autocompletion=complete_project_name
        ),
    ] = None,
) -> None:
    """Show current spend limits and usage."""
    store = GlobalCostStore.load()

    # -- Overall -----------------------------------------------------------
    console.print()
    overall_limit_s = f"${store.overall_limit:.2f}" if store.overall_limit is not None else "[dim]not set[/dim]"
    console.print(f"[bold]Overall[/bold]  limit: {overall_limit_s}  spent: ${store.overall_total_cost:.4f}")

    # -- Project limits ----------------------------------------------------
    if store.project_limits:
        console.print()
        table = Table(title="Project Limits", show_header=True, header_style="bold")
        table.add_column("Project")
        table.add_column("Limit", justify="right")
        table.add_column("Spent", justify="right")
        table.add_column("Remaining", justify="right")

        for pname, plimit in sorted(store.project_limits.items()):
            pstore = ProjectCostStore.load(pname)
            spent = pstore.total_cost
            remaining = plimit - spent
            style = "red" if remaining < 0 else ""
            table.add_row(
                pname,
                f"${plimit:.2f}",
                f"${spent:.4f}",
                f"[{style}]${remaining:.4f}[/{style}]" if style else f"${remaining:.4f}",
            )
        console.print(table)

    # -- Detailed project view ---------------------------------------------
    if project:
        pstore = ProjectCostStore.load(project)
        if pstore.tasks:
            console.print()
            table = Table(title=f"Cost History: {project}", show_header=True, header_style="bold")
            table.add_column("Task")
            table.add_column("Total Cost", justify="right")
            table.add_column("Count", justify="right")
            table.add_column("Average", justify="right")

            for tname, tdata in sorted(pstore.tasks.items()):
                total = tdata.get("total_cost", 0.0)
                count = tdata.get("count", 0)
                avg = total / count if count > 0 else 0.0
                table.add_row(tname, f"${total:.4f}", str(count), f"${avg:.4f}")

            console.print(table)
        else:
            console.print(f"\n[dim]No cost history for project '{project}'[/dim]")

    console.print()
