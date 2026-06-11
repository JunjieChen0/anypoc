"""Utility functions for the PoC module."""

import os
import sys
from pathlib import Path

# Windows compatibility: patch caw's fcntl usage before anything imports caw.
# This MUST run before `from anypoc.utils.base_model import ...` because
# base_model.py does `from caw import ...`.
if sys.platform == "win32":
    import json as _json
    import shutil as _shutil
    import types as _types

    _fcntl_stub = _types.ModuleType("fcntl")
    _fcntl_stub.LOCK_EX = 2  # type: ignore[attr-defined]
    _fcntl_stub.LOCK_SH = 1  # type: ignore[attr-defined]
    _fcntl_stub.LOCK_UN = 8  # type: ignore[attr-defined]
    _fcntl_stub.flock = lambda *a, **kw: None  # type: ignore[attr-defined]
    sys.modules.setdefault("fcntl", _fcntl_stub)

    try:
        import portalocker as _portalocker
    except ImportError:
        _portalocker = None  # type: ignore[assignment]

    if _portalocker is not None:
        import caw.storage as _caw_storage

        def _patched_append(self, entry: dict) -> None:
            if self._subagent:
                entry = {**entry, "subagent": self._subagent}
            with open(self._path, "a", encoding="utf-8") as f:
                _portalocker.lock(f, _portalocker.LOCK_EX)
                f.write(_json.dumps(entry) + "\n")

        _caw_storage.JsonlWriter.append = _patched_append

from anypoc.utils.base_model import (
    BaseModelWithHelpers,
    LLMGeneratedBaseModel,
    extract_model_from_text,
    model_to_description,
)
from anypoc.utils.logger import (
    ConsoleManager,
    PanelLogger,
    debug,
    error,
    fancy_logging_enabled,
    get_manager,
    get_panel,
    info,
    log,
    remove_panel,
    set_config,
    shutdown,
    warn,
)
from . import logger as logger


def _find_project_root() -> Path:
    """Walk up from this file to find the repo root (contains pyproject.toml)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").is_file():
            return current
        current = current.parent
    # Fallback: env var or 4 levels up (src/anypoc/utils/__init__.py)
    return Path(os.environ.get("POC_PROJECT_ROOT", Path(__file__).parent.parent.parent.parent))


PROJECT_ROOT = _find_project_root()

# Home directory for anypoc user data (projects config, output, etc.).
# Defaults to the cloned repo root — anypoc is run from a checkout of the repo,
# so projects/, output/, logs/, etc. live alongside the source by default.
ANYPOC_HOME = Path(os.environ.get("ANYPOC_HOME", PROJECT_ROOT))

# Output directory - configurable via environment variable (absolute path).
# All transient state (caw auth, dashboard logs, scan/poc artifacts) lives under
# this single directory so it can be wiped or relocated as a unit.
OUTPUT_DIR = Path(os.environ.get("POC_OUTPUT_DIR", ANYPOC_HOME / "output"))

# Keep caw's auth staging under OUTPUT_DIR so users of anypoc don't get a
# separate ~/.caw/ directory in their home. Set as an env var (which caw reads
# at call time) so any caw API or CLI invoked from this process inherits it.
CAW_AUTH_DIR = Path(os.environ.get("CAW_AUTH_DIR", OUTPUT_DIR / ".caw"))
os.environ["CAW_AUTH_DIR"] = str(CAW_AUTH_DIR)

# Projects directory - configurable via environment variable (absolute path)
PROJECTS_DIR = Path(os.environ.get("POC_PROJECTS_DIR", ANYPOC_HOME / "projects"))

__all__ = [
    # Paths
    "PROJECT_ROOT",
    "ANYPOC_HOME",
    "CAW_AUTH_DIR",
    "PROJECTS_DIR",
    "OUTPUT_DIR",
    # Base model utilities
    "BaseModelWithHelpers",
    "LLMGeneratedBaseModel",
    "model_to_description",
    "extract_model_from_text",
    # Logger utilities
    "ConsoleManager",
    "PanelLogger",
    "debug",
    "error",
    "fancy_logging_enabled",
    "get_manager",
    "get_panel",
    "info",
    "log",
    "logger",
    "remove_panel",
    "set_config",
    "shutdown",
    "warn",
]
