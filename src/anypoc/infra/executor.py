#!/usr/bin/env python3
"""
Playground Executor - Transparent container execution for CLI tools

Provides a function that allows CLI commands to run either locally or in a container
with a simple --use-playground flag, without changing the implementation code.

The executor handles mapping CLI argument paths from the local machine to container
paths, and validates that all paths exist.

Supports both argparse (playground_executable) and typer (playground_executable_typer).
"""

import inspect
import os
import shlex
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Optional, get_args, get_origin

import typer
from anypoc.utils import PROJECT_ROOT as _DEFAULT_PROJECT_ROOT
from anypoc.utils.platform import get_total_memory_bytes, get_uid_gid
from rich.console import Console

from anypoc.utils import CAW_AUTH_DIR

try:
    from caw.auth import get_docker_flags as _caw_get_docker_flags
    from caw.auth import setup as _caw_auth_setup
except ImportError:
    _caw_get_docker_flags = None
    _caw_auth_setup = None


def _ensure_caw_auth_setup() -> None:
    """Run `caw auth setup` once if the manifest under CAW_AUTH_DIR is missing."""
    if _caw_auth_setup is None:
        return
    if (CAW_AUTH_DIR / "manifest.json").exists():
        return
    console.print(f"[dim]No caw auth manifest at {CAW_AUTH_DIR} — running caw.auth.setup()...[/dim]")
    _caw_auth_setup(agents=["all"], dest_dir=CAW_AUTH_DIR)


def _caw_auth_docker_args() -> list[str]:
    """Return the Docker -v args for caw auth, or [] if no manifest is set up.

    Uses caw.auth.get_docker_flags so the directory mount *and* per-credential
    file mounts are always in sync with the current manifest. Triggers
    `caw.auth.setup()` automatically on first use.
    """
    if _caw_get_docker_flags is None:
        return []
    _ensure_caw_auth_setup()
    try:
        return shlex.split(_caw_get_docker_flags())
    except FileNotFoundError:
        return []


console = Console()

FORWARDED_ENV_PREFIXES = ("CAW_", "CLAUDE_CODE_", "AWS_", "ANTHROPIC_")


def get_forwarded_env_args() -> list[str]:
    """Return docker -e flags for environment variables matching forwarded prefixes."""
    args = []
    for key, value in os.environ.items():
        if key.startswith(FORWARDED_ENV_PREFIXES):
            args.extend(["-e", f"{key}={value}"])
    return args


def resolve_container_command(
    script_path: Path,
    project_root: Optional[str] = None,
    module_name: Optional[str] = None,
) -> list[str]:
    """Resolve how to invoke the current CLI inside an installed container image."""
    script_name = script_path.name
    if not script_name.endswith(".py"):
        return [script_name]

    if module_name and module_name != "__main__":
        return ["python3", "-m", module_name]

    if project_root is not None:
        project_path = Path(project_root).resolve()
        try:
            rel_path = script_path.relative_to(project_path)
        except ValueError:
            rel_path = None

        if rel_path and len(rel_path.parts) >= 2 and rel_path.parts[0] == "src":
            module = ".".join(Path(*rel_path.parts[1:]).with_suffix("").parts)
            return ["python3", "-m", module]

    raise RuntimeError(
        f"Cannot resolve container command for {script_path}. "
        "Use an installed console entry point or a module under src/."
    )


class PathMount:
    """Configuration for a path mount."""

    def __init__(self, arg_name: str, container_path: str, mode: str = "ro"):
        self.arg_name = arg_name
        self.container_path = container_path
        self.mode = mode  # "ro" or "rw"

    def __repr__(self):
        return f"PathMount({self.arg_name}, {self.container_path}, {self.mode})"


class PlaygroundExecutor:
    """Handles re-execution of CLI commands inside containers."""

    def __init__(
        self,
        image: str = "anypoc-base:latest",
        project_root: Optional[str] = None,
        container_workdir: str = "/home/playground",
        path_mounts: Optional[list[PathMount]] = None,
        memory_limit: Optional[str] = None,
    ):
        self.image = image
        if memory_limit is None:
            total_bytes = get_total_memory_bytes()
            memory_limit = f"{total_bytes // 4 // (1 << 30)}g"
        self.memory_limit = memory_limit
        # Default to project root by going up from this file's location (poc/infra/executor.py)
        # This works for both direct execution and editable installs (pip install -e .)
        if project_root is None:
            env_root = os.environ.get("POC_PROJECT_ROOT")
            if env_root:
                project_root = env_root
            else:
                cwd = Path.cwd().resolve()
                looks_like_repo = (cwd / "pyproject.toml").is_file() and (cwd / "src" / "anypoc").is_dir()
                if looks_like_repo:
                    project_root = str(cwd)
                else:
                    project_root = str(_DEFAULT_PROJECT_ROOT)
        self.project_root = project_root
        self.container_workdir = container_workdir
        self.path_mounts = path_mounts or []

    def validate_and_extract_paths(self, parsed_args) -> dict[str, str]:
        """
        Extract and validate paths from parsed arguments based on configured mounts.
        Returns a mapping of {arg_name: local_path} or exits on error.
        """
        path_values = {}

        for mount in self.path_mounts:
            # Get the value from parsed args
            if not hasattr(parsed_args, mount.arg_name):
                console.print(f"[yellow]⚠ Warning:[/yellow] Argument '{mount.arg_name}' not found in parsed args")
                continue

            local_path = getattr(parsed_args, mount.arg_name)
            if local_path is None:
                console.print(f"[yellow]⚠ Warning:[/yellow] Argument '{mount.arg_name}' is None")
                continue

            local_path_obj = Path(local_path).expanduser().resolve()

            # Validate path exists
            if not local_path_obj.exists():
                console.print(f"[red]✗ Error:[/red] Path does not exist: {local_path_obj}")
                console.print(f"[dim]  Argument: --{mount.arg_name.replace('_', '-')}[/dim]")
                sys.exit(1)

            # Note: Removed directory-only validation to support both files and directories
            path_values[mount.arg_name] = str(local_path_obj)

        return path_values

    def translate_args_for_container(self, parsed_args, path_values: dict[str, str]) -> list[str]:
        """
        Build new command-line arguments with container paths substituted.
        """
        new_args = []

        # Iterate through all attributes in parsed_args
        for arg_name in vars(parsed_args):
            arg_value = getattr(parsed_args, arg_name)

            # Skip decorator-managed flags (will be added separately)
            if arg_name in ["use_playground", "in_container"]:
                continue

            # Check if this is a path that needs translation
            if arg_name in path_values:
                # Find the corresponding mount
                for mount in self.path_mounts:
                    if mount.arg_name == arg_name:
                        arg_flag = f"--{arg_name.replace('_', '-')}"
                        new_args.extend([arg_flag, mount.container_path])
                        break
            else:
                # Pass through other arguments as-is
                arg_flag = f"--{arg_name.replace('_', '-')}"
                if isinstance(arg_value, bool):
                    if arg_value:
                        new_args.append(arg_flag)
                elif arg_value is not None:
                    new_args.extend([arg_flag, str(arg_value)])

        # Add flag to indicate we're in container
        new_args.append("--in-container")

        return new_args

    def build_docker_command(
        self,
        cli_command: list[str],
        path_values: dict[str, str],
    ) -> list[str]:
        """
        Build the docker run command with appropriate volume mounts.
        """
        docker_cmd = [
            "docker",
            "run",
            "--rm",  # Remove container after exit
            "-i",  # Interactive
            "--user",
            "root",  # Run as root so entrypoint can remap the runtime user first
            "-e",
            f"HOST_UID={get_uid_gid()[0]}",
            "-e",
            f"HOST_GID={get_uid_gid()[1]}",
        ]

        # Apply memory limit if configured
        if self.memory_limit:
            docker_cmd.extend(["--memory", self.memory_limit])

        # Forward matching environment variables into the container
        docker_cmd.extend(get_forwarded_env_args())

        # Mount ~/.caw/auth/ plus per-credential bind mounts from the host.
        # `caw auth` no longer symlinks originals — credentials live at their
        # real host paths and are bind-mounted into /tmp/caw_auth.
        docker_cmd.extend(_caw_auth_docker_args())

        # Bind-mount the host anypoc source into the container read-only so
        # in-container `python -m anypoc...` and the `anypoc` CLI shim resolve
        # the live source tree. The base image installs deps but not the
        # project itself; a .pth file in the venv adds /opt/anypoc/src to
        # sys.path, so this mount is what makes `import anypoc` work.
        docker_cmd.extend(["-v", f"{_DEFAULT_PROJECT_ROOT / 'src'}:/opt/anypoc/src:ro"])

        # Mount configured paths
        for mount in self.path_mounts:
            if mount.arg_name in path_values:
                local_path = path_values[mount.arg_name]
                docker_cmd.extend(["-v", f"{local_path}:{mount.container_path}:{mount.mode}"])

        # Set working directory
        docker_cmd.extend(["-w", self.container_workdir])

        # Set image
        docker_cmd.append(self.image)

        # Add the CLI command to execute
        docker_cmd.extend(cli_command)

        return docker_cmd

    def execute_in_container(self, original_command: list[str], parsed_args) -> int:
        """
        Re-execute the CLI command inside a container.

        Args:
            original_command: The base command to run (e.g., ["python3", "script.py"] or ["poc-gen"])
            parsed_args: Already-parsed command line arguments

        Returns the exit code.
        """
        console.print("[cyan]→[/cyan] Running in playground container...\n")

        # Check for authentication files
        auth_mounted = CAW_AUTH_DIR.exists() and (CAW_AUTH_DIR / "manifest.json").exists()
        if auth_mounted:
            console.print(f"[green]✓[/green] {CAW_AUTH_DIR}/ detected — credentials bind-mounted from host")

        # Validate and extract configured paths from parsed args
        path_values = self.validate_and_extract_paths(parsed_args)

        if path_values:
            console.print("[dim]Path mappings:[/dim]")
            for mount in self.path_mounts:
                if mount.arg_name in path_values:
                    local_path = path_values[mount.arg_name]
                    console.print(
                        f"[dim]  --{mount.arg_name.replace('_', '-')}: {local_path} → "
                        f"{mount.container_path} ({mount.mode})[/dim]"
                    )
            console.print()
        elif auth_mounted:
            console.print()

        # Build arguments for container execution
        container_args = self.translate_args_for_container(parsed_args, path_values)

        # Combine command with translated arguments
        full_command = original_command + container_args

        # Build complete docker command
        docker_cmd = self.build_docker_command(full_command, path_values)

        console.print(f"[dim]Container command: {' '.join(docker_cmd)}[/dim]\n")
        console.print("[yellow]→[/yellow] Starting container execution...\n")

        # Execute in container
        try:
            result = subprocess.run(docker_cmd, check=False)

            if result.returncode == 0:
                console.print("\n[green bold]✓ Container execution completed successfully[/green bold]")
            else:
                console.print(f"\n[yellow]⚠ Container execution exited with code {result.returncode}[/yellow]")

            return result.returncode

        except KeyboardInterrupt:
            console.print("\n\n[yellow]→[/yellow] Interrupted by user")
            return 130
        except Exception as e:
            console.print(f"\n[red bold]✗ Error running container:[/red bold] {e}")
            return 1


def playground_executable(
    main: Callable,
    image: str = "anypoc-base:latest",
    project_root: Optional[str] = None,
    mount: Optional[list[tuple[str, str, str]]] = None,
    get_arg_parser: Optional[Callable] = None,
    pre_process: Optional[Callable] = None,
    post_process: Optional[Callable] = None,
    container_only: bool = False,
):
    """
    Execute a CLI function either locally or in a playground container.

    When --use-playground flag is detected in sys.argv, the entire CLI command
    is re-executed inside a container instead of running locally.

    Args:
        main: The main function to execute. Receives parsed_args as its first parameter.
        image: Docker image name
        project_root: Path to project root directory (default: auto-detected from this file's location)
        mount: List of path mount configurations as tuples of (arg_name, container_path, mode)
               where mode is "ro" (read-only) or "rw" (read-write)
        get_arg_parser: Function that returns an argparse.ArgumentParser (before parsing).
                       The function will automatically add --use-playground and --in-container
                       flags (unless container_only=True, which skips --use-playground).
        pre_process: Optional callback function that runs on the local machine before container
                    starts. Receives parsed_args as parameter. Useful for setup like creating directories.
        post_process: Optional callback function that runs on the local machine after container
                     execution completes successfully. Receives parsed_args as parameter.
        container_only: If True, the function will ALWAYS run in a container (no --use-playground flag needed).
                       Useful for scripts that depend on container-specific resources.

    Usage:
        def get_arg_parser():
            parser = argparse.ArgumentParser()
            parser.add_argument("--input", type=str, default="test_input")
            parser.add_argument("--output", type=str, default="test_output")
            # NOTE: Don't add --use-playground or --in-container
            # These flags are added automatically
            return parser

        def setup_dirs(args):
            # This runs on local machine before container starts
            Path(args.input).mkdir(exist_ok=True)
            Path(args.output).mkdir(exist_ok=True)
            return 0

        def verify_output(args):
            # This runs on local machine after container finishes
            output_dir = Path(args.output)
            print(f"Verifying output in {output_dir}")
            return 0

        def main(args):
            # Receives parsed args
            # Your implementation here
            # This runs either locally or in container transparently
            input_dir = Path(args.input)
            output_dir = Path(args.output)
            pass

        if __name__ == "__main__":
            playground_executable(
                main=main,
                image="anypoc-base:latest",
                mount=[
                    ("input", "/home/playground/input", "rw"),
                    ("output", "/home/playground/output", "rw"),
                ],
                get_arg_parser=get_arg_parser,
                pre_process=setup_dirs,
                post_process=verify_output
            )

    Example CLI:
        # Local execution
        $ python script.py

        # Container execution (handles pre/post process automatically)
        $ python script.py --use-playground

        The --input directory will be mounted at /home/playground/input
        The --output directory will be mounted at /home/playground/output
        Pre-process runs on host before container, post-process runs on host after

    Container-only mode:
        if __name__ == "__main__":
            playground_executable(
                main=main,
                image="poc-firefox:latest",
                mount=[("output", "/home/playground/output", "rw")],
                get_arg_parser=get_arg_parser,
                container_only=True  # Always runs in container, no --use-playground flag needed
            )

        # Usage: Just run directly, no --use-playground needed
        $ python run.py
    """
    # Get parser and add our flags
    if get_arg_parser is not None:
        parser = get_arg_parser()
        # Add managed flags (skip --use-playground if container_only)
        if not container_only:
            parser.add_argument(
                "--use-playground", action="store_true", help="Run in playground container instead of locally"
            )
        parser.add_argument(
            "--in-container", action="store_true", help="Indicates execution is inside container (used internally)"
        )
        parsed_args = parser.parse_args()
    else:
        parsed_args = None

    # Check if we're already in container
    in_container = parsed_args and getattr(parsed_args, "in_container", False)

    # Check if --use-playground flag is present or container_only is set
    if container_only and not in_container:
        use_playground = True
    elif not container_only:
        use_playground = parsed_args and parsed_args.use_playground
    else:
        # Already in container, don't re-execute
        use_playground = False

    # Run pre_process (only on host, not in container)
    if pre_process is not None and parsed_args is not None and not in_container:
        try:
            pre_result = pre_process(parsed_args)
            if pre_result is not None and pre_result != 0:
                console.print(f"[red]✗ Pre-process failed with code {pre_result}[/red]")
                sys.exit(pre_result)
        except Exception as e:
            console.print(f"[red]✗ Error in pre-process:[/red] {e}")
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            sys.exit(1)

    # Execute main function (either in container or locally)
    if use_playground:
        # Convert mount tuples to PathMount objects
        path_mounts = []
        if mount:
            for arg_name, container_path, mode in mount:
                path_mounts.append(PathMount(arg_name, container_path, mode))

        # Create executor and run in container
        executor = PlaygroundExecutor(
            image=image,
            project_root=project_root,
            path_mounts=path_mounts,
        )

        try:
            original_command = resolve_container_command(
                script_path=Path(sys.argv[0]).resolve(),
                project_root=executor.project_root,
                module_name=getattr(main, "__module__", None),
            )
        except RuntimeError as exc:
            console.print(f"[red]✗ Error:[/red] {exc}")
            sys.exit(1)

        exit_code = executor.execute_in_container(original_command, parsed_args)
    else:
        # Normal local execution - pass parsed_args to main function
        exit_code = main(parsed_args)
        exit_code = exit_code if exit_code is not None else 0

    # Run post_process (only on host, not in container)
    if post_process is not None and parsed_args is not None and exit_code == 0 and not in_container:
        try:
            post_result = post_process(parsed_args)
            if post_result is not None and post_result != 0:
                console.print(f"[yellow]⚠ Post-process exited with code {post_result}[/yellow]")
                sys.exit(post_result)
        except Exception as e:
            console.print(f"[red]✗ Error in post-process:[/red] {e}")
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            sys.exit(1)

    # Exit with the code
    sys.exit(exit_code)


@dataclass
class _TyperParsedArgs:
    """Namespace-like object to hold parsed typer arguments."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _extract_option_name(param_name: str, annotation) -> str:
    """Extract the CLI option name from a typer annotation."""
    # Default to --param-name format
    cli_name = param_name.replace("_", "-")

    # Check if annotation has custom names in typer.Option
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        for arg in args[1:]:
            if isinstance(arg, typer.models.OptionInfo):
                # Check if custom param_decls were provided
                if arg.param_decls:
                    # Use the first long option (starts with --)
                    for decl in arg.param_decls:
                        if decl.startswith("--"):
                            cli_name = decl[2:]
                            break
                break

    return cli_name


def _build_typer_cli_args(parsed_args: _TyperParsedArgs, path_mounts: list[PathMount]) -> list[str]:
    """Build CLI arguments for container execution from parsed typer args."""
    new_args = []
    path_mount_names = {m.arg_name for m in path_mounts}

    for arg_name, arg_value in vars(parsed_args).items():
        # Skip internal flags
        if arg_name in ["use_playground", "in_container"]:
            continue

        cli_flag = f"--{arg_name.replace('_', '-')}"

        # Check if this is a path that needs translation
        if arg_name in path_mount_names:
            for mount in path_mounts:
                if mount.arg_name == arg_name:
                    new_args.extend([cli_flag, mount.container_path])
                    break
        else:
            # Pass through other arguments as-is
            if isinstance(arg_value, bool):
                if arg_value:
                    new_args.append(cli_flag)
            elif arg_value is not None:
                new_args.extend([cli_flag, str(arg_value)])

    # Add flag to indicate we're in container
    new_args.append("--in-container")

    return new_args


def playground_executable_typer(
    main: Callable,
    image: str = "anypoc-base:latest",
    project_root: Optional[str] = None,
    mount: Optional[list[tuple[str, str, str]]] = None,
    pre_process: Optional[Callable] = None,
    post_process: Optional[Callable] = None,
    container_only: bool = False,
):
    """
    Execute a typer-based CLI function either locally or in a playground container.

    This is the typer equivalent of playground_executable(). Instead of providing
    a get_arg_parser function, you provide a typer-style function with type annotations.

    When --use-playground flag is passed, the entire CLI command is re-executed
    inside a container instead of running locally.

    Args:
        main: The main function to execute. Should be a typer-style function with
              type-annotated parameters using typer.Option/typer.Argument.
        image: Docker image name
        project_root: Path to project root directory (default: auto-detected)
        mount: List of path mount configurations as tuples of (arg_name, container_path, mode)
               where mode is "ro" (read-only) or "rw" (read-write)
        pre_process: Optional callback that runs on host before container starts.
                    Receives a namespace-like object with all parsed args.
        post_process: Optional callback that runs on host after container completes.
                     Receives a namespace-like object with all parsed args.
        container_only: If True, always run in container (no --use-playground needed)

    Usage:
        from typing import Annotated
        import typer
        from anypoc.infra.executor import playground_executable_typer

        def main(
            input: Annotated[str, typer.Option(help="Input directory")],
            output: Annotated[str, typer.Option(help="Output directory")],
            verbose: Annotated[bool, typer.Option(help="Verbose output")] = False,
        ):
            # Your implementation here
            print(f"Processing {input} -> {output}")

        if __name__ == "__main__":
            playground_executable_typer(
                main=main,
                image="anypoc-base:latest",
                mount=[
                    ("input", "/home/playground/input", "ro"),
                    ("output", "/home/playground/output", "rw"),
                ],
            )

    Example CLI:
        # Local execution
        $ python script.py --input ./data --output ./results

        # Container execution
        $ python script.py --input ./data --output ./results --use-playground

    Container-only mode:
        playground_executable_typer(
            main=main,
            container_only=True  # Always runs in container
        )

        # Usage: runs in container automatically
        $ python script.py --input ./data --output ./results
    """
    # Convert mount tuples to PathMount objects
    path_mounts = []
    if mount:
        for arg_name, container_path, mode in mount:
            path_mounts.append(PathMount(arg_name, container_path, mode))

    # Determine project root
    if project_root is None:
        project_root = str(_DEFAULT_PROJECT_ROOT)

    # Create a typer app that wraps the main function
    app = typer.Typer(add_completion=False)

    # Get the signature of the main function to understand its parameters
    sig = inspect.signature(main)

    def wrapped_main(
        use_playground: Annotated[
            bool,
            typer.Option(
                "--use-playground",
                help="Run in playground container instead of locally",
                is_flag=True,
                hidden=container_only,  # Hide if container_only (not used)
            ),
        ] = False,
        in_container: Annotated[
            bool,
            typer.Option(
                "--in-container",
                help="Internal flag indicating execution inside container",
                is_flag=True,
                hidden=True,
            ),
        ] = False,
        **kwargs: Any,
    ):
        # Build a namespace-like object with all parsed args
        all_args = {"use_playground": use_playground, "in_container": in_container, **kwargs}
        parsed_args = _TyperParsedArgs(**all_args)

        # Determine if we should run in container
        should_use_playground = (container_only and not in_container) or (
            not container_only and use_playground and not in_container
        )

        # Run pre_process on host before container starts
        if pre_process is not None and not in_container:
            try:
                pre_result = pre_process(parsed_args)
                if pre_result is not None and pre_result != 0:
                    console.print(f"[red]✗ Pre-process failed with code {pre_result}[/red]")
                    raise typer.Exit(pre_result)
            except typer.Exit:
                raise
            except Exception as e:
                console.print(f"[red]✗ Error in pre-process:[/red] {e}")
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
                raise typer.Exit(1)

        if should_use_playground:
            # Execute in container
            executor = PlaygroundExecutor(
                image=image,
                project_root=project_root,
                path_mounts=path_mounts,
            )

            # Validate paths
            path_values = executor.validate_and_extract_paths(parsed_args)

            # Build container CLI args
            container_args = _build_typer_cli_args(parsed_args, path_mounts)

            try:
                original_command = resolve_container_command(
                    script_path=Path(sys.argv[0]).resolve(),
                    project_root=project_root,
                    module_name=getattr(main, "__module__", None),
                )
            except RuntimeError as exc:
                console.print(f"[red]✗ Error:[/red] {exc}")
                raise typer.Exit(1)

            # Build docker command
            docker_cmd = executor.build_docker_command(
                original_command + container_args,
                path_values,
            )

            console.print("[cyan]→[/cyan] Running in playground container...\n")

            # Show auth info
            auth_detected = CAW_AUTH_DIR.exists() and (CAW_AUTH_DIR / "manifest.json").exists()
            if auth_detected:
                console.print(f"[green]✓[/green] {CAW_AUTH_DIR}/ detected — credentials bind-mounted from host")

            if path_values:
                console.print("[dim]Path mappings:[/dim]")
                for pm in path_mounts:
                    if pm.arg_name in path_values:
                        local_path = path_values[pm.arg_name]
                        console.print(
                            f"[dim]  --{pm.arg_name.replace('_', '-')}: {local_path} → "
                            f"{pm.container_path} ({pm.mode})[/dim]"
                        )
                console.print()
            elif auth_detected:
                console.print()

            console.print(f"[dim]Container command: {' '.join(docker_cmd)}[/dim]\n")
            console.print("[yellow]→[/yellow] Starting container execution...\n")

            try:
                result = subprocess.run(docker_cmd, check=False)
                exit_code = result.returncode

                if exit_code == 0:
                    console.print("\n[green bold]✓ Container execution completed successfully[/green bold]")
                else:
                    console.print(f"\n[yellow]⚠ Container execution exited with code {exit_code}[/yellow]")

            except KeyboardInterrupt:
                console.print("\n\n[yellow]→[/yellow] Interrupted by user")
                exit_code = 130
            except Exception as e:
                console.print(f"\n[red bold]✗ Error running container:[/red bold] {e}")
                exit_code = 1

        else:
            # Run locally - call the original main function with kwargs
            result = main(**kwargs)
            exit_code = result if result is not None else 0

        # Run post_process on host after completion
        if post_process is not None and exit_code == 0 and not in_container:
            try:
                post_result = post_process(parsed_args)
                if post_result is not None and post_result != 0:
                    console.print(f"[yellow]⚠ Post-process exited with code {post_result}[/yellow]")
                    raise typer.Exit(post_result)
            except typer.Exit:
                raise
            except Exception as e:
                console.print(f"[red]✗ Error in post-process:[/red] {e}")
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
                raise typer.Exit(1)

        raise typer.Exit(exit_code)

    # Build the wrapped function with the same signature as main, plus our extra params
    # We need to dynamically create parameters for typer
    params = list(sig.parameters.values())

    # Add our internal parameters
    use_playground_param = inspect.Parameter(
        "use_playground",
        inspect.Parameter.KEYWORD_ONLY,
        default=False,
        annotation=Annotated[
            bool,
            typer.Option(
                "--use-playground",
                help="Run in playground container instead of locally",
                is_flag=True,
                hidden=container_only,
            ),
        ],
    )
    in_container_param = inspect.Parameter(
        "in_container",
        inspect.Parameter.KEYWORD_ONLY,
        default=False,
        annotation=Annotated[
            bool,
            typer.Option(
                "--in-container",
                help="Internal flag indicating execution inside container",
                is_flag=True,
                hidden=True,
            ),
        ],
    )

    # Create new signature with all parameters
    new_params = params + [use_playground_param, in_container_param]

    # Create the actual command function with the correct signature
    def make_command():
        # Use exec to create a function with the exact signature we need
        param_names = [p.name for p in new_params]
        param_str = ", ".join(param_names)
        func_code = f"def _cmd({param_str}): return _impl({param_str})"

        local_ns: dict[str, Any] = {"_impl": wrapped_main}
        exec(func_code, local_ns)  # noqa: S102
        cmd_func = local_ns["_cmd"]

        # Copy annotations from the signature
        cmd_func.__annotations__ = {p.name: p.annotation for p in new_params if p.annotation != inspect.Parameter.empty}

        # Copy defaults
        cmd_func.__defaults__ = tuple(p.default for p in new_params if p.default != inspect.Parameter.empty)

        return cmd_func

    cmd = make_command()
    cmd.__doc__ = main.__doc__

    # Register with typer
    app.command()(cmd)

    # Run the app
    app()
