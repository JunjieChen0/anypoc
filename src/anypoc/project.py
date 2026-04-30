"""Project information representation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from anypoc.infra.build import (
    IMAGE_PREFIX,
    ImageInfo,
    ImageType,
    build_image,
    check_image_status,
    get_local_image_created,
    pull_image,
)
from anypoc.utils import OUTPUT_DIR, PROJECTS_DIR

console = Console()


class Project:
    """Represents a project with static and dynamic information."""

    def __init__(self, name: str):
        self.name = name

    @property
    def config_dir(self) -> Path:
        """Get the directory for static project config (projects/{name}/)."""
        return PROJECTS_DIR / self.name

    @property
    def output_dir(self) -> Path:
        """Get the directory for dynamically generated output (output/{name}/)."""
        return OUTPUT_DIR / self.name

    @property
    def scans_dir(self) -> Path:
        """Get the directory containing scan jobs."""
        return self.output_dir / "scans"

    @property
    def poc_dir(self) -> Path:
        """Get the directory containing POC outputs."""
        return self.output_dir / "poc"

    @property
    def paths_file(self) -> Path:
        return self.config_dir / "paths.md"

    @property
    def dockerfile(self) -> Path:
        return self.config_dir / "Dockerfile"

    @property
    def prompts_dir(self) -> Path:
        """Get the directory containing custom prompts."""
        return self.config_dir / "prompts"

    @property
    def bug_report_format_file(self) -> Path:
        """Get the bug report format prompt file (legacy location fallback)."""
        # Check new location first, then fall back to legacy location
        new_path = self.prompts_dir / "bug_report_format.md"
        if new_path.exists():
            return new_path
        legacy_path = self.config_dir / "bug_report_format.md"
        if legacy_path.exists():
            return legacy_path
        return new_path  # Return new location for creation

    @property
    def analysis_prompt_file(self) -> Path:
        """Get the analysis step prompt file."""
        return self.prompts_dir / "analysis.md"

    @property
    def poc_gen_prompt_file(self) -> Path:
        """Get the POC generation step prompt file."""
        return self.prompts_dir / "poc_gen.md"

    @property
    def evidence_prompt_file(self) -> Path:
        """Get the evidence checking step prompt file."""
        return self.prompts_dir / "evidence.md"

    def get_custom_prompts(self) -> dict[str, str | None]:
        """
        Load all custom prompts for this project.

        Returns:
            Dictionary with prompt names as keys and content as values.
            Value is None if the prompt file doesn't exist.
        """
        prompts = {}
        prompt_files = {
            "analysis": self.analysis_prompt_file,
            "poc_gen": self.poc_gen_prompt_file,
            "evidence": self.evidence_prompt_file,
            "bug_report_format": self.bug_report_format_file,
        }
        for name, path in prompt_files.items():
            prompts[name] = path.read_text() if path.exists() else None
        return prompts

    def exists(self) -> bool:
        return self.config_dir.exists()

    def get_bug_reports(self) -> list[Path]:
        """Find all bug report files (markdown) across all scan jobs for this project."""
        if not self.scans_dir.exists():
            return []
        reports = list(self.scans_dir.glob("*/reports/*.md"))
        return sorted(reports)

    def get_poc_output_dir(self, bug_report: Path) -> Path:
        """Get the POC output directory for a bug report."""
        return self.poc_dir / bug_report.stem

    def has_existing_run(self, bug_report: Path) -> bool:
        """Check if a bug report already has a POC run."""
        poc_output = self.get_poc_output_dir(bug_report)
        if not poc_output.exists():
            return False
        attempts = list(poc_output.glob("attempt_*"))
        return len(attempts) > 0

    def filter_pending(self, reports: list[Path]) -> list[Path]:
        """Filter to bug reports that don't have a POC run yet."""
        return [r for r in reports if not self.has_existing_run(r)]

    def get_image_info(self) -> ImageInfo:
        """Get ImageInfo for this project's Docker image."""
        return ImageInfo(
            name=f"{IMAGE_PREFIX}-{self.name}",
            dockerfile=self.dockerfile,
            image_type=ImageType.PROJECT,
        )


def get_all_projects() -> list[Project]:
    """Get all available projects."""
    if not PROJECTS_DIR.exists():
        return []
    projects = []
    for project_dir in sorted(PROJECTS_DIR.iterdir()):
        if project_dir.is_dir():
            project = Project(project_dir.name)
            if project.dockerfile.exists():
                projects.append(project)
    return projects


def complete_project_name(incomplete: str) -> list[str]:
    """Autocomplete project names for shell completion."""
    projects = get_all_projects()
    names = [p.name for p in projects if p.name.startswith(incomplete)]
    if "all".startswith(incomplete):
        names.insert(0, "all")
    return names


# CLI
app = typer.Typer(help="Project management commands")


PATHS_TEMPLATE = """Path to source code:

Path to built binary:
"""

BUG_REPORT_FORMAT_TEMPLATE = """# Title: should be within 100 characters

## Proof-of-Concept

<!-- Brief description of the PoC: what it does and what it shows -->

## Vulnerable code analysis

<!-- Briefly explain the bug with code snippets (include relative paths and line numbers) -->

## Impact

<!-- Explain the consequence. If it has any security impact, explain the threat model. -->
"""


DOCKERFILE_TEMPLATE = """# {name} project image
# Extends the shared anypoc base image with {name} source and build

FROM zzjas/anypoc-common:latest

USER root
WORKDIR /opt/{name}

# TODO: Add project-specific setup
# - Clone source directly into /opt/{name} (the WORKDIR). Do NOT add an extra
#   src/ subdir — clone with `git clone <url> .` so files land at /opt/{name}/.
# - Keep large source/build trees under /opt/{name} so runtime UID remapping stays fast
# - Install dependencies
# - Build with sanitizers

CMD ["/bin/bash"]
"""


@app.command()
def init(name: str = typer.Argument(..., help="Name of the project to initialize")):
    """Initialize a new project with template files."""
    project = Project(name)

    if project.config_dir.exists():
        typer.echo(f"Project '{name}' already exists at {project.config_dir}")
        raise typer.Exit(1)

    # Create config directory and prompt subdirectories
    project.config_dir.mkdir(parents=True, exist_ok=True)
    project.prompts_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Created project directory: {project.config_dir}")

    # Create template files
    templates = [
        (project.paths_file, PATHS_TEMPLATE),
        (project.dockerfile, DOCKERFILE_TEMPLATE.format(name=name)),
    ]

    for filepath, content in templates:
        filepath.write_text(content)
        typer.echo(f"  Created: {filepath.name}")

    # Create prompt files
    typer.echo("  Created: prompts/")
    project.bug_report_format_file.write_text(BUG_REPORT_FORMAT_TEMPLATE.format(name=name))
    typer.echo(f"    Created: {project.bug_report_format_file.name}")

    # Create empty prompt files
    for prompt_file in [project.analysis_prompt_file, project.poc_gen_prompt_file, project.evidence_prompt_file]:
        prompt_file.touch()
        typer.echo(f"    Created: {prompt_file.name}")

    typer.echo(f"\nProject '{name}' initialized.")
    typer.echo("Run the AnyPoC skill in Claude Code or Codex to configure it interactively.")


@app.command()
def status(
    name: str = typer.Argument(..., help="Name of the project to inspect", autocompletion=complete_project_name),
    local: Annotated[bool, typer.Option("--local", "-l", help="Skip remote registry check for image status")] = False,
):
    """Inspect the status of a project."""
    project = Project(name)

    typer.echo(f"\n{'=' * 50}")
    typer.echo(f"Project: {name}")
    typer.echo(f"{'=' * 50}")

    # Config status
    typer.echo("\n[Config Files]")
    config_files = [
        ("Dockerfile", project.dockerfile),
        ("paths.md", project.paths_file),
    ]
    for label, path in config_files:
        exists = "[x]" if path.exists() else "[ ]"
        typer.echo(f"  {exists} {label}")

    # Prompts status
    typer.echo("\n[Prompts]")
    prompt_files = [
        ("analysis.md", project.analysis_prompt_file),
        ("poc_gen.md", project.poc_gen_prompt_file),
        ("evidence.md", project.evidence_prompt_file),
        ("bug_report_format.md", project.bug_report_format_file),
    ]
    for label, path in prompt_files:
        exists = "[x]" if path.exists() else "[ ]"
        typer.echo(f"  {exists} {label}")

    if not project.exists():
        typer.echo(f"\nProject '{name}' not found at {project.config_dir}")
        typer.echo(f"Run 'python -m poc.project init {name}' to create it.")
        raise typer.Exit(1)

    # Docker image status
    image = project.get_image_info()
    image_status, image_info = check_image_status(image, skip_remote=local)
    console.print(f"\n[Docker Image] ({image.full_name})")
    console.print(f"  Status:  {_get_status_str(image_status.value)}")
    console.print(f"  Built:   {image_info.get('local_created') or '-'}")
    if image_info.get("local_digest"):
        console.print(f"  Local:   {image_info['local_digest']}")
    if image_info.get("remote_digest"):
        console.print(f"  Remote:  {image_info['remote_digest']}")
    if image_info.get("dockerfile_newer"):
        console.print("  [yellow]⚠ Dockerfile is newer than the built image — consider rebuilding[/yellow]")

    # Output status
    typer.echo(f"\n[Output Data] ({project.output_dir})")

    scan_jobs = [d for d in project.scans_dir.iterdir() if d.is_dir()] if project.scans_dir.exists() else []
    bug_reports = project.get_bug_reports()
    pending_reports = project.filter_pending(bug_reports)

    typer.echo(f"  Scan Jobs:   {len(scan_jobs)}")
    typer.echo(f"  Bug Reports: {len(bug_reports)}")
    if bug_reports:
        typer.echo(f"    - Pending: {len(pending_reports)}")
        typer.echo(f"    - With POC: {len(bug_reports) - len(pending_reports)}")

    # POC status
    if project.poc_dir.exists():
        poc_dirs = [d for d in project.poc_dir.iterdir() if d.is_dir()]
        typer.echo(f"  POC Runs:    {len(poc_dirs)}")

    typer.echo("")


# ---------------------------------------------------------------------------
# Image commands
# ---------------------------------------------------------------------------


def _get_status_str(status_value: str) -> str:
    """Convert status value to styled string."""
    if status_value == "local_latest":
        return "[green]✓ Up to date[/green]"
    elif status_value == "local_stale":
        return "[yellow]⚠ Stale[/yellow]"
    elif status_value == "local_only":
        return "[blue]● Local only[/blue]"
    elif status_value == "remote_only":
        return "[dim]○ Remote only[/dim]"
    else:
        return "[dim]- Not built[/dim]"


@app.command("list")
@app.command("ls", hidden=True)
def cmd_list(
    local: Annotated[bool, typer.Option("--local", "-l", help="Skip remote registry check")] = False,
):
    """List all project images and their status."""
    projects = get_all_projects()
    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        return

    table = Table(title="Project Images")
    table.add_column("Project", style="cyan")
    table.add_column("Status")
    table.add_column("Built", style="dim")

    # Fetch status in parallel when checking remote
    def fetch_status(project: Project) -> tuple[Project, str, str | None]:
        image = project.get_image_info()
        status, _info = check_image_status(image, skip_remote=local)
        built_time = get_local_image_created(image.full_name)
        return project, status.value, built_time

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(fetch_status, projects))

    for project, status_value, built_time in results:
        status_str = _get_status_str(status_value)
        built_str = built_time or "-"
        table.add_row(project.name, status_str, built_str)

    console.print(table)


def _build_one(
    name: str,
    no_cache: bool,
    push: bool,
    memory: str,
) -> bool:
    """Build a single project. Returns True on success, False on failure."""
    project = Project(name)
    if not project.exists():
        console.print(f"[red]Project '{name}' not found.[/red]")
        return False

    project_image = project.get_image_info()
    if not project.dockerfile.exists():
        console.print(f"[red]Dockerfile not found for project '{name}'.[/red]")
        return False

    return build_image(project_image, no_cache=no_cache, push=push, memory=memory)


@app.command()
def build(
    name: Annotated[
        str,
        typer.Argument(help="Project name to build (use 'all' for all projects)", autocompletion=complete_project_name),
    ],
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Build without cache")] = False,
    push: Annotated[bool, typer.Option("--push", help="Push after building")] = False,
    memory: Annotated[str, typer.Option("--memory", "-m", help="Memory limit (e.g., 64g, 128g)")] = "128g",
):
    """Build project Docker images. Use 'all' to build all projects."""
    if name == "all":
        projects = get_all_projects()
        if not projects:
            console.print("[red]No projects found.[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]Building all {len(projects)} projects...[/bold]\n")
        succeeded = []
        failed = []

        for project in projects:
            console.print(f"\n[bold cyan]{'=' * 60}[/bold cyan]")
            console.print(f"[bold cyan]Building {project.name}...[/bold cyan]")
            console.print(f"[bold cyan]{'=' * 60}[/bold cyan]")
            if _build_one(project.name, no_cache=no_cache, push=push, memory=memory):
                succeeded.append(project.name)
            else:
                failed.append(project.name)

        # Print summary
        console.print(f"\n[bold]{'=' * 60}[/bold]")
        console.print("[bold]Build Summary[/bold]")
        console.print(f"[bold]{'=' * 60}[/bold]")
        console.print(f"  Total:     {len(projects)}")
        console.print(f"  [green]Succeeded: {len(succeeded)}[/green]")
        console.print(f"  [red]Failed:    {len(failed)}[/red]")
        if succeeded:
            console.print(f"\n[green]Succeeded:[/green] {', '.join(succeeded)}")
        if failed:
            console.print(f"\n[red]Failed:[/red] {', '.join(failed)}")
            raise typer.Exit(1)
    else:
        if not _build_one(name, no_cache=no_cache, push=push, memory=memory):
            raise typer.Exit(1)


@app.command()
def pull(
    name: Annotated[str, typer.Argument(help="Project name to pull", autocompletion=complete_project_name)],
):
    """Pull a project's Docker image from registry."""
    project = Project(name)
    if not project.exists():
        console.print(f"[red]Project '{name}' not found.[/red]")
        raise typer.Exit(1)

    image = project.get_image_info()
    pull_image(image)


if __name__ == "__main__":
    app()
