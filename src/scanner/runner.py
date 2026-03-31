"""Scan job runner: validates inputs, sets up the job directory, drives a strategy."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anypoc.utils import OUTPUT_DIR, logger
from anypoc.utils.spend_limit import SpendLimiter
from scanner.backpressure import BackpressureGate
from scanner.types import BugReport, BugScanStrategy, StrategyContext

ReportConsumer = Callable[[BugReport, Path], Awaitable[None]]

LOG_PREFIX = "[Scanner]"

MANIFEST_NAME = "manifest.json"


def make_scan_id(strategy_name: str, inputs: dict[str, str]) -> str:
    """Derive a stable scan id from `(strategy, inputs)`.

    Same inputs always produce the same id, so re-running with the same
    inputs reuses the existing job directory (resume by default).
    """
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    return f"{strategy_name}-{digest}"


def resolve_job_dir(project_name: str | None, scan_id: str) -> Path:
    """Resolve the on-disk job directory for a scan id."""
    if project_name:
        return OUTPUT_DIR / project_name / "scans" / scan_id
    return OUTPUT_DIR / "scans" / scan_id


def validate_inputs(strategy_cls: type[BugScanStrategy], raw_inputs: dict[str, str]) -> dict[str, str]:
    """Strict validation: reject unknown keys, fill defaults, error on missing required."""
    declared = {p.name: p for p in strategy_cls.params}

    unknown = set(raw_inputs) - set(declared)
    if unknown:
        raise ValueError(
            f"Unknown parameter(s) for strategy {strategy_cls.name!r}: {sorted(unknown)}. Declared: {sorted(declared)}"
        )

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for name, spec in declared.items():
        if name in raw_inputs and raw_inputs[name] is not None:
            resolved[name] = str(raw_inputs[name])
            continue
        if spec.default is not None:
            resolved[name] = spec.default
            continue
        if spec.required:
            missing.append(name)
    if missing:
        raise ValueError(f"Missing required parameter(s) for strategy {strategy_cls.name!r}: {sorted(missing)}")
    return resolved


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_manifest(job_dir: Path, payload: dict[str, Any]) -> None:
    (job_dir / MANIFEST_NAME).write_text(json.dumps(payload, indent=2, sort_keys=True))


def _read_manifest(job_dir: Path) -> dict[str, Any]:
    path = job_dir / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _prepare_job_dir(
    *,
    job_dir: Path,
    strategy_name: str,
    inputs: dict[str, str],
    source_code_dir: Path,
    force: bool,
) -> dict[str, Any]:
    """Create or reuse the job directory and return the manifest payload."""
    if force and job_dir.exists():
        logger.info(f"{LOG_PREFIX} --force: removing existing job dir {job_dir}")
        shutil.rmtree(job_dir)

    existed = job_dir.exists()
    (job_dir / "reports").mkdir(parents=True, exist_ok=True)
    (job_dir / "logs").mkdir(parents=True, exist_ok=True)
    (job_dir / "state").mkdir(parents=True, exist_ok=True)

    if existed and not force:
        manifest = _read_manifest(job_dir)
        if manifest:
            logger.info(f"{LOG_PREFIX} Resuming existing job at {job_dir}")
            manifest["resumed_at"] = _now_iso()
            manifest["status"] = "running"
            _write_manifest(job_dir, manifest)
            return manifest

    manifest = {
        "scan_id": job_dir.name,
        "strategy": strategy_name,
        "inputs": dict(inputs),
        "source_code_dir": str(source_code_dir),
        "created_at": _now_iso(),
        "status": "running",
    }
    _write_manifest(job_dir, manifest)
    return manifest


async def run_scan_job(
    strategy_cls: type[BugScanStrategy],
    raw_inputs: dict[str, str],
    *,
    project_name: str | None,
    source_code_dir: Path,
    spend_limit: float | None,
    force: bool = False,
    on_report: ReportConsumer | None = None,
    backpressure: BackpressureGate | None = None,
) -> Path:
    """Run a strategy as a scan job. Returns the job directory.

    `on_report` is awaited per yielded report with (report, report_path) so
    downstream consumers (e.g. hunt mode) can dispatch as reports arrive.
    `backpressure` is installed on the strategy context; strategies that opt
    in call `await ctx.backpressure.acquire()` at safe session boundaries.
    """

    inputs = validate_inputs(strategy_cls, raw_inputs)
    scan_id = make_scan_id(strategy_cls.name, inputs)
    job_dir = resolve_job_dir(project_name, scan_id)

    manifest = _prepare_job_dir(
        job_dir=job_dir,
        strategy_name=strategy_cls.name,
        inputs=inputs,
        source_code_dir=source_code_dir,
        force=force,
    )

    spend_limiter = SpendLimiter(
        task_name=f"scan_{strategy_cls.name}",
        project_name=project_name,
        command_limit=spend_limit,
    )

    ctx = StrategyContext(
        project_name=project_name,
        source_code_dir=source_code_dir,
        job_dir=job_dir,
        reports_dir=job_dir / "reports",
        logs_dir=job_dir / "logs",
        state_dir=job_dir / "state",
        spend_limiter=spend_limiter,
        backpressure=backpressure or BackpressureGate(),
    )

    logger.info(f"{LOG_PREFIX} Starting scan job {scan_id} ({strategy_cls.name})")
    logger.info(f"{LOG_PREFIX} Job directory: {job_dir}")
    logger.info(f"{LOG_PREFIX} Inputs: {inputs}")

    strategy = strategy_cls(ctx)
    report_count = 0

    try:
        async for report in strategy.run(inputs):
            report_count += 1
            logger.info(f"{LOG_PREFIX} [{report_count}] {report.identifier}: {report.title}")
            if on_report is not None:
                report_path = ctx.reports_dir / f"{report.identifier}.md"
                await on_report(report, report_path)
        manifest["status"] = "completed"
    except Exception:
        manifest["status"] = "errored"
        manifest["completed_at"] = _now_iso()
        manifest["report_count"] = report_count
        _write_manifest(job_dir, manifest)
        raise

    manifest["completed_at"] = _now_iso()
    manifest["report_count"] = report_count
    _write_manifest(job_dir, manifest)

    logger.info(f"{LOG_PREFIX} Scan job {scan_id} complete: {report_count} report(s) at {ctx.reports_dir}")
    return job_dir


def persist_report(ctx: StrategyContext, report: BugReport) -> Path:
    """Helper for strategies that don't go through the collector toolkit."""
    path = ctx.reports_dir / f"{report.identifier}.md"
    report.to_file(path)
    return path
