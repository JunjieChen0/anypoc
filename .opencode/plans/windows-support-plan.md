# AnyPoC Windows Support — Implementation Plan

**Status**: Plan complete, ready for execution  
**Estimated effort**: 4–5 hours  
**Target**: Docker Desktop for Windows, scan + poc + dashboard (foreground first)

---

## 0. Architecture Overview

AnyPoC runs in two layers:

1. **Host (Windows)** — CLI entrypoint, project management, Docker orchestration, dashboard web server
2. **Container (Linux)** — LLM agents (`caw` → Claude Code / Codex), build/test environments

The host side needs Windows compatibility. The container side is already Linux and does **not** need changes.

---

## 1. Dependency Update

**File**: `pyproject.toml`

Add `portalocker` (cross-platform file locking) to `[project.dependencies]`:

```toml
dependencies = [
    "coding-agent-wrapper>=0.1.1",
    "portalocker>=2.0",      # NEW: replaces fcntl on Windows
    "rich",
    "pyyaml",
    "pydantic>=2.0",
    "fastapi>=0.115.0",
    "typer>=0.21.0",
    "markdown>=3.5.0",
    "pygments>=2.17.0",
]
```

**Verification**:
```bash
pip install -e .
python -c "import portalocker; print(portalocker.__version__)"
```

---

## 2. Monkey-patch `caw` for Windows

**File**: `src/anypoc/utils/windows_compat.py` (NEW)

Create a new module that patches `caw.storage.JsonlWriter` before any other code imports it.

```python
"""Windows compatibility patches for external dependencies.

This module must be imported *before* any code that uses `caw`.
It is imported automatically from `anypoc.__init__`.
"""

from __future__ import annotations

import json
import sys


def _patch_caw_storage() -> None:
    """Replace fcntl-based file locking with portalocker on Windows."""
    if sys.platform != "win32":
        return

    try:
        import portalocker
    except ImportError:
        # portalocker is an optional dependency on non-Windows;
        # on Windows it is required and the import will be enforced by pyproject.toml
        return

    # Patch JsonlWriter.append to use portalocker instead of fcntl
    import caw.storage

    _original_append = caw.storage.JsonlWriter.append

    def _windows_append(self, entry: dict) -> None:
        if self._subagent:
            entry = {**entry, "subagent": self._subagent}
        with open(self._path, "a", encoding="utf-8") as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            f.write(json.dumps(entry) + "\n")

    caw.storage.JsonlWriter.append = _windows_append


_patch_caw_storage()
```

**File**: `src/anypoc/__init__.py` (MODIFY)

Add at the top of the file (before any other imports):

```python
"""AnyPoC — AI-powered bug detection and PoC generation."""

# Windows compatibility: patch caw before anything else imports it
from anypoc.utils import windows_compat  # noqa: F401

# ... rest of existing imports ...
```

**Verification**:
```bash
python -c "import anypoc; import caw; print('caw patched OK')"
# Should NOT raise ModuleNotFoundError: No module named 'fcntl'
```

---

## 3. Cross-Platform Utilities

**File**: `src/anypoc/utils/platform.py` (NEW)

```python
"""Cross-platform utilities for AnyPoC.

Wraps Unix-only operations so the host-side Python code can run on Windows
against Docker Desktop.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple


def is_windows() -> bool:
    """Return True when running on Windows (native or WSL1)."""
    return sys.platform == "win32"


def get_uid_gid() -> Tuple[int, int]:
    """Return (uid, gid) for the current user.

    On Windows we return (1000, 1000) because the playground user inside the
    Docker image is created with those IDs.  Docker Desktop handles volume
    ownership automatically, so the exact values do not matter for bind-mounts.
    """
    if is_windows():
        return (1000, 1000)
    import os
    return (os.getuid(), os.getgid())


def get_total_memory_bytes() -> int:
    """Return total physical memory in bytes.

    Used by PlaygroundExecutor to pick a default Docker memory limit.
    """
    if is_windows():
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        kernel32 = ctypes.windll.kernel32
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            # Fallback: assume 8 GiB
            return 8 * (1 << 30)
        return stat.ullTotalPhys

    import os
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def safe_chown(path: Path | str, uid: int, gid: int) -> None:
    """Change file ownership.  No-op on Windows.

    Docker Desktop for Windows manages volume permissions automatically,
    so manual chown is unnecessary and would raise AttributeError.
    """
    if is_windows():
        return
    import os
    os.chown(path, uid, gid)


def is_root() -> bool:
    """Return True if the current process is running as root/admin.

    On Windows we always return False because there is no Unix-style root
    concept and containers run under the current user token.
    """
    if is_windows():
        return False
    import os
    return os.getuid() == 0


def chmod_executable(path: Path | str) -> None:
    """Make a file executable (chmod +x).  No-op on Windows.

    Windows does not use Unix permission bits; the file extension or ACLs
    determine executability.  In our Docker use-case the file is consumed
    inside a Linux container where it will be run via /bin/bash, so the
    executable bit is not strictly required.
    """
    if is_windows():
        return
    import os
    os.chmod(path, 0o755)


def get_username() -> str:
    """Return the current user name."""
    if is_windows():
        import os
        return os.environ.get("USERNAME", "user")
    import os
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def getpwuid(uid: int) -> Tuple[str, int, int]:
    """Return (name, uid, gid) for the given uid."""
    if is_windows():
        return ("user", uid, 1000)
    import pwd
    pw = pwd.getpwuid(uid)
    return (pw.pw_name, pw.pw_uid, pw.pw_gid)


def getpwnam(name: str) -> Tuple[str, int, int]:
    """Return (name, uid, gid) for the given user name."""
    if is_windows():
        return (name, 1000, 1000)
    import pwd
    pw = pwd.getpwnam(name)
    return (pw.pw_name, pw.pw_uid, pw.pw_gid)
```

**Verification**:
```bash
python -c "from anypoc.utils.platform import *; print(get_uid_gid()); print(get_total_memory_bytes())"
```

---

## 4. Docker Image Build (`infra/build.py`)

**File**: `src/anypoc/infra/build.py`

### 4a. Replace UID/GID calls

Lines 155–156:
```python
# BEFORE
build_args["PLAYGROUND_UID"] = str(os.getuid())
build_args["PLAYGROUND_GID"] = str(os.getgid())

# AFTER
from anypoc.utils.platform import get_uid_gid
uid, gid = get_uid_gid()
build_args["PLAYGROUND_UID"] = str(uid)
build_args["PLAYGROUND_GID"] = str(gid)
```

Lines 739–742 (inside `run` command):
```python
# BEFORE
        f"HOST_UID={os.getuid()}",
        f"HOST_GID={os.getgid()}",

# AFTER
        f"HOST_UID={get_uid_gid()[0]}",
        f"HOST_GID={get_uid_gid()[1]}",
```

### 4b. Replace chmod

Line 726:
```python
# BEFORE
    Path(temp_file.name).chmod(0o755)

# AFTER
    from anypoc.utils.platform import chmod_executable
    chmod_executable(temp_file.name)
```

**Verification**:
```bash
python -c "from anypoc.infra.build import get_env_build_args; print(get_env_build_args())"
# Should output {'PLAYGROUND_UID': '1000', 'PLAYGROUND_GID': '1000', ...}
```

---

## 5. Container Executor (`infra/executor.py`)

**File**: `src/anypoc/infra/executor.py`

### 5a. Replace memory detection

Lines 132–134:
```python
# BEFORE
        total_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")

# AFTER
        from anypoc.utils.platform import get_total_memory_bytes
        total_bytes = get_total_memory_bytes()
```

### 5b. Replace UID/GID in Docker command

Lines 236–238:
```python
# BEFORE
            f"HOST_UID={os.getuid()}",
            f"HOST_GID={os.getgid()}",

# AFTER
            from anypoc.utils.platform import get_uid_gid
            uid, gid = get_uid_gid()
            docker_cmd.extend([
                "-e", f"HOST_UID={uid}",
                "-e", f"HOST_GID={gid}",
            ])
```

**Verification**:
```bash
python -c "from anypoc.infra.executor import PlaygroundExecutor; e = PlaygroundExecutor(); print(e.memory_limit)"
# Should print a reasonable memory limit like '16g'
```

---

## 6. Permission Utilities (`utils/permissions.py`)

**File**: `src/anypoc/utils/permissions.py`

### 6a. Conditional `pwd` import

Line 12:
```python
# BEFORE
import pwd

# AFTER
try:
    import pwd
except ImportError:
    pwd = None  # type: ignore
```

### 6b. Replace all `os.getuid()` / `os.getgid()` / `os.chown()` / root checks

Replace throughout the file:
- `os.getuid()` → use `platform.get_uid_gid()[0]` or `platform.is_root()`
- `os.getgid()` → use `platform.get_uid_gid()[1]`
- `os.chown()` → use `platform.safe_chown()`
- `pwd.getpwuid(...)` → use `platform.getpwuid(...)`
- `pwd.getpwnam(...)` → use `platform.getpwnam(...)`

Key locations:
- Lines 43–44 (`get_real_user`)
- Lines 85, 93, 104, 116 (`fix_permissions_direct`)
- Lines 200, 219–220 (`fix_permissions`)
- Lines 532 (`main`)

### 6c. Sudo no-op on Windows

In `fix_permissions_with_sudo` and `sudo_validate` / `sudo_check`:

```python
# At the top of each function:
from anypoc.utils.platform import is_windows
if is_windows():
    return 0  # or False for boolean functions
```

### 6d. `anypoc-perm` CLI message

In `main()`:
```python
# Add at the start:
from anypoc.utils.platform import is_windows
if is_windows():
    console.print("[yellow]Note:[/yellow] Permission fixing is not needed on Windows. Docker Desktop handles volume permissions automatically.")
    return 0
```

**Verification**:
```bash
anypoc-perm
# On Windows: should print the note and exit 0
```

---

## 7. Dashboard (`dashboard/__init__.py`)

**File**: `src/dashboard/__init__.py`

### 7a. Fork-based daemonize → Windows subprocess

Replace `_daemonize()`:

```python
# BEFORE (Unix fork-based)
def _daemonize(log_file: Path, dev_port: int) -> None:
    pid = os.fork()
    if pid > 0:
        # Parent exits...
    os.setsid()
    # ... dup2 redirects ...

# AFTER (Windows-compatible)
def _daemonize(log_file: Path, dev_port: int) -> None:
    """Launch dashboard as a detached subprocess on Windows."""
    import subprocess
    import sys

    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Build the command: re-invoke ourselves without --headless
    cmd = [
        sys.executable, "-m", "dashboard",
        "--port", str(dev_port),
        "--output-dir", str(OUTPUT_DIR),
    ]

    # Windows: CREATE_NEW_CONSOLE creates a new console window,
    # CREATE_NEW_PROCESS_GROUP lets us signal the process tree
    creationflags = (
        subprocess.CREATE_NEW_CONSOLE
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
    )

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
    typer.echo(f"  Stop: taskkill /PID {proc.pid}")
    raise typer.Exit(0)
```

### 7b. Process termination (killpg → taskkill / terminate)

Replace `_terminate()`:

```python
# BEFORE
def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    # ... SIGKILL fallback ...

# AFTER
def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    import sys
    if sys.platform == "win32":
        import subprocess as sp
        # Windows: taskkill /T kills the whole process tree
        sp.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False, capture_output=True)
        try:
            proc.wait(timeout=3)
        except sp.TimeoutExpired:
            proc.kill()
            proc.wait()
    else:
        # Unix: keep existing killpg logic
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
```

### 7c. Signal handling

Lines 196–197:
```python
# BEFORE
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

# AFTER
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: sys.exit(0))
```

### 7d. `start_new_session` → `creationflags`

For both `api_proc` and `vite_proc`:

```python
# BEFORE
    start_new_session=True,

# AFTER (conditional)
    **({"start_new_session": True} if sys.platform != "win32" else {}),
    **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {}),
```

Or use a helper:

```python
import sys
import subprocess

_NEW_SESSION_KW = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    if sys.platform == "win32"
    else {"start_new_session": True}
)

# Then pass **_NEW_SESSION_KW to Popen
```

**Verification**:
```bash
anypoc dashboard
# Should start foreground server on http://localhost:8501

# In another terminal:
anypoc dashboard --headless
# Should print PID and log path, then exit
```

---

## 8. Skill Documentation Updates

### 8a. `setup.md`

Add a Windows section after the existing Linux/macOS instructions:

```markdown
## Windows (Docker Desktop)

AnyPoC works on Windows with Docker Desktop. The container layer is still Linux
(Ubuntu), so all project builds and agent runs behave identically.

### Prerequisites

1. Install Docker Desktop for Windows: https://docs.docker.com/desktop/install/windows-install/
2. Ensure WSL2 backend is enabled (Docker Desktop will prompt during install)
3. Install Python 3.10+ and pip

### Installation

```powershell
# In PowerShell or CMD
pip install -e .
anypoc install-skills
```

### Differences from Linux/macOS

- **No tmux**: Windows does not have tmux. Use PowerShell background jobs or
  the `--headless` flag for long-running commands.
- **No sudo**: Docker Desktop handles volume permissions automatically.
- **Paths**: Use Windows paths (e.g., `D:\projects\firefox`). Docker Desktop
  automatically converts them for container bind-mounts.

### Starting a hunt

```powershell
anypoc hunt run history -p openssl time_range="last 6 months"
```

For background execution, use `Start-Process`:

```powershell
Start-Process anypoc -ArgumentList "hunt","run","history","-p","openssl","time_range=last 6 months" -WindowStyle Hidden
```
```

### 8b. Skill references

Update references that mention tmux to include Windows alternatives:

**`find-bugs.md`** and **`hunt.md`** and **`run-poc.md`**:

Replace:
```
Launch in tmux for me — you run `tmux new-session -d -s anypoc-...`
```

With:
```
Launch in background for me:
- On Linux/macOS: `tmux new-session -d -s anypoc-... '...'`
- On Windows: `Start-Process anypoc -ArgumentList "..." -WindowStyle Hidden`
```

**`status.md`**:

Replace `tmux ls` with a cross-platform session discovery:
```powershell
# Windows: list anypoc background processes
Get-Process | Where-Object { $_.ProcessName -like "*python*" -and $_.CommandLine -like "*anypoc*" }
```

---

## 9. Test Plan

### 9.1 Unit-level checks (run on Windows host)

```powershell
# 1. Platform utils
python -c "from anypoc.utils.platform import *; print(get_uid_gid()); print(get_total_memory_bytes() > 0)"

# 2. caw import (the critical one)
python -c "import anypoc; import caw; print('OK — no fcntl error')"

# 3. Project init
anypoc project init testproject
anypoc project status testproject

# 4. Dashboard (foreground)
anypoc dashboard --port 8502
# ^C after confirming http://localhost:8502 loads

# 5. Dashboard (headless)
anypoc dashboard --headless --port 8503
# Verify process starts, then stop with: taskkill /PID <pid>
```

### 9.2 Integration checks (requires Docker Desktop running)

```powershell
# 1. Base image build
anypoc infra build base

# 2. Pull a prebuilt project image (if available)
anypoc project pull testproject

# 3. Run a focused scan (short, does not need long git history)
anypoc scan run focused -p testproject instruction="look for obvious null pointer issues"

# 4. Verify output files exist
ls output/testproject/scans/
```

### 9.3 Edge cases to verify

- [ ] Unicode paths (e.g., `D:\用户\anypoc`)
- [ ] Paths with spaces (e.g., `D:\My Projects\anypoc`)
- [ ] Long-running hunt with `--headless` dashboard
- [ ] Concurrent scan + dashboard

---

## 10. Rollback Plan

If anything breaks, the changes are isolated and easy to revert:

1. **Delete new files**:
   - `src/anypoc/utils/platform.py`
   - `src/anypoc/utils/windows_compat.py`

2. **Revert `pyproject.toml`** — remove `portalocker`

3. **Revert modified files** — use git checkout or manual edits

No database migrations, no API changes, no Docker image rebuilds required.

---

## Appendix A: File Change Summary

| File | Action | Lines changed | Risk |
|------|--------|---------------|------|
| `pyproject.toml` | add `portalocker` dep | 1 line | Low |
| `src/anypoc/utils/windows_compat.py` | **NEW** — monkey-patch caw | ~30 lines | Low |
| `src/anypoc/utils/platform.py` | **NEW** — cross-platform utils | ~80 lines | Low |
| `src/anypoc/__init__.py` | import windows_compat | 1 line | Low |
| `src/anypoc/infra/build.py` | UID/GID + chmod | ~6 lines | Low |
| `src/anypoc/infra/executor.py` | UID/GID + memory | ~4 lines | Low |
| `src/anypoc/utils/permissions.py` | pwd import + chown + sudo | ~15 lines | Medium |
| `src/dashboard/__init__.py` | daemonize + signals + Popen | ~40 lines | Medium |
| `setup.md` | Windows section | +30 lines | Low |
| `src/skills/anypoc/references/*.md` | tmux → Windows alternatives | ~10 lines each | Low |

**Total**: 2 new files, 6 modified files, ~200 lines of code.
