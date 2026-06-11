#!/usr/bin/env python3
"""
Permission utilities for fixing file ownership after container execution.

Containers often create files as root or different users, which can cause
permission issues on the host. This module provides utilities to fix ownership
and manage sudo credentials.
"""

import atexit
import os
import subprocess
import sys
import threading
from pathlib import Path

from anypoc.utils import logger
from anypoc.utils.platform import is_windows, safe_chown

try:
    import pwd
except ImportError:
    pwd = None  # type: ignore[assignment]

LOG_PREFIX = "[Permissions]"

# Global sudo refresher instance for module-level management
_sudo_refresher: "SudoRefresher | None" = None


def get_real_user() -> tuple[str, int, int]:
    """
    Get the real user when running with sudo.

    Returns:
        tuple: (username, uid, gid)
    """

    if sys.platform == "win32":
        return (os.environ.get("USERNAME", "user"), 1000, 1000)

    sudo_user = os.environ.get("SUDO_USER")

    if sudo_user:
        pw_record = pwd.getpwnam(sudo_user)
        return sudo_user, pw_record.pw_uid, pw_record.pw_gid
    else:
        pw_record = pwd.getpwuid(os.getuid())
        return pw_record.pw_name, os.getuid(), os.getgid()


def is_broken_symlink(path: str) -> bool:
    """Check if a path is a broken symlink."""
    return os.path.islink(path) and not os.path.exists(path)


def fix_permissions_direct(
    paths: list[Path],
    uid: int,
    gid: int,
    verbose: bool = False,
) -> tuple[int, int, int]:
    """
    Fix permissions directly (assumes we have permission to do so).

    Args:
        paths: List of paths to fix
        uid: Target user ID
        gid: Target group ID
        verbose: Whether to log detailed progress

    Returns:
        tuple: (total_fixed, skipped_symlinks, errors)
    """
    total_fixed = 0
    skipped_symlinks = 0
    errors = 0

    for path in paths:
        if not path.exists():
            if verbose:
                logger.warn(f"{LOG_PREFIX} Path does not exist: {path}")
            continue

        if verbose:
            logger.debug(f"{LOG_PREFIX} Processing: {path}")

        try:
            # Fix the root path itself
            safe_chown(path, uid, gid)
            fixed = 1

            # If it's a directory, recursively fix everything inside
            if path.is_dir():
                for root, dirs, files in os.walk(path):
                    # Fix current directory
                    try:
                        safe_chown(root, uid, gid)
                    except Exception:
                        errors += 1

                    # Fix all subdirectories
                    for d in dirs:
                        dir_path = os.path.join(root, d)
                        try:
                            if is_broken_symlink(dir_path):
                                skipped_symlinks += 1
                                continue
                            safe_chown(dir_path, uid, gid)
                            fixed += 1
                        except Exception:
                            errors += 1

                    # Fix all files
                    for f in files:
                        file_path = os.path.join(root, f)
                        try:
                            if is_broken_symlink(file_path):
                                skipped_symlinks += 1
                                continue
                            safe_chown(file_path, uid, gid)
                            fixed += 1
                        except Exception:
                            errors += 1

            total_fixed += fixed

        except PermissionError:
            if verbose:
                logger.warn(f"{LOG_PREFIX} Permission denied for {path}")
            errors += 1
        except Exception as e:
            if verbose:
                logger.warn(f"{LOG_PREFIX} Failed to fix {path}: {e}")
            errors += 1

    return total_fixed, skipped_symlinks, errors


def fix_permissions_with_sudo(
    paths: list[Path],
    verbose: bool = False,
) -> int:
    """
    Fix permissions by invoking a subprocess with sudo.

    Args:
        paths: List of paths to fix
        verbose: Whether to log detailed progress

    Returns:
        Exit code (0 for success)
    """
    if not paths:
        return 0

    # Filter to only existing paths
    existing_paths = [p for p in paths if p.exists()]
    if not existing_paths:
        return 0

    if verbose:
        logger.info(f"{LOG_PREFIX} Requesting sudo to fix permissions...")

    # Re-exec this module under sudo to fix permissions
    cmd = ["sudo", sys.executable, "-m", "anypoc.utils.permissions"] + [str(p) for p in existing_paths]

    try:
        result = subprocess.run(cmd, check=False, capture_output=not verbose)
        return result.returncode
    except KeyboardInterrupt:
        logger.warn(f"{LOG_PREFIX} Cancelled by user")
        return 130
    except Exception as e:
        logger.error(f"{LOG_PREFIX} Failed to run sudo: {e}")
        return 1


def fix_permissions(
    paths: list[Path],
    use_sudo: bool = True,
    verbose: bool = False,
) -> int:
    """
    Fix permissions for the given paths.

    If running as root, fixes directly. Otherwise, uses sudo if allowed.

    Args:
        paths: List of paths to fix ownership for
        use_sudo: Whether to use sudo if not running as root
        verbose: Whether to log detailed progress

    Returns:
        Exit code (0 for success)
    """
    if not paths:
        return 0

    # Filter to only existing paths
    existing_paths = [p for p in paths if p.exists()]
    if not existing_paths:
        return 0

    if is_windows():
        return 0

    is_root = os.getuid() == 0

    if is_root:
        # Already have root - fix directly
        username, uid, gid = get_real_user()
        if verbose:
            logger.info(f"{LOG_PREFIX} Fixing permissions for user: {username} ({uid}:{gid})")

        total_fixed, skipped, errors = fix_permissions_direct(existing_paths, uid, gid, verbose)

        if verbose:
            logger.info(f"{LOG_PREFIX} Fixed {total_fixed} items, skipped {skipped} symlinks, {errors} errors")

        return 1 if errors > 0 else 0
    elif use_sudo:
        # Request sudo
        return fix_permissions_with_sudo(existing_paths, verbose)
    else:
        # Try without sudo (will likely fail for container-created files)
        uid = os.getuid()
        gid = os.getgid()
        total_fixed, skipped, errors = fix_permissions_direct(existing_paths, uid, gid, verbose)
        return 1 if errors > 0 else 0


# =============================================================================
# Sudo Credential Management
# =============================================================================


def sudo_validate() -> bool:
    """
    Validate/refresh sudo credentials.

    Runs `sudo -v` to either prompt for password or refresh existing credentials.

    Returns:
        True if sudo credentials are valid, False otherwise.
    """
    try:
        result = subprocess.run(
            ["sudo", "-v"],
            check=False,
            capture_output=False,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"{LOG_PREFIX} Failed to validate sudo: {e}")
        return False


def sudo_check() -> bool:
    """
    Check if sudo credentials are currently cached (non-interactive).

    Returns:
        True if sudo can be used without password prompt.
    """
    try:
        result = subprocess.run(
            ["sudo", "-n", "true"],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False


class SudoRefresher:
    """
    Keeps sudo credentials fresh by periodically running `sudo -v`.

    Can be used as a context manager or manually started/stopped.

    Usage as context manager:
        with SudoRefresher() as refresher:
            # sudo credentials stay fresh
            run_long_operation()

    Usage manually:
        refresher = SudoRefresher()
        refresher.start()
        try:
            run_long_operation()
        finally:
            refresher.stop()

    Usage with module-level helper:
        ensure_sudo()  # Prompts once and starts background refresh
        # ... run operations ...
        stop_sudo_refresh()  # Stop when done
    """

    def __init__(
        self,
        refresh_interval: int = 240,
        prompt_upfront: bool = True,
        verbose: bool = False,
    ):
        """
        Initialize the sudo refresher.

        Args:
            refresh_interval: Seconds between refresh attempts (default 240 = 4 minutes).
                              Should be less than sudo timeout (typically 5-15 minutes).
            prompt_upfront: Whether to prompt for sudo password immediately on start.
            verbose: Whether to log refresh activity.
        """
        self.refresh_interval = refresh_interval
        self.prompt_upfront = prompt_upfront
        self.verbose = verbose

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False

    def start(self) -> bool:
        """
        Start the sudo refresh background thread.

        Returns:
            True if started successfully (sudo credentials valid), False otherwise.
        """
        if self._started:
            return True

        # Prompt for password upfront if requested
        if self.prompt_upfront:
            if self.verbose:
                logger.info(f"{LOG_PREFIX} Requesting sudo credentials...")
            if not sudo_validate():
                logger.error(f"{LOG_PREFIX} Failed to obtain sudo credentials")
                return False

        # Start background refresh thread
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()
        self._started = True

        if self.verbose:
            logger.info(f"{LOG_PREFIX} Started sudo refresh (interval: {self.refresh_interval}s)")

        return True

    def stop(self) -> None:
        """Stop the sudo refresh background thread."""
        if not self._started:
            return

        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._started = False
        self._thread = None

        if self.verbose:
            logger.info(f"{LOG_PREFIX} Stopped sudo refresh")

    def _refresh_loop(self) -> None:
        """Background thread that periodically refreshes sudo credentials."""
        while not self._stop_event.is_set():
            # Wait for the interval or until stopped
            if self._stop_event.wait(timeout=self.refresh_interval):
                break  # Stop event was set

            # Refresh sudo credentials (non-interactive, will fail silently if expired)
            try:
                subprocess.run(
                    ["sudo", "-v"],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
                if self.verbose:
                    logger.debug(f"{LOG_PREFIX} Refreshed sudo credentials")
            except Exception as e:
                if self.verbose:
                    logger.warn(f"{LOG_PREFIX} Failed to refresh sudo: {e}")

    @property
    def is_running(self) -> bool:
        """Check if the refresher is currently running."""
        return self._started and self._thread is not None and self._thread.is_alive()

    def __enter__(self) -> "SudoRefresher":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()


def ensure_sudo(
    refresh_interval: int = 240,
    verbose: bool = False,
) -> bool:
    """
    Ensure sudo credentials are available and start background refresh.

    This is a module-level helper that manages a global SudoRefresher instance.
    Call `stop_sudo_refresh()` when done, or it will be stopped automatically on exit.

    Args:
        refresh_interval: Seconds between refresh attempts.
        verbose: Whether to log activity.

    Returns:
        True if sudo credentials are valid and refresh started.
    """
    global _sudo_refresher

    # Stop existing refresher if any
    if _sudo_refresher is not None:
        _sudo_refresher.stop()

    # Create and start new refresher
    _sudo_refresher = SudoRefresher(
        refresh_interval=refresh_interval,
        prompt_upfront=True,
        verbose=verbose,
    )

    return _sudo_refresher.start()


def stop_sudo_refresh() -> None:
    """Stop the global sudo refresher if running."""
    global _sudo_refresher

    if _sudo_refresher is not None:
        _sudo_refresher.stop()
        _sudo_refresher = None


# Register cleanup on exit
atexit.register(stop_sudo_refresh)


# =============================================================================
# Permission Fixer
# =============================================================================


class PermissionFixer:
    """
    Context manager and helper for fixing permissions after container operations.

    Usage:
        fixer = PermissionFixer()
        fixer.add_path(output_dir)
        fixer.add_path(knowledge_dir)

        # Run container operation...

        fixer.fix()  # Fixes all registered paths
    """

    def __init__(self, use_sudo: bool = True, verbose: bool = False):
        """
        Initialize the permission fixer.

        Args:
            use_sudo: Whether to use sudo for fixing permissions
            verbose: Whether to log detailed progress
        """
        self.paths: list[Path] = []
        self.use_sudo = use_sudo
        self.verbose = verbose

    def add_path(self, path: Path | str) -> None:
        """Add a path to be fixed."""
        p = Path(path) if isinstance(path, str) else path
        if p not in self.paths:
            self.paths.append(p)

    def add_paths(self, paths: list[Path | str]) -> None:
        """Add multiple paths to be fixed."""
        for p in paths:
            self.add_path(p)

    def fix(self) -> int:
        """
        Fix permissions for all registered paths.

        Returns:
            Exit code (0 for success)
        """
        if not self.paths:
            return 0

        if self.verbose:
            logger.info(f"{LOG_PREFIX} Fixing permissions for {len(self.paths)} path(s)")

        return fix_permissions(self.paths, use_sudo=self.use_sudo, verbose=self.verbose)

    def clear(self) -> None:
        """Clear all registered paths."""
        self.paths = []


# =============================================================================
# CLI entry point (anypoc-perm)
# =============================================================================


def main() -> int:
    """CLI entry point for the `anypoc-perm` command.

    Fixes ownership of the given paths (or the current directory if none given),
    re-execing under sudo if not already root.
    """
    from rich.console import Console

    console = Console()
    console.print("\n[cyan bold]Fix Permissions Tool[/cyan bold]\n")

    if len(sys.argv) > 1:
        paths = [Path(arg).resolve() for arg in sys.argv[1:]]
    else:
        paths = [Path.cwd()]

    console.print("[dim]Paths to fix:[/dim]")
    for p in paths:
        console.print(f"[dim]  - {p}[/dim]")
    console.print()

    if is_windows():
        console.print("[yellow]Note:[/yellow] Permission fixing is not needed on Windows.")
        console.print("Docker Desktop handles volume permissions automatically.")
        return 0

    username, uid, gid = get_real_user()
    is_root = os.getuid() == 0

    if is_root:
        console.print(f"[cyan]->[/cyan] Fixing permissions for user: {username} ({uid}:{gid})\n")

        total_fixed, skipped_symlinks, errors = fix_permissions_direct(paths, uid, gid, verbose=False)

        for path in paths:
            if path.exists():
                console.print(f"[green]v[/green] Processed {path}")

        console.print()
        if skipped_symlinks > 0:
            console.print(f"[dim]Skipped {skipped_symlinks} broken symlink(s)[/dim]")
        if errors > 0:
            console.print(f"[yellow]![/yellow] Fixed {total_fixed} items with {errors} errors")
            return 1
        console.print(f"[green bold]v[/green bold] Successfully fixed {total_fixed} items")
        return 0

    console.print("[yellow]->[/yellow] Requesting sudo privileges to fix permissions...")
    return fix_permissions_with_sudo(paths, verbose=True)


if __name__ == "__main__":
    sys.exit(main())
