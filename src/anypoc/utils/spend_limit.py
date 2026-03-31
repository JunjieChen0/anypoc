"""Spend-limit management with persistent cost tracking.

Three levels, checked in priority order (overall > project > command):

1. **Overall** — across all projects.  Limit and running total stored in
   ``~/.anypoc/.cost``.
2. **Per-project** — across all commands for one project.  Limit stored in
   ``~/.anypoc/.cost``; per-task cost history stored in
   ``<output_dir>/<project>/.cost``.
3. **Per-command** — single CLI invocation.  In-memory only.

Usage::

    limiter = SpendLimiter("scan_bug", project_name="firefox", command_limit=5.0)

    for task in tasks:
        if not limiter.can_proceed():
            break
        run_task(task)
        limiter.record_cost_from_traj(traj_path)
"""

from __future__ import annotations

import json
from pathlib import Path

from anypoc.utils import OUTPUT_DIR, logger

LOG_PREFIX = "[SpendLimit]"

# ---------------------------------------------------------------------------
# Persistent stores
# ---------------------------------------------------------------------------


class GlobalCostStore:
    """Read / write ``<OUTPUT_DIR>/.cost`` (overall limit, overall total, project limits)."""

    PATH = OUTPUT_DIR / ".cost"

    def __init__(self) -> None:
        self.overall_limit: float | None = None
        self.overall_total_cost: float = 0.0
        self.project_limits: dict[str, float] = {}

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls) -> GlobalCostStore:
        store = cls()
        if cls.PATH.exists():
            try:
                data = json.loads(cls.PATH.read_text())
            except (json.JSONDecodeError, OSError):
                return store
            store.overall_limit = data.get("overall_limit")
            store.overall_total_cost = float(data.get("overall_total_cost", 0.0))
            store.project_limits = {k: float(v) for k, v in data.get("project_limits", {}).items()}
        return store

    def save(self) -> None:
        self.PATH.parent.mkdir(parents=True, exist_ok=True)
        self.PATH.write_text(
            json.dumps(
                {
                    "overall_limit": self.overall_limit,
                    "overall_total_cost": self.overall_total_cost,
                    "project_limits": self.project_limits,
                },
                indent=2,
            )
        )

    # -- helpers ------------------------------------------------------------

    def get_project_limit(self, project: str) -> float | None:
        return self.project_limits.get(project)

    def set_project_limit(self, project: str, limit: float | None) -> None:
        if limit is None:
            self.project_limits.pop(project, None)
        else:
            self.project_limits[project] = limit


class ProjectCostStore:
    """Read / write ``<output_dir>/<project>/.cost`` (per-task cost history)."""

    def __init__(self, project_name: str) -> None:
        self.project_name = project_name
        self.path = OUTPUT_DIR / project_name / ".cost"
        # {"task_name": {"total_cost": float, "count": int}}
        self.tasks: dict[str, dict[str, float]] = {}

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls, project_name: str) -> ProjectCostStore:
        store = cls(project_name)
        if store.path.exists():
            try:
                data = json.loads(store.path.read_text())
            except (json.JSONDecodeError, OSError):
                return store
            store.tasks = data.get("tasks", {})
        return store

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"tasks": self.tasks}, indent=2))

    # -- helpers ------------------------------------------------------------

    @property
    def total_cost(self) -> float:
        return sum(t.get("total_cost", 0.0) for t in self.tasks.values())

    def task_avg(self, task_name: str) -> float | None:
        """Return historical average cost for *task_name*, or None if no data."""
        task = self.tasks.get(task_name)
        if task and task.get("count", 0) > 0:
            return task["total_cost"] / task["count"]
        return None

    def add_task_cost(self, task_name: str, cost: float) -> None:
        if task_name not in self.tasks:
            self.tasks[task_name] = {"total_cost": 0.0, "count": 0}
        self.tasks[task_name]["total_cost"] += cost
        self.tasks[task_name]["count"] += 1

    def reset(self) -> None:
        self.tasks.clear()


# ---------------------------------------------------------------------------
# SpendLimiter
# ---------------------------------------------------------------------------


class SpendLimiter:
    """Three-level spend limiter with persistent cost tracking.

    Parameters
    ----------
    task_name:
        Identifier for the kind of work (e.g. ``"scan_bug"``).  Used as the
        key in the per-project cost history.
    project_name:
        Project name (optional).  Enables project-level limit checking and
        cost persistence.
    command_limit:
        In-memory dollar cap for this CLI invocation.
    """

    def __init__(
        self,
        task_name: str,
        project_name: str | None = None,
        command_limit: float | None = None,
    ) -> None:
        self.task_name = task_name
        self.project_name = project_name
        self.command_limit = command_limit

        # In-memory (command-level) state
        self._cmd_spent: float = 0.0
        self._cmd_count: int = 0

        # Persistent stores
        self._global = GlobalCostStore.load()
        self._project = ProjectCostStore.load(project_name) if project_name else None

    # ------------------------------------------------------------------
    # Estimation
    # ------------------------------------------------------------------

    @property
    def avg_task_cost(self) -> float:
        """Best available estimate for the cost of the next task.

        Priority: project history for this task name -> current-run average -> 0.
        """
        # 1. Project history
        if self._project is not None:
            avg = self._project.task_avg(self.task_name)
            if avg is not None:
                return avg
        # 2. Current-run average
        if self._cmd_count > 0:
            return self._cmd_spent / self._cmd_count
        # 3. No data
        return 0.0

    # ------------------------------------------------------------------
    # Budget check
    # ------------------------------------------------------------------

    def can_proceed(self) -> bool:
        """Return *True* if the estimated next task stays within all limits.

        Checks overall > project > command (first failure wins).
        When there is no estimate at all (no history, no current-run data)
        the command-level check allows the first task unconditionally;
        overall/project checks still block if already over limit.
        """
        est = self.avg_task_cost

        # 1. Overall (highest priority)
        if self._global.overall_limit is not None:
            if self._global.overall_total_cost + est > self._global.overall_limit:
                logger.info(
                    f"{LOG_PREFIX} Overall limit would be exceeded: "
                    f"${self._global.overall_total_cost:.4f} spent "
                    f"+ ${est:.4f} est. > ${self._global.overall_limit:.2f} limit"
                )
                return False

        # 2. Project
        if self._project is not None and self.project_name:
            project_limit = self._global.get_project_limit(self.project_name)
            if project_limit is not None:
                project_total = self._project.total_cost
                if project_total + est > project_limit:
                    logger.info(
                        f"{LOG_PREFIX} Project '{self.project_name}' limit would be exceeded: "
                        f"${project_total:.4f} spent "
                        f"+ ${est:.4f} est. > ${project_limit:.2f} limit"
                    )
                    return False

        # 3. Command (allow first task when there is no estimate at all)
        if self.command_limit is not None:
            if self._cmd_count > 0 or est > 0:
                if self._cmd_spent + est > self.command_limit:
                    logger.info(
                        f"{LOG_PREFIX} Command limit would be exceeded: "
                        f"${self._cmd_spent:.4f} spent "
                        f"+ ${est:.4f} est. > ${self.command_limit:.2f} limit"
                    )
                    return False

        return True

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_task_cost(self, cost: float) -> None:
        """Record the dollar cost of a completed task (in-memory + persistent)."""
        # In-memory
        self._cmd_spent += cost
        self._cmd_count += 1

        # Persist — project
        if self._project is not None:
            self._project.add_task_cost(self.task_name, cost)
            self._project.save()

        # Persist — global total
        self._global.overall_total_cost += cost
        self._global.save()

        self._log_status(cost)

    def record_cost_from_traj(self, traj_path: Path) -> float:
        """Extract cost from a single trajectory file and record it."""
        from caw import FastStats

        cost = 0.0
        if traj_path.exists():
            fs = FastStats.from_path(traj_path)
            if fs is not None:
                cost = fs.cost_usd
        self.record_task_cost(cost)
        return cost

    def record_cost_from_dir(self, directory: Path) -> float:
        """Sum costs from all trajectory files in *directory* and record."""
        from caw import FastStats

        cost = FastStats.directory_total_cost(directory) if directory.exists() else 0.0
        self.record_task_cost(cost)
        return cost

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _log_status(self, cost: float) -> None:
        parts = [f"Task #{self._cmd_count} ({self.task_name}) cost: ${cost:.4f}"]

        if self.command_limit is not None:
            parts.append(f"Cmd: ${self._cmd_spent:.4f}/${self.command_limit:.2f}")

        if self._project is not None and self.project_name:
            plimit = self._global.get_project_limit(self.project_name)
            plimit_s = f"${plimit:.2f}" if plimit is not None else "no limit"
            parts.append(f"Project: ${self._project.total_cost:.4f}/{plimit_s}")

        if self._global.overall_limit is not None:
            parts.append(f"Overall: ${self._global.overall_total_cost:.4f}/${self._global.overall_limit:.2f}")

        logger.info(f"{LOG_PREFIX} {' | '.join(parts)}")
