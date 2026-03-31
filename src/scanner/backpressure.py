"""Cooperative backpressure for bug-scan strategies.

A `BackpressureGate` lets a strategy pause between LLM sessions when a
downstream consumer (e.g. the hunt-mode PoC worker pool) is saturated. The
scanner voluntarily calls `acquire` at session boundaries; the dispatcher
calls `register` / `complete` as it starts and finishes PoC tasks. If the
gate is constructed with `max_inflight=None` (the default for plain scans),
every method is a no-op — strategies never need to branch on mode.
"""

from __future__ import annotations

import asyncio


class BackpressureGate:
    """Counter-based gate. No-op when `max_inflight` is None."""

    def __init__(self, max_inflight: int | None = None) -> None:
        self._max = max_inflight
        self._inflight = 0
        self._cond: asyncio.Condition | None = asyncio.Condition() if max_inflight else None

    @property
    def enabled(self) -> bool:
        return self._cond is not None

    @property
    def inflight(self) -> int:
        return self._inflight

    async def acquire(self) -> None:
        """Block until the in-flight count is below the configured max."""
        if self._cond is None:
            return
        async with self._cond:
            while self._inflight >= self._max:
                await self._cond.wait()

    async def register(self) -> None:
        """Record that a downstream task has been dispatched."""
        if self._cond is None:
            return
        async with self._cond:
            self._inflight += 1

    async def complete(self) -> None:
        """Record that a downstream task has finished; wakes waiting scanners."""
        if self._cond is None:
            return
        async with self._cond:
            self._inflight = max(0, self._inflight - 1)
            self._cond.notify_all()
