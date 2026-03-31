"""Core types for the bug-scanning framework.

A `BugScanStrategy` is a self-contained way to find bugs in a project. It declares
its required string parameters via `params`, then `run()` yields `BugReport`s as
it discovers them. The framework owns persistence, manifest tracking, and CLI
plumbing — strategies own only the actual scanning logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from scanner._frontmatter import render_with_frontmatter, split_frontmatter
from scanner.backpressure import BackpressureGate

if TYPE_CHECKING:
    from anypoc.utils.spend_limit import SpendLimiter


@dataclass
class BugReport:
    """A generic bug report. The body is free-form markdown.

    Persisted as a single `.md` file with YAML frontmatter carrying the
    structured fields. No JSON sidecar.
    """

    identifier: str
    title: str
    strategy: str
    metadata: dict[str, str] = field(default_factory=dict)
    body: str = ""

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> "BugReport":
        text = Path(path).read_text()
        fm, body = split_frontmatter(text)
        return cls(
            identifier=str(fm.get("identifier", Path(path).stem)),
            title=str(fm.get("title", "")),
            strategy=str(fm.get("strategy", "")),
            metadata={str(k): str(v) for k, v in (fm.get("metadata") or {}).items()},
            body=body,
        )

    def to_file(self, path: str | Path) -> None:
        Path(path).write_text(self._render_full())

    def _render_full(self) -> str:
        fm: dict[str, Any] = {
            "identifier": self.identifier,
            "title": self.title,
            "strategy": self.strategy,
            "metadata": dict(self.metadata),
        }
        return render_with_frontmatter(fm, self.body)

    def to_markdown(self) -> str:
        """Render the report as plain markdown for downstream consumers.

        Includes the title as a top-level heading and the body. Frontmatter
        is intentionally omitted — downstream consumers (POC pipeline) want
        the readable content, not metadata.
        """
        if self.title and not self.body.lstrip().startswith("#"):
            return f"# {self.title}\n\n{self.body}".rstrip() + "\n"
        return self.body if self.body.endswith("\n") else self.body + "\n"


@dataclass(frozen=True)
class StrategyParam:
    """Declared input parameter for a strategy. All values are strings."""

    name: str
    description: str
    required: bool = True
    default: str | None = None


@dataclass
class StrategyContext:
    """Infrastructure handed to every strategy at construction time.

    Strategies should never compute paths themselves — they receive everything
    they need here.
    """

    project_name: str | None
    source_code_dir: Path
    job_dir: Path
    reports_dir: Path
    logs_dir: Path
    state_dir: Path
    spend_limiter: "SpendLimiter"
    backpressure: BackpressureGate = field(default_factory=BackpressureGate)


class BugScanStrategy(ABC):
    """Abstract base class for bug-scanning strategies.

    Subclasses declare `name`, `description`, and `params`, then implement
    `run()` as an async generator that yields `BugReport`s.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    params: ClassVar[list[StrategyParam]]

    def __init__(self, ctx: StrategyContext) -> None:
        self.ctx = ctx

    @abstractmethod
    def run(self, inputs: dict[str, str]) -> AsyncIterator[BugReport]:
        """Run the strategy with validated inputs and yield bug reports."""
        ...
