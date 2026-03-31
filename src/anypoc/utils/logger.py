"""Minimal process-wide logging console built on top of Rich.

This module exposes a single global :class:`ConsoleManager` instance that keeps
track of normal log lines and any panels that the caller registers. Regardless
of which module emits a message, everything flows through this manager so the
terminal layout stays consistent: the scrolling log fills the left column while
panel widgets stay aligned in the right column.
"""

from __future__ import annotations

import atexit
import os
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Deque, Mapping
import sys
import traceback

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

_MIN_COLUMN_HEIGHT = 8
_MIN_PANEL_HEIGHT = 4


@dataclass
class _ConsoleConfig:
    include_timestamp: bool = False
    fancy_logging_enabled: bool = False


_CONFIG = _ConsoleConfig()
_TIMESTAMP_ENV = "LOGGER_ENABLE_TIMESTAMPS"
_ENABLE_FANCY_ENV = "FANCY"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"1", "true", "yes", "on"}
    return bool(value)


def _initialize_config_from_env() -> None:
    timestamp_value = os.getenv(_TIMESTAMP_ENV)
    if timestamp_value is not None:
        _CONFIG.include_timestamp = _coerce_bool(timestamp_value)
    enable_fancy_value = os.getenv(_ENABLE_FANCY_ENV)
    if enable_fancy_value is not None:
        _CONFIG.fancy_logging_enabled = _coerce_bool(enable_fancy_value)


_initialize_config_from_env()


def _update_config_attr(attr: str, value: bool) -> bool:
    current = getattr(_CONFIG, attr)
    if current == value:
        return False
    setattr(_CONFIG, attr, value)
    return True


_LEVEL_STYLES: dict[str, str] = {
    "debug": "dim",
    "info": "cyan",
    "warn": "yellow",
    "error": "bold red",
}


@dataclass
class _LogEntry:
    text: str
    style: str | None = None


def _split_lines(message: str) -> list[str]:
    """Convert arbitrary text into individual lines."""

    text = str(message)
    if not text:
        return [""]
    lines = text.splitlines()
    return lines if lines else [text]


class PanelLogger:
    """Mutable panel that can append or overwrite lines."""

    def __init__(
        self,
        manager: "ConsoleManager",
        panel_id: str,
        title: str,
        *,
        max_lines: int = 8,
        border_style: str = "cyan",
    ) -> None:
        self._manager = manager
        self.panel_id = panel_id
        self.title = title or panel_id
        self.border_style = border_style
        self.max_lines = max_lines
        self._lines: Deque[_LogEntry] = deque(maxlen=max_lines)

    def log(self, message: str, *, style: str | None = None) -> None:
        """Append a line (or multiple lines) to this panel."""

        self._record_lines(message, style=style)

    def debug(self, message: str) -> None:
        """Append a debug line with a dim style."""

        self._record_lines(message, style=_LEVEL_STYLES["debug"], level_label="DEBUG")

    def info(self, message: str) -> None:
        """Append an info line with a cyan style."""

        self._record_lines(message, style=_LEVEL_STYLES["info"], level_label="INFO")

    def warn(self, message: str) -> None:
        """Append a warning line with a yellow style."""

        self._record_lines(message, style=_LEVEL_STYLES["warn"], level_label="WARN")

    def error(self, message: str) -> None:
        """Append an error line with a red style."""

        self._record_lines(message, style=_LEVEL_STYLES["error"], level_label="ERROR")

    def set_text(self, message: str, *, style: str | None = None) -> None:
        """Replace panel contents with the provided message."""

        self._record_lines(message, style=style, replace=True)

    def set_dict(self, entries: Mapping[str, Any] | None, *, style: str | None = None) -> None:
        """Render ``key: value`` for each mapping entry."""

        with self._manager._lock:
            if not self._manager._fancy_enabled():
                self._manager._emit_simple_panel_dict(self.panel_id, entries, style=style)
                return
            self._lines.clear()
            if entries:
                for key, value in entries.items():
                    rendered = f"{key}: {value}"
                    self._lines.append(_LogEntry(rendered, style))
            self._manager._refresh_locked()

    def clear(self) -> None:
        """Clear all lines from this panel."""

        with self._manager._lock:
            self._lines.clear()
            if self._manager._fancy_enabled():
                self._manager._refresh_locked()

    def render(self, *, height: int | None = None, max_lines: int | None = None) -> Panel:
        """Render this panel into a Rich ``Panel`` instance."""

        limit = self.max_lines if max_lines is None else min(self.max_lines, max_lines)
        if limit is not None and limit > 0:
            lines = list(self._lines)[-limit:]
        else:
            lines = list(self._lines)

        if not lines:
            body = Text("waiting for updates", style="dim")
        else:
            body = Text()
            for idx, entry in enumerate(lines):
                if idx:
                    body.append("\n")
                body.append(entry.text, style=entry.style)

        panel_kwargs: dict[str, Any] = {
            "title": self.title,
            "border_style": self.border_style,
            "padding": (0, 1),
            "expand": True,
        }
        if height is not None:
            panel_kwargs["height"] = height
        return Panel(body, **panel_kwargs)

    def _record_lines(
        self,
        message: str,
        *,
        style: str | None = None,
        level_label: str | None = None,
        replace: bool = False,
    ) -> None:
        lines = _split_lines(message)
        with self._manager._lock:
            if not self._manager._fancy_enabled():
                self._manager._emit_simple_panel_lines(
                    self.panel_id,
                    lines,
                    level_label=level_label,
                    style=style,
                )
                return
            if replace:
                self._lines.clear()
            for line in lines:
                decorated = self._decorate_panel_line(line, level_label)
                self._lines.append(_LogEntry(decorated, style))
            self._manager._refresh_locked()

    @staticmethod
    def _decorate_panel_line(line: str, level_label: str | None) -> str:
        if not level_label:
            return line
        if not line:
            return f"[{level_label}]"
        return f"[{level_label}] {line}"


class ConsoleManager:
    """Small orchestrator that keeps log output and panels in sync."""

    def __init__(
        self,
        *,
        console: Console | None = None,
        refresh_per_second: int = 10,
        max_log_lines: int = 300,
        default_column_height: int = 24,
    ) -> None:
        self._console = console or Console(force_terminal=True, force_interactive=True)
        self._lock = threading.RLock()
        self._refresh_per_second = refresh_per_second
        self._log_lines: Deque[_LogEntry] = deque(maxlen=max_log_lines)
        self._panels: OrderedDict[str, PanelLogger] = OrderedDict()
        self._live: Live | None = None
        self._default_column_height = max(_MIN_COLUMN_HEIGHT, default_column_height)
        atexit.register(self.stop)

    # Public API ---------------------------------------------------------

    def log(self, message: str, *, style: str | None = None) -> None:
        """Record a normal log line (shows up in the scrolling top section)."""

        self._log_with_metadata(message, style=style)

    def debug(self, message: str) -> None:
        """Record a debug line with a dim style."""

        self._log_with_metadata(message, style=_LEVEL_STYLES["debug"], level_label="DEBUG")

    def info(self, message: str) -> None:
        """Record an info line with a cyan style."""

        self._log_with_metadata(message, style=_LEVEL_STYLES["info"], level_label="INFO")

    def warn(self, message: str) -> None:
        """Record a warning line with a yellow style."""

        self._log_with_metadata(message, style=_LEVEL_STYLES["warn"], level_label="WARN")

    def error(self, message: str) -> None:
        """Record an error line with a red style."""

        self._log_with_metadata(message, style=_LEVEL_STYLES["error"], level_label="ERROR")

    def exception(self, message: str, *args: Any, exc_info: Any = True) -> None:
        """Record an error line and optional exception traceback."""

        if args:
            try:
                message = message % args
            except Exception:
                message = f"{message} {' '.join(str(arg) for arg in args)}"
        self._log_with_metadata(message, style=_LEVEL_STYLES["error"], level_label="ERROR")
        for line in _format_exception_lines(exc_info):
            rendered = line.rstrip("\n")
            self._log_with_metadata(rendered, style=_LEVEL_STYLES["error"])

    def create_panel(
        self,
        panel_id: str,
        *,
        title: str | None = None,
        max_lines: int = 8,
        border_style: str = "cyan",
    ) -> PanelLogger:
        """Return a panel handle, creating it if required."""

        with self._lock:
            panel = self._panels.get(panel_id)
            if panel is None:
                panel = PanelLogger(self, panel_id, title or panel_id, max_lines=max_lines, border_style=border_style)
                self._panels[panel_id] = panel
            else:
                if title:
                    panel.title = title
                if border_style:
                    panel.border_style = border_style
                if max_lines and max_lines != panel.max_lines:
                    panel.max_lines = max_lines
                    panel._lines = deque(panel._lines, maxlen=max_lines)
            if self._fancy_enabled():
                self._ensure_live_locked()
                self._refresh_locked()
            return panel

    def remove_panel(self, panel_id: str) -> None:
        """Remove a panel from the live display if it exists."""

        with self._lock:
            removed = self._panels.pop(panel_id, None)
            if removed and self._fancy_enabled():
                self._refresh_locked()

    def stop(self) -> None:
        """Tear down the live console, leaving the last render on screen."""

        with self._lock:
            if not self._live:
                return
            self._live.stop()
            self._live = None

    # Internal helpers ---------------------------------------------------

    def _ensure_live_locked(self) -> None:
        if self._live or not self._fancy_enabled():
            return
        renderable = self._render()
        self._live = Live(
            renderable,
            console=self._console,
            refresh_per_second=self._refresh_per_second,
            auto_refresh=False,
        )
        self._live.start()

    def _refresh_locked(self) -> None:
        if not self._live:
            return
        self._live.update(self._render(), refresh=True)

    def _render(self) -> Layout:
        column_height = self._determine_column_height(len(self._panels))
        layout = Layout()
        layout.split_row(
            Layout(name="logs", ratio=1),
            Layout(name="panels", ratio=1),
        )
        layout["logs"].update(self._render_logs(column_height))
        layout["panels"].update(self._render_panels(column_height))
        return layout

    def _render_logs(self, column_height: int) -> Panel:
        visible_lines = max(1, column_height - 2)
        entries = list(self._log_lines)[-visible_lines:]
        if not entries:
            body = Text("no log entries yet", style="dim")
        else:
            body = Text()
            for idx, entry in enumerate(entries):
                if idx:
                    body.append("\n")
                body.append(entry.text, style=entry.style)
        return Panel(body, title="log output", padding=(0, 1), expand=True, height=column_height)

    def _render_panels(self, column_height: int):
        if not self._panels:
            body = Text("no panels registered", style="dim")
            return Panel(body, title="panels", padding=(0, 1), expand=True, height=column_height)

        panels = list(self._panels.values())
        visible_capacity = max(1, column_height // _MIN_PANEL_HEIGHT)
        if len(panels) > visible_capacity:
            panels = panels[-visible_capacity:]
        heights = self._distribute_panel_heights(column_height, len(panels))
        rendered = []
        for panel, height in zip(panels, heights):
            max_lines = max(1, height - 2)
            rendered.append(panel.render(height=height, max_lines=max_lines))
        return Group(*rendered)

    def _determine_column_height(self, panel_count: int) -> int:
        dynamic_height = max(_MIN_COLUMN_HEIGHT, panel_count * _MIN_PANEL_HEIGHT)
        target = max(self._default_column_height, dynamic_height)
        size = getattr(self._console, "size", None)
        if size and size.height:
            target = max(target, size.height - 2)
        return target

    def _distribute_panel_heights(self, total_height: int, count: int) -> list[int]:
        if count <= 0:
            return []
        base = total_height // count
        remainder = total_height % count
        heights = []
        for idx in range(count):
            height = base + (1 if idx < remainder else 0)
            height = max(_MIN_PANEL_HEIGHT, height)
            heights.append(height)
        adjustment = sum(heights) - total_height
        idx = len(heights) - 1
        while adjustment > 0 and idx >= 0:
            reducible = heights[idx] - _MIN_PANEL_HEIGHT
            if reducible > 0:
                delta = min(reducible, adjustment)
                heights[idx] -= delta
                adjustment -= delta
            idx -= 1
        return heights

    def _log_with_metadata(
        self,
        message: str,
        *,
        style: str | None = None,
        level_label: str | None = None,
    ) -> None:
        lines = _split_lines(message)
        with self._lock:
            if not self._fancy_enabled():
                for line in lines:
                    rendered = self._format_log_line(line, level_label=level_label)
                    self._emit_simple_line(rendered, style=style)
                return
            self._ensure_live_locked()
            for line in lines:
                rendered = self._format_log_line(line, level_label=level_label)
                self._log_lines.append(_LogEntry(rendered, style))
            self._refresh_locked()

    def _format_log_line(self, line: str, *, level_label: str | None = None) -> str:
        prefix_parts: list[str] = []
        if level_label:
            prefix_parts.append(f"[{level_label}]")
        if _CONFIG.include_timestamp:
            prefix_parts.append(datetime.now().strftime("%H:%M:%S"))
        if not prefix_parts:
            return line
        prefix = " ".join(prefix_parts)
        if not line:
            return prefix
        return f"{prefix} {line}"

    def _emit_simple_line(self, text: str, *, style: str | None = None) -> None:
        self._console.print(text, style=style, markup=False)

    def _emit_simple_panel_lines(
        self,
        panel_id: str,
        lines: list[str],
        *,
        level_label: str | None = None,
        style: str | None = None,
    ) -> None:
        prefix = self._build_panel_prefix(panel_id, level_label)
        if not lines:
            self._emit_simple_line(prefix, style=style)
            return
        for line in lines:
            if line:
                self._emit_simple_line(f"{prefix} {line}", style=style)
            else:
                self._emit_simple_line(prefix, style=style)

    def _emit_simple_panel_dict(
        self,
        panel_id: str,
        entries: Mapping[str, Any] | None,
        *,
        style: str | None = None,
    ) -> None:
        prefix = self._build_panel_prefix(panel_id, None)
        if not entries:
            body = "{}"
        else:
            pairs = ", ".join(f"{key}: {value}" for key, value in entries.items())
            body = f"{{{pairs}}}"
        self._emit_simple_line(f"{prefix} {body}".rstrip(), style=style)

    @staticmethod
    def _build_panel_prefix(panel_id: str, level_label: str | None) -> str:
        prefix = f"[{panel_id}]"
        if level_label:
            prefix = f"{prefix} [{level_label}]"
        return prefix

    def _fancy_enabled(self) -> bool:
        return _CONFIG.fancy_logging_enabled

    def _config_updated(self) -> None:
        with self._lock:
            if not self._fancy_enabled():
                self.stop()


_DEFAULT_MANAGER = ConsoleManager()


def get_manager() -> ConsoleManager:
    """Expose the process-global manager."""

    return _DEFAULT_MANAGER


def log(message: str, *, style: str | None = None) -> None:
    """Convenience function that records a line with the default manager."""

    _DEFAULT_MANAGER.log(message, style=style)


def debug(message: str) -> None:
    """Record a debug line with the default manager."""

    _DEFAULT_MANAGER.debug(message)


def info(message: str) -> None:
    """Record an info line with the default manager."""

    _DEFAULT_MANAGER.info(message)


def warn(message: str) -> None:
    """Record a warning line with the default manager."""

    _DEFAULT_MANAGER.warn(message)


def error(message: str) -> None:
    """Record an error line with the default manager."""

    _DEFAULT_MANAGER.error(message)


def exception(message: str, *args: Any, exc_info: Any = True) -> None:
    """Record an error line with traceback details."""

    _DEFAULT_MANAGER.exception(message, *args, exc_info=exc_info)


def get_panel(
    panel_id: str,
    *,
    title: str | None = None,
    max_lines: int = 8,
    border_style: str = "cyan",
) -> PanelLogger:
    """Convenience helper returning a named panel from the default manager."""

    return _DEFAULT_MANAGER.create_panel(
        panel_id,
        title=title,
        max_lines=max_lines,
        border_style=border_style,
    )


def remove_panel(panel_id: str) -> None:
    """Remove a panel created via :func:`get_panel` if it exists."""

    _DEFAULT_MANAGER.remove_panel(panel_id)


def fancy_logging_enabled() -> bool:
    """Return True if the live/fancy console output is enabled."""

    return _DEFAULT_MANAGER._fancy_enabled()


def shutdown() -> None:
    """Stop the live console."""

    _DEFAULT_MANAGER.stop()


def set_config(key: str, value: Any) -> None:
    """Update a global console configuration option.

    Supported keys:
    - ``timestamp`` / ``timestamps`` / ``include_timestamp``: truthy enables timestamps.
    - ``fancy_logging`` / ``fancy``: truthy keeps the live console enabled.
    - ``disable_fancy_logging`` / ``disable_fancy`` / ``simple_output``: truthy disables the live console and
      switches to simple printing.
    """

    if not isinstance(key, str):
        raise ValueError("config key must be a string")
    normalized = key.strip().lower()
    changed = False
    if normalized in {"timestamp", "timestamps", "include_timestamp"}:
        changed = _update_config_attr("include_timestamp", _coerce_bool(value))
    elif normalized in {"fancy_logging", "fancy"}:
        changed = _update_config_attr("fancy_logging_enabled", _coerce_bool(value))
    elif normalized in {"disable_fancy_logging", "disable_fancy", "simple_output"}:
        changed = _update_config_attr("fancy_logging_enabled", not _coerce_bool(value))
    else:
        raise ValueError(f"unknown config key: {key}")
    if changed:
        _DEFAULT_MANAGER._config_updated()


def _format_exception_lines(exc_info: Any) -> list[str]:
    if exc_info is False:
        return []
    if isinstance(exc_info, BaseException):
        return traceback.format_exception(type(exc_info), exc_info, exc_info.__traceback__)
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        exc_type, exc, tb = exc_info
        if exc_type is None or exc is None:
            return []
        return traceback.format_exception(exc_type, exc, tb)
    if exc_info is True or exc_info is None:
        exc_type, exc, tb = sys.exc_info()
        if exc_type is None or exc is None:
            return []
        return traceback.format_exception(exc_type, exc, tb)
    return []


__all__ = [
    "ConsoleManager",
    "PanelLogger",
    "fancy_logging_enabled",
    "debug",
    "error",
    "exception",
    "get_manager",
    "get_panel",
    "remove_panel",
    "info",
    "log",
    "set_config",
    "shutdown",
    "warn",
]
