"""Cross-platform utilities for AnyPoC.

Wraps Unix-only operations so the host-side Python code can run on Windows
against Docker Desktop.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple


def is_windows() -> bool:
    return sys.platform == "win32"


def get_uid_gid() -> Tuple[int, int]:
    """Return (uid, gid) for the current user.

    On Windows returns (1000, 1000) which matches the playground user baked
    into the Docker image.  Docker Desktop handles volume ownership
    automatically so the exact values do not matter for bind-mounts.
    """
    if is_windows():
        return (1000, 1000)
    import os

    return (os.getuid(), os.getgid())


def get_total_memory_bytes() -> int:
    """Return total physical memory in bytes."""
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
            return 8 * (1 << 30)
        return stat.ullTotalPhys

    import os

    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def safe_chown(path: Path | str, uid: int, gid: int) -> None:
    """Change file ownership.  No-op on Windows."""
    if is_windows():
        return
    import os

    os.chown(path, uid, gid)


def is_root() -> bool:
    """Return True if running as root/admin.  Always False on Windows."""
    if is_windows():
        return False
    import os

    return os.getuid() == 0


def chmod_executable(path: Path | str) -> None:
    """Make a file executable (chmod +x).  No-op on Windows."""
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
    """Return (name, uid, gid) for the given uid.  Dummy on Windows."""
    if is_windows():
        return ("user", uid, 1000)
    import pwd

    pw = pwd.getpwuid(uid)
    return (pw.pw_name, pw.pw_uid, pw.pw_gid)


def getpwnam(name: str) -> Tuple[str, int, int]:
    """Return (name, uid, gid) for the given user name.  Dummy on Windows."""
    if is_windows():
        return (name, 1000, 1000)
    import pwd

    pw = pwd.getpwnam(name)
    return (pw.pw_name, pw.pw_uid, pw.pw_gid)
