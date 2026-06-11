"""POC Web Dashboard."""

import atexit
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import typer

from anypoc.utils import OUTPUT_DIR

app = typer.Typer(
    name="dashboard",
    help="POC web dashboard",
    invoke_without_command=True,
)

DASHBOARD_DIR = Path(__file__).parent / "dashboard"
DEFAULT_LOG_FILE = OUTPUT_DIR / "logs" / "dashboard.log"


def _find_free_port() -> int:
    """Find a free port by binding to port 0 and letting the OS assign one."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


_IS_WINDOWS = sys.platform == "win32"


def _daemonize(log_file: Path, dev_port: int) -> None:
    """Launch dashboard as a detached background process.

    On Unix, forks into the background with std streams redirected to *log_file*.
    On Windows, re-invokes ourselves as a detached subprocess.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    if _IS_WINDOWS:
        cmd = [sys.executable, "-m", "dashboard", "--port", str(dev_port), "--output-dir", str(OUTPUT_DIR)]
        creationflags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        proc = subprocess.Popen(
            cmd,
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            cwd=str(Path(__file__).parent.parent),
        )
        typer.echo("Dashboard started in headless mode.")
        typer.echo(f"  PID:  {proc.pid}")
        typer.echo(f"  Log:  {log_file}")
        typer.echo(f"  URL:  http://localhost:{dev_port}")
        typer.echo(f"  Stop: taskkill /PID {proc.pid} /T")
        raise typer.Exit(0)

    pid = os.fork()
    if pid > 0:
        typer.echo("Dashboard started in headless mode.")
        typer.echo(f"  PID:  {pid}")
        typer.echo(f"  Log:  {log_file}")
        typer.echo(f"  URL:  http://localhost:{dev_port}")
        typer.echo(f"  Stop: kill {pid}")
        raise typer.Exit(0)

    os.setsid()

    header = (
        f"\n=== dashboard started at {datetime.now().isoformat(timespec='seconds')} "
        f"pid={os.getpid()} port={dev_port} ===\n"
    )
    with open(log_file, "ab") as fh:
        fh.write(header.encode())

    devnull_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull_fd, 0)
    os.close(devnull_fd)

    log_fd = os.open(str(log_file), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)


@app.callback(invoke_without_command=True)
def dashboard(
    dev_port: int = typer.Option(8501, "--port", "-p", help="Dev server port"),
    install: bool = typer.Option(False, "--install", "-i", help="Run npm install first"),
    output_dir: str = typer.Option(str(OUTPUT_DIR), "--output-dir", "-o", help="Output directory to watch"),
    headless: bool = typer.Option(
        False,
        "--headless",
        "-H",
        help="Run detached in the background, logging to --log-file.",
    ),
    log_file: Path = typer.Option(
        DEFAULT_LOG_FILE,
        "--log-file",
        "-l",
        help="Log file to write to in headless mode (ignored otherwise).",
    ),
):
    """Launch the POC web dashboard."""
    if not DASHBOARD_DIR.exists():
        typer.echo(f"Dashboard directory not found: {DASHBOARD_DIR}", err=True)
        raise typer.Exit(1)

    # Install deps (if needed) BEFORE forking so npm progress stays on the
    # user's terminal rather than disappearing into the log file.
    node_modules = DASHBOARD_DIR / "node_modules"
    if not node_modules.exists() or install:
        typer.echo("Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=DASHBOARD_DIR, check=True)

    if headless:
        _daemonize(log_file, dev_port)
        # From here on we are the detached child; all output goes to log_file.

    api_port = _find_free_port()

    # Start caw trajectory viewer server
    caw_viewer = None
    caw_viewer_port = None
    try:
        from caw.viewer import start_viewer_server

        caw_viewer = start_viewer_server(host="0.0.0.0")
        caw_viewer_port = caw_viewer.port
        typer.echo(f"Starting CAW trajectory viewer on port {caw_viewer_port}...")
    except Exception as e:
        typer.echo(f"Warning: Could not start CAW viewer: {e}", err=True)

    typer.echo(f"Starting dev server on port {dev_port}...")
    typer.echo(f"Starting API server on port {api_port}...")
    typer.echo(f"Watching output directory: {output_dir}")
    typer.echo(f"\nOpen http://localhost:{dev_port} in your browser\n")

    # API server in background with output dir environment variable.
    # start_new_session=True so we can signal the whole uvicorn tree
    # (reloader + worker) via os.killpg below.
    env = {**os.environ, "POC_OUTPUT_DIR": output_dir}
    _popen_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if _IS_WINDOWS else {"start_new_session": True}
    api_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "dashboard.api:app",
            "--port",
            str(api_port),
            "--reload",
            "--reload-dir",
            str(Path(__file__).parent),
        ],
        cwd=Path(__file__).parent.parent,
        env=env,
        **_popen_kwargs,
    )

    # Vite dev server (pass API port so vite proxy knows where to forward).
    # start_new_session=True is important: `npm run dev` forks grandchildren
    # (sh -> node -> esbuild) that actually own the listening port, and npm
    # does not forward SIGTERM to them. Putting npm in its own session lets
    # cleanup() kill the whole process group and reliably free the port.
    vite_env = {**os.environ, "VITE_API_PORT": str(api_port)}
    if caw_viewer_port is not None:
        vite_env["VITE_CAW_VIEWER_PORT"] = str(caw_viewer_port)
    vite_proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", str(dev_port)],
        cwd=DASHBOARD_DIR,
        env=vite_env,
        **_popen_kwargs,
    )

    def _terminate(proc: subprocess.Popen) -> None:
        """Kill *proc* and all processes in its session/group."""
        if proc.poll() is not None:
            return
        if _IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False, capture_output=True)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()

    def cleanup():
        _terminate(vite_proc)
        _terminate(api_proc)
        if caw_viewer is not None:
            try:
                caw_viewer.stop()
            except Exception:
                pass

    # Ensure cleanup on exit
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: sys.exit(0))

    try:
        vite_proc.wait()
    finally:
        cleanup()


@app.command()
def build():
    """Build the dashboard for production."""
    if not DASHBOARD_DIR.exists():
        typer.echo(f"Dashboard directory not found: {DASHBOARD_DIR}", err=True)
        raise typer.Exit(1)

    node_modules = DASHBOARD_DIR / "node_modules"
    if not node_modules.exists():
        typer.echo("Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=DASHBOARD_DIR, check=True)

    typer.echo("Building dashboard...")
    subprocess.run(["npm", "run", "build"], cwd=DASHBOARD_DIR, check=True)
    typer.echo(f"Built to {DASHBOARD_DIR / 'dist'}")


def main():
    """Entry point for standalone execution."""
    app()
