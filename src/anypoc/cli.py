#!/usr/bin/env python3
"""
Central CLI for AnyPoC.

Usage: anypoc <command> [options]
"""

from enum import Enum
from pathlib import Path
from shutil import which
from typing import Annotated
from typing import Optional

import typer

app = typer.Typer(
    name="anypoc",
    help="Central CLI for AnyPoC",
    no_args_is_help=True,
)


class SkillTarget(str, Enum):
    claude = "claude"
    codex = "codex"


def repo_skills_dir() -> Path:
    """Return the bundled skills directory."""
    return Path(__file__).resolve().parent.parent / "skills"


def user_skills_dir(target: SkillTarget) -> Path:
    """Return the per-agent user skills directory."""
    if target == SkillTarget.claude:
        return Path.home() / ".claude" / "skills"
    return Path.home() / ".agents" / "skills"


def target_display_name(target: SkillTarget) -> str:
    """Return a human-friendly agent name."""
    if target == SkillTarget.claude:
        return "Claude Code"
    return "Codex"


def is_target_installed(target: SkillTarget) -> bool:
    """Best-effort detection for whether an agent is installed locally."""
    if which(target.value):
        return True

    if target == SkillTarget.claude:
        markers = [Path.home() / ".claude"]
    else:
        markers = [Path.home() / ".codex", Path.home() / ".agents"]

    return any(marker.exists() for marker in markers)


def detected_skill_targets() -> list[SkillTarget]:
    """Return installed skill hosts in stable order."""
    return [target for target in SkillTarget if is_target_installed(target)]


def install_repo_skills(repo_dir: Path, install_dir: Path) -> None:
    """Symlink every bundled skill into one target skills directory."""
    install_dir.mkdir(parents=True, exist_ok=True)

    for skill_dir in sorted(repo_dir.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
            continue

        resolved_skill_dir = skill_dir.resolve()
        target = install_dir / skill_dir.name

        if target.is_symlink():
            existing = target.resolve()
            if existing == resolved_skill_dir:
                typer.echo(f"  {skill_dir.name}: already installed")
                continue
            target.unlink()
        elif target.exists():
            typer.echo(f"  {skill_dir.name}: skipped (non-symlink already exists at {target})")
            continue

        target.symlink_to(resolved_skill_dir)
        typer.echo(f"  {skill_dir.name}: installed -> {resolved_skill_dir}")


@app.command()
def install_skills(
    only: Annotated[
        Optional[SkillTarget],
        typer.Option("--only", help="Install skills only for one agent: claude or codex."),
    ] = None,
):
    """Install AnyPoC skills for Claude Code and/or Codex."""
    repo_dir = repo_skills_dir()
    if not repo_dir.is_dir():
        typer.echo(f"No skills directory found at {repo_dir}")
        raise typer.Exit(1)

    targets = [only] if only is not None else detected_skill_targets()
    if not targets:
        typer.echo("No Claude Code or Codex installation detected.")
        typer.echo("Use --only claude or --only codex to force installation.")
        raise typer.Exit(1)

    for index, target in enumerate(targets):
        if index:
            typer.echo("")

        install_dir = user_skills_dir(target)
        typer.echo(f"Installing skills for {target_display_name(target)} -> {install_dir}")
        install_repo_skills(repo_dir, install_dir)

    typer.echo("")
    typer.echo("Done. Claude Code uses ~/.claude/skills and Codex uses ~/.agents/skills.")


def main():
    """Main entry point for the CLI."""
    # Import and register subcommands here
    from anypoc.infra.build import app as infra_app
    from anypoc.core.manager import app as poc_app
    from anypoc.core.hunt import app as hunt_app
    from anypoc.project import app as project_app
    from scanner.cli import app as scan_app
    from anypoc.utils.prune import app as prune_app
    from anypoc.utils.spend_limit_cli import app as spend_limit_app
    from dashboard import app as web_app

    app.add_typer(infra_app, name="infra", help="Docker image management")
    app.add_typer(hunt_app, name="hunt", help="Concurrent bug scan + PoC generation")
    app.add_typer(poc_app, name="poc", help="POC generation management")
    app.add_typer(project_app, name="project", help="Project management")
    app.add_typer(prune_app, name="prune", help="Prune incomplete runs")
    app.add_typer(scan_app, name="scan", help="Bug-scanning strategies")
    app.add_typer(spend_limit_app, name="spend-limit", help="Spend limit management")
    app.add_typer(web_app, name="dashboard", help="POC web dashboard")

    app()


if __name__ == "__main__":
    main()
