#!/usr/bin/env python3
"""
Docker image management for anypoc infrastructure images.

This module manages the shared base image. Project-specific images are managed
via poc.project.

Exports functions for building/pulling/pushing images that can be used by other
modules (like poc.project).
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from anypoc.infra.executor import _caw_auth_docker_args, get_forwarded_env_args
from anypoc.utils import PROJECT_ROOT

console = Console()

app = typer.Typer(
    name="infra",
    help="Docker image management for anypoc infrastructure images",
    no_args_is_help=True,
)

# Configuration
REGISTRY = "docker.io"
NAMESPACE = "zzjas"
IMAGE_PREFIX = "anypoc"

# Base images directory (relative to this script)
INFRA_DIR = Path(__file__).parent


class ImageStatus(Enum):
    """Status of an image comparing local and remote."""

    LOCAL_LATEST = "local_latest"  # Local matches remote
    LOCAL_STALE = "local_stale"  # Local exists but differs from remote
    LOCAL_ONLY = "local_only"  # Local exists, no remote
    REMOTE_ONLY = "remote_only"  # Remote exists, no local
    NOT_FOUND = "not_found"  # Neither local nor remote exists


class ImageType(Enum):
    """Type of Docker image."""

    BASE = "base"  # Base infrastructure images
    PROJECT = "project"  # Project-specific images (e.g., firefox, chromium)


@dataclass
class ImageInfo:
    """Information about a Docker image."""

    name: str
    dockerfile: Path
    tag: str = "latest"
    base_image: Optional[str] = None  # Optional local image dependency for the Docker build
    image_type: ImageType = ImageType.BASE
    local_only: bool = False  # If True, cannot be pushed to registry

    @property
    def full_name(self) -> str:
        """Full image name with tag."""
        return f"{self.name}:{self.tag}"

    @property
    def remote_name(self) -> str:
        """Full remote image name including registry/namespace."""
        if NAMESPACE:
            return f"{REGISTRY}/{NAMESPACE}/{self.name}:{self.tag}"
        return f"{self.name}:{self.tag}"


# ---------------------------------------------------------------------------
# Command builders (pure functions returning command lists)
# ---------------------------------------------------------------------------


def get_build_cmd(
    image: "ImageInfo",
    no_cache: bool = False,
    memory: Optional[str] = None,
    base_image_name: Optional[str] = None,
    build_args: Optional[dict[str, str]] = None,
) -> list[str]:
    """Build the docker build command for an image.

    Args:
        image: The image to build
        no_cache: Whether to use --no-cache
        memory: Memory limit for the build (e.g., "64g", "128g")
        base_image_name: Optional local base image name to pass as --build-arg BASE_IMAGE

    Returns:
        Command list ready for subprocess
    """
    cmd = [
        "docker",
        "build",
        "-f",
        str(image.dockerfile),
        "-t",
        image.full_name,
    ]
    if base_image_name:
        cmd.extend(["--build-arg", f"BASE_IMAGE={base_image_name}"])
    if build_args:
        for key, value in build_args.items():
            cmd.extend(["--build-arg", f"{key}={value}"])
    if no_cache:
        cmd.append("--no-cache")
    if memory:
        cmd.extend(["--memory", memory])
    cmd.append(str(PROJECT_ROOT))
    return cmd


def get_pull_cmd(image: "ImageInfo") -> list[str]:
    """Build the docker pull command for an image."""
    return ["docker", "pull", image.remote_name]


def get_push_cmd(image: "ImageInfo") -> list[str]:
    """Build the docker push command for an image."""
    return ["docker", "push", image.remote_name]


def get_tag_cmd(source: str, target: str) -> list[str]:
    """Build the docker tag command."""
    return ["docker", "tag", source, target]


def get_env_build_args() -> dict[str, str]:
    """Collect build args from environment variables."""
    build_args: dict[str, str] = {}
    cache_bust = os.environ.get("CACHE_BUST")
    if cache_bust is not None:
        build_args["CACHE_BUST"] = cache_bust
    # Bake the host user's UID/GID into the playground account so files chowned
    # to playground inside the image (e.g. /opt/<project>) are owned by the same
    # UID on the host. Avoids the need for runtime usermod remapping.
    build_args["PLAYGROUND_UID"] = str(os.getuid())
    build_args["PLAYGROUND_GID"] = str(os.getgid())
    return build_args


# Define the infrastructure images
BASE_IMAGES: dict[str, ImageInfo] = {
    "base": ImageInfo(
        name=f"{IMAGE_PREFIX}-base",
        dockerfile=INFRA_DIR / "base.Dockerfile",
        image_type=ImageType.BASE,
    ),
    "common": ImageInfo(
        name=f"{IMAGE_PREFIX}-common",
        dockerfile=INFRA_DIR / "common.Dockerfile",
        base_image="base",
        image_type=ImageType.BASE,
    ),
}

# For infra commands, only infrastructure images are available.
IMAGES: dict[str, ImageInfo] = BASE_IMAGES


def run_cmd(cmd: list[str], capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        if capture:
            console.print(f"[red]Command failed:[/red] {' '.join(cmd)}")
            if e.stdout:
                console.print(f"[dim]stdout:[/dim] {e.stdout}")
            if e.stderr:
                console.print(f"[dim]stderr:[/dim] {e.stderr}")
        raise


def get_local_image_digest(image_name: str) -> Optional[str]:
    """Get the digest of a local image."""
    try:
        result = run_cmd(
            ["docker", "inspect", "--format", "{{.Id}}", image_name],
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_remote_image_digest(image_name: str) -> Optional[str]:
    """Get the digest of a remote image from registry."""
    try:
        # Use docker manifest inspect for remote digest
        result = run_cmd(
            ["docker", "manifest", "inspect", image_name],
            check=False,
        )
        if result.returncode == 0:
            manifest = json.loads(result.stdout)
            # Get the digest from manifest
            if "config" in manifest and "digest" in manifest["config"]:
                return manifest["config"]["digest"]
            # For manifest lists, return the overall digest
            return manifest.get("digest", result.stdout.strip()[:64])
    except Exception:
        pass
    return None


def get_local_image_created(image_name: str) -> Optional[str]:
    """Get the creation timestamp of a local image."""
    try:
        result = run_cmd(
            ["docker", "inspect", "--format", "{{.Created}}", image_name],
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:19]  # Trim to readable format
    except Exception:
        pass
    return None


def get_local_image_created_datetime(image_name: str) -> Optional[datetime]:
    """Get the creation timestamp of a local image as a datetime object."""
    try:
        result = run_cmd(
            ["docker", "inspect", "--format", "{{.Created}}", image_name],
            check=False,
        )
        if result.returncode == 0:
            timestamp_str = result.stdout.strip()
            # Parse ISO format timestamp (e.g., 2024-01-15T10:30:00.123456789Z)
            # Truncate nanoseconds to microseconds for Python compatibility
            if "." in timestamp_str:
                base, frac = timestamp_str.split(".")
                # Handle timezone suffix
                if frac.endswith("Z"):
                    frac = frac[:-1]
                    tz_suffix = "+00:00"
                elif "+" in frac:
                    frac, tz_suffix = frac.split("+")
                    tz_suffix = "+" + tz_suffix
                elif "-" in frac:
                    frac, tz_suffix = frac.rsplit("-", 1)
                    tz_suffix = "-" + tz_suffix
                else:
                    tz_suffix = "+00:00"
                # Truncate to 6 digits (microseconds)
                frac = frac[:6]
                timestamp_str = f"{base}.{frac}{tz_suffix}"
                return datetime.fromisoformat(timestamp_str)
            else:
                return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def get_dockerfile_mtime(dockerfile: Path) -> Optional[datetime]:
    """Get the modification time of a Dockerfile."""
    try:
        if dockerfile.exists():
            mtime = dockerfile.stat().st_mtime
            return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception:
        pass
    return None


def is_dockerfile_newer(image: "ImageInfo") -> Optional[bool]:
    """Check if the Dockerfile is newer than the built image.

    Returns:
        True if Dockerfile is newer than image
        False if image is newer than Dockerfile
        None if comparison cannot be made (missing image or Dockerfile)
    """
    image_created = get_local_image_created_datetime(image.full_name)
    dockerfile_mtime = get_dockerfile_mtime(image.dockerfile)

    if image_created is None or dockerfile_mtime is None:
        return None

    return dockerfile_mtime > image_created


def check_image_status(image: ImageInfo, skip_remote: bool = False) -> tuple[ImageStatus, dict]:
    """Check the status of an image (local vs remote)."""
    local_digest = get_local_image_digest(image.full_name)

    # Skip remote check for local-only images or if explicitly requested
    remote_digest = None
    if NAMESPACE and not image.local_only and not skip_remote:
        remote_digest = get_remote_image_digest(image.remote_name)

    # Check if Dockerfile is newer than the image
    dockerfile_newer = is_dockerfile_newer(image)

    info = {
        "local_digest": local_digest[:12] if local_digest else None,
        "remote_digest": remote_digest[:12] if remote_digest else None,
        "local_created": get_local_image_created(image.full_name),
        "local_only": image.local_only,
        "dockerfile_newer": dockerfile_newer,
    }

    if image.local_only:
        # Local-only images only check local status
        if local_digest:
            status = ImageStatus.LOCAL_ONLY
        else:
            status = ImageStatus.NOT_FOUND
    elif local_digest and remote_digest:
        # Both exist - compare them
        # Note: Local ID and remote digest are different formats,
        # so we can't directly compare. We'll mark as potentially stale.
        status = ImageStatus.LOCAL_LATEST  # Assume latest if both exist
        info["note"] = "Use --pull to ensure latest"
    elif local_digest and not remote_digest:
        status = ImageStatus.LOCAL_ONLY
    elif not local_digest and remote_digest:
        status = ImageStatus.REMOTE_ONLY
    else:
        status = ImageStatus.NOT_FOUND

    return status, info


def get_build_order() -> list[str]:
    """Get the build order for infrastructure images."""
    return list(BASE_IMAGES.keys())


def build_image(image: ImageInfo, no_cache: bool = False, push: bool = False, memory: Optional[str] = None) -> bool:
    """Build a single image."""
    console.print(f"\n[bold]Building {image.full_name}...[/bold]")

    if not image.dockerfile.exists():
        console.print(f"[red]Dockerfile not found:[/red] {image.dockerfile}")
        return False

    # For images with dependencies, check that the base image exists
    base_image_name = None
    if image.base_image:
        base_info = IMAGES[image.base_image]
        base_image_name = base_info.full_name
        if not get_local_image_digest(base_image_name):
            console.print(f"[red]Dependency '{base_image_name}' not found[/red]")
            console.print(f"[dim]  Run: p infra build {image.base_image} first[/dim]")
            return False
        console.print(f"[dim]  Base: {base_image_name}[/dim]")

    cmd = get_build_cmd(
        image,
        no_cache=no_cache,
        memory=memory,
        base_image_name=base_image_name,
        build_args=get_env_build_args(),
    )

    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

    try:
        # Run without capture to show build output
        subprocess.run(cmd, check=True)
        console.print(f"[green]✓ Built {image.full_name}[/green]")

        # Only push if not a local-only image
        if push and NAMESPACE and not image.local_only:
            push_image(image)
        elif push and image.local_only:
            console.print(f"[dim]Skipping push for local-only image {image.full_name}[/dim]")

        return True
    except subprocess.CalledProcessError:
        console.print(f"[red]✗ Failed to build {image.full_name}[/red]")
        return False


def push_image(image: ImageInfo) -> bool:
    """Push an image to the remote registry."""
    if image.local_only:
        console.print(f"[yellow]Skipping push for local-only image: {image.full_name}[/yellow]")
        return False

    if not NAMESPACE:
        console.print("[yellow]No NAMESPACE configured, skipping push[/yellow]")
        return False

    console.print(f"\n[bold]Pushing {image.remote_name}...[/bold]")

    # Tag for remote
    run_cmd(get_tag_cmd(image.full_name, image.remote_name))

    try:
        subprocess.run(get_push_cmd(image), check=True)
        console.print(f"[green]✓ Pushed {image.remote_name}[/green]")
        return True
    except subprocess.CalledProcessError:
        console.print(f"[red]✗ Failed to push {image.remote_name}[/red]")
        return False


def pull_image(image: ImageInfo) -> bool:
    """Pull an image from the remote registry."""
    if image.local_only:
        console.print(f"[yellow]Skipping pull for local-only image: {image.full_name}[/yellow]")
        return False

    if not NAMESPACE:
        console.print("[yellow]No NAMESPACE configured, skipping pull[/yellow]")
        return False

    console.print(f"\n[bold]Pulling {image.remote_name}...[/bold]")

    try:
        subprocess.run(get_pull_cmd(image), check=True)
        # Tag as local name
        run_cmd(get_tag_cmd(image.remote_name, image.full_name))
        console.print(f"[green]✓ Pulled {image.full_name}[/green]")
        return True
    except subprocess.CalledProcessError:
        console.print(f"[red]✗ Failed to pull {image.remote_name}[/red]")
        return False


def _create_image_table(title: str) -> Table:
    """Create a table for displaying image status."""
    table = Table(title=title)
    table.add_column("Image", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Local ID", style="dim")
    table.add_column("Created", style="dim")
    table.add_column("Dockerfile", style="dim")
    table.add_column("Freshness", style="bold")
    return table


def _get_status_style(status: ImageStatus, local_only: bool = False) -> str:
    """Get the display style for an image status."""
    if local_only and status == ImageStatus.LOCAL_ONLY:
        return "[blue]● Local[/blue]"
    styles = {
        ImageStatus.LOCAL_LATEST: "[green]✓ Local (latest)[/green]",
        ImageStatus.LOCAL_STALE: "[yellow]⚠ Local (stale)[/yellow]",
        ImageStatus.LOCAL_ONLY: "[blue]● Local only[/blue]",
        ImageStatus.REMOTE_ONLY: "[yellow]↓ Remote only[/yellow]",
        ImageStatus.NOT_FOUND: "[red]✗ Not built[/red]",
    }
    return styles.get(status, str(status))


def _get_freshness_style(dockerfile_newer: Optional[bool]) -> str:
    """Get the display style for Dockerfile freshness."""
    if dockerfile_newer is None:
        return "[dim]-[/dim]"
    elif dockerfile_newer:
        return "[yellow]⚠ Rebuild needed[/yellow]"
    else:
        return "[green]✓ Up to date[/green]"


def _add_images_to_table(table: Table, images: dict[str, ImageInfo], skip_remote: bool = False) -> None:
    """Add images to a table with their status."""
    for key, image in images.items():
        status, info = check_image_status(image, skip_remote=skip_remote)
        try:
            dockerfile_rel = image.dockerfile.relative_to(PROJECT_ROOT)
        except ValueError:
            dockerfile_rel = image.dockerfile
        table.add_row(
            image.full_name,
            _get_status_style(status, info.get("local_only", False)),
            info.get("local_digest") or "-",
            info.get("local_created") or "-",
            str(dockerfile_rel),
            _get_freshness_style(info.get("dockerfile_newer")),
        )


@app.command("list")
@app.command("ls", hidden=True)
def cmd_list():
    """List base images and their status."""
    base_table = _create_image_table("Base Images")
    _add_images_to_table(base_table, BASE_IMAGES)
    console.print(base_table)


@app.command()
def build(
    images: Annotated[Optional[list[str]], typer.Argument(help="Base images to build (default: all)")] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Build without cache")] = False,
    push: Annotated[bool, typer.Option("--push", help="Push after building")] = False,
    keep_going: Annotated[bool, typer.Option("--keep-going", "-k", help="Continue on errors")] = False,
    memory: Annotated[str, typer.Option("--memory", "-m", help="Memory limit for build (e.g., 64g, 128g)")] = "128g",
):
    """Build base images."""
    build_order = get_build_order()

    # Filter to requested images
    if images:
        for img in images:
            if img not in IMAGES:
                console.print(f"[red]Unknown image: {img}[/red]")
                console.print(f"Available: {', '.join(IMAGES.keys())}")
                raise typer.Exit(1)
        build_order = [k for k in build_order if k in images]

    console.print(f"[bold]Building base images:[/bold] {', '.join(build_order)}")

    success = True
    for key in build_order:
        image = IMAGES[key]
        if not build_image(image, no_cache=no_cache, push=push, memory=memory):
            success = False
            if not keep_going:
                break

    if not success:
        raise typer.Exit(1)


@app.command()
def pull(
    images: Annotated[Optional[list[str]], typer.Argument(help="Base images to pull (default: all)")] = None,
):
    """Pull base images from remote registry."""
    if not NAMESPACE:
        console.print("[red]No NAMESPACE configured. Set NAMESPACE in build.py to pull from registry.[/red]")
        raise typer.Exit(1)

    images_to_pull = images if images else list(IMAGES.keys())

    for key in images_to_pull:
        if key not in IMAGES:
            console.print(f"[red]Unknown image: {key}[/red]")
            continue
        pull_image(IMAGES[key])


@app.command()
def push(
    images: Annotated[Optional[list[str]], typer.Argument(help="Base images to push (default: all)")] = None,
):
    """Push base images to remote registry."""
    if not NAMESPACE:
        console.print("[red]No NAMESPACE configured. Set NAMESPACE in build.py to push to registry.[/red]")
        raise typer.Exit(1)

    images_to_push = images if images else list(IMAGES.keys())

    for key in images_to_push:
        if key not in IMAGES:
            console.print(f"[red]Unknown image: {key}[/red]")
            continue
        push_image(IMAGES[key])


@app.command()
def run(
    project_name: Annotated[str, typer.Argument(help="Project name to run")],
    dir: Annotated[
        Optional[str], typer.Option("--dir", "-d", help="Directory to mount at /home/playground/shared")
    ] = None,
    xrdp: Annotated[int, typer.Option("--xrdp", help="Host port for RDP access")] = 3399,
    cmd: Annotated[
        Optional[str], typer.Option("--cmd", "-c", help="Command to run (default: interactive bash)")
    ] = None,
):
    """Run a project's container interactively.

    Starts the project container with optional directory mounting,
    HTTP server, and RDP access.

    Examples:
        p infra run firefox
        p infra run sqlite --dir ./output
        p infra run firefox --xrdp 3999
        p infra run sqlite --cmd "sqlite3 /test.db"
    """
    import os
    import tempfile

    from anypoc.project import Project

    # Validate project exists
    project = Project(project_name)
    if not project.exists():
        console.print(f"[red]Error: Project '{project_name}' not found[/red]")
        console.print(f"[dim]  Expected directory: {project.config_dir}[/dim]")
        raise typer.Exit(1)

    project_image = project.get_image_info()
    project_image_name = project_image.full_name

    # Check if image exists
    result = subprocess.run(
        ["docker", "image", "inspect", project_image_name],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        console.print(f"[red]Error: Project image '{project_image_name}' not found[/red]")
        console.print(f"[dim]  Run: p project build {project_name} first[/dim]")
        raise typer.Exit(1)

    # Validate directory if provided
    dir_path = None
    if dir:
        dir_path = Path(dir).expanduser().resolve()
        if not dir_path.exists():
            console.print(f"[red]Error: Directory does not exist: {dir_path}[/red]")
            raise typer.Exit(1)
        if not dir_path.is_dir():
            console.print(f"[red]Error: Path is not a directory: {dir_path}[/red]")
            raise typer.Exit(1)

    # Print startup info
    console.print(f"\n[cyan bold]Starting {project_name} Container[/cyan bold]\n")
    console.print("[dim]Configuration:[/dim]")
    console.print(f"[dim]  Project: {project_name}[/dim]")
    console.print(f"[dim]  Image: {project_image_name}[/dim]")
    if dir_path:
        console.print(f"[dim]  Shared directory: {dir_path} → /home/playground/shared[/dim]")
        console.print("[dim]  HTTP server: localhost:8080[/dim]")
    console.print(f"[dim]  RDP access: localhost:{xrdp} (playground/playground)[/dim]")

    # Check for authentication files
    from anypoc.utils import CAW_AUTH_DIR as caw_auth_dir

    if caw_auth_dir.exists() and (caw_auth_dir / "manifest.json").exists():
        console.print(f"[dim]  Auth: {caw_auth_dir}/ staging + host credential bind mounts[/dim]")

    console.print()

    # Create startup script
    script_content = f"""#!/bin/bash
# Container startup script

# Start HTTP server in background if directory is mounted
if [ -d /home/playground/shared ]; then
    cd /home/playground/shared
    python3 -m http.server 8080 >/dev/null 2>&1 &
fi

# Print welcome message
echo ''
echo '================================'
echo '{project_name} Environment'
echo '================================'
echo ''
echo 'Project: {project_name}'
"""
    if dir_path:
        script_content += """echo 'Shared directory: /home/playground/shared'
echo 'HTTP server: http://localhost:8080'
"""
    script_content += f"""echo 'RDP access: localhost:{xrdp}'
echo '  Username: playground'
echo '  Password: playground'
echo ''
echo 'Type exit to quit'
echo ''

# Start interactive bash or run command
"""
    if cmd:
        script_content += f"exec {cmd}\n"
    else:
        script_content += "exec /bin/bash\n"

    # Write startup script to temp file
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False)
    temp_file.write(script_content)
    temp_file.close()
    Path(temp_file.name).chmod(0o755)
    startup_script = Path(temp_file.name)

    container_project_dir = f"/home/playground/.anypoc/projects/{project.name}"

    # Build docker command
    docker_cmd = [
        "docker",
        "run",
        "-it",
        "--rm",
        "--user",
        "root",
        "-e",
        f"HOST_UID={os.getuid()}",
        "-e",
        f"HOST_GID={os.getgid()}",
        "-e",
        "ANYPOC_HOME=/home/playground/.anypoc",
    ]

    # Forward matching environment variables into the container
    docker_cmd.extend(get_forwarded_env_args())

    # Mount shared directory if provided
    if dir_path:
        docker_cmd.extend(["-v", f"{dir_path}:/home/playground/shared:rw"])

    # Mount the user-owned project configuration (paths/prompts) read-only.
    docker_cmd.extend(["-v", f"{project.config_dir}:{container_project_dir}:ro"])

    # Bind-mount the host anypoc source so the container picks up live edits;
    # the base image installs deps but not the project itself (see base.Dockerfile).
    docker_cmd.extend(["-v", f"{PROJECT_ROOT / 'src'}:/opt/anypoc/src:ro"])

    # Mount the caw-auth staging dir plus per-credential bind mounts from the host.
    docker_cmd.extend(_caw_auth_docker_args())

    # Map RDP port
    docker_cmd.extend(["-p", f"{xrdp}:3389"])

    # Mount the startup script
    docker_cmd.extend(["-v", f"{startup_script}:/tmp/container_startup.sh:ro"])

    # Set image
    docker_cmd.append(project_image_name)

    # Execute the startup script
    docker_cmd.append("/tmp/container_startup.sh")

    console.print(f"[dim]Command: {' '.join(docker_cmd)}[/dim]\n")
    console.print("[yellow]→[/yellow] Starting container...\n")

    try:
        result = subprocess.run(docker_cmd)
        exit_code = result.returncode
    except KeyboardInterrupt:
        console.print("\n[yellow]→[/yellow] Interrupted by user")
        exit_code = 130
    except Exception as e:
        console.print(f"[red]✗[/red] Error running container: {e}")
        exit_code = 1
    finally:
        # Clean up temporary script
        try:
            startup_script.unlink()
        except Exception:
            pass

    raise typer.Exit(exit_code)


def main():
    """Entry point for standalone execution."""
    app()


if __name__ == "__main__":
    sys.exit(main())
