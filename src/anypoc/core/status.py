#!/usr/bin/env python3
"""
Pipeline Status - Shared status tracking for POC generation pipeline.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from anypoc.utils import logger

AnalysisStatus = Literal["pending", "valid", "rejected", "error"]
GenerationStatus = Literal["pending", "completed", "help_needed", "error"]
EvidenceCheckStatus = Literal[
    "pending", "passed", "flaky", "invalid_evidence", "not_reproducible", "help_needed", "error"
]
ReportStatus = Literal["pending", "completed", "skipped", "error"]

LOG_PREFIX = "[Pipeline Status]"


@dataclass
class StepStatus:
    """Status for a single pipeline step."""

    status: str = "pending"
    timestamp: str = ""

    def update(self, status: str) -> None:
        self.status = status
        self.timestamp = datetime.now().isoformat()


@dataclass
class PipelineStatus:
    """Overall pipeline status tracking."""

    analysis: StepStatus = field(default_factory=StepStatus)
    generation: StepStatus = field(default_factory=StepStatus)
    evidence_check: StepStatus = field(default_factory=StepStatus)
    report: StepStatus = field(default_factory=StepStatus)

    # Metadata
    bug_report_path: str = ""
    output_dir: str = ""
    started_at: str = ""
    completed_at: str = ""

    # Attempt tracking
    attempt_number: int = 1
    resumed_from: int | None = None  # Previous attempt number if resuming
    help_needed_reason: str = ""  # Reason if help_needed status

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now().isoformat()

    def mark_complete(self) -> None:
        self.completed_at = datetime.now().isoformat()

    def save(self, output_dir: Path) -> Path:
        """Save status to status.json in output directory."""
        status_path = output_dir / "status.json"
        temp_path = status_path.with_name(f".{status_path.name}.{os.getpid()}.tmp")
        payload = json.dumps(asdict(self), indent=2)

        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(status_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return status_path

    @classmethod
    def load(cls, output_dir: Path) -> "PipelineStatus":
        """Load status from status.json if it exists."""
        status_path = output_dir / "status.json"
        if status_path.exists():
            try:
                raw = status_path.read_text(encoding="utf-8")
                if not raw.strip():
                    raise ValueError("status.json is empty")

                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("status.json did not contain an object")
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warn(f"{LOG_PREFIX} Failed to load {status_path}: {e}")
                return cls()

            return cls(
                analysis=StepStatus(
                    status=data.get("analysis", {}).get("status", "pending"),
                    timestamp=data.get("analysis", {}).get("timestamp", ""),
                ),
                generation=StepStatus(
                    status=data.get("generation", {}).get("status", "pending"),
                    timestamp=data.get("generation", {}).get("timestamp", ""),
                ),
                evidence_check=StepStatus(
                    status=data.get("evidence_check", {}).get("status", "pending"),
                    timestamp=data.get("evidence_check", {}).get("timestamp", ""),
                ),
                report=StepStatus(
                    status=data.get("report", {}).get("status", "pending"),
                    timestamp=data.get("report", {}).get("timestamp", ""),
                ),
                bug_report_path=data.get("bug_report_path", ""),
                output_dir=data.get("output_dir", ""),
                started_at=data.get("started_at", ""),
                completed_at=data.get("completed_at", ""),
                attempt_number=data.get("attempt_number", 1),
                resumed_from=data.get("resumed_from"),
                help_needed_reason=data.get("help_needed_reason", ""),
            )
        return cls()

    def needs_help(self) -> bool:
        """Check if this run is waiting for help."""
        return self.generation.status == "help_needed" or self.evidence_check.status == "help_needed"

    def get_final_status(self) -> str:
        """Get overall pipeline result."""
        if self.analysis.status == "rejected":
            return "rejected"
        if self.analysis.status == "error":
            return "analysis_error"
        if self.generation.status == "help_needed":
            return "generation_help_needed"
        if self.generation.status == "error":
            return "generation_error"
        if self.evidence_check.status == "help_needed":
            return "evidence_check_help_needed"
        if self.evidence_check.status == "error":
            return "evidence_check_error"
        if self.evidence_check.status == "invalid_evidence":
            return "invalid_evidence"
        if self.evidence_check.status == "not_reproducible":
            return "not_reproducible"
        if self.evidence_check.status == "flaky":
            return "flaky"
        if self.evidence_check.status == "passed":
            return "passed"
        return "incomplete"


def find_next_attempt_number(base_output_dir: Path) -> int:
    """Find the next available attempt number in the output directory."""
    if not base_output_dir.exists():
        return 1

    max_attempt = 0
    for entry in base_output_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("attempt_"):
            try:
                attempt_num = int(entry.name.split("_")[1])
                max_attempt = max(max_attempt, attempt_num)
            except (IndexError, ValueError):
                continue

    return max_attempt + 1


def get_attempt_dir(base_output_dir: Path, attempt_number: int) -> Path:
    """Get the directory path for a specific attempt."""
    return base_output_dir / f"attempt_{attempt_number}"


def find_latest_help_needed_attempt(base_output_dir: Path) -> tuple[int, PipelineStatus] | None:
    """
    Find the latest attempt that needs help.

    Returns:
        Tuple of (attempt_number, PipelineStatus) if found, None otherwise.
    """
    if not base_output_dir.exists():
        return None

    attempts: list[tuple[int, Path]] = []
    for entry in base_output_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("attempt_"):
            try:
                attempt_num = int(entry.name.split("_")[1])
                attempts.append((attempt_num, entry))
            except (IndexError, ValueError):
                continue

    # Sort by attempt number descending to find latest first
    attempts.sort(key=lambda x: x[0], reverse=True)

    for attempt_num, attempt_dir in attempts:
        status = PipelineStatus.load(attempt_dir)
        if status.needs_help():
            return attempt_num, status

    return None


def load_attempt_status(base_output_dir: Path, attempt_number: int) -> PipelineStatus | None:
    """Load the status for a specific attempt."""
    attempt_dir = get_attempt_dir(base_output_dir, attempt_number)
    if not attempt_dir.exists():
        return None
    return PipelineStatus.load(attempt_dir)
