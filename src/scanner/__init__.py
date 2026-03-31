"""Bug-scanning framework.

A `BugScanStrategy` produces `BugReport`s from a project. Strategies declare
their string parameters via `params`, and the runner persists each yielded
report under a per-job directory.

Use `register_strategy` to add a new strategy. The CLI exposes them via
`anypoc scan list` and `anypoc scan run`.
"""

from scanner.registry import all_strategies, get_strategy, register_strategy
from scanner.runner import make_scan_id, resolve_job_dir, run_scan_job
from scanner.types import (
    BugReport,
    BugScanStrategy,
    StrategyContext,
    StrategyParam,
)

# Importing strategies registers them with the registry as a side effect.
from scanner import strategies  # noqa: F401

__all__ = [
    "BugReport",
    "BugScanStrategy",
    "StrategyContext",
    "StrategyParam",
    "all_strategies",
    "get_strategy",
    "make_scan_id",
    "register_strategy",
    "resolve_job_dir",
    "run_scan_job",
]
