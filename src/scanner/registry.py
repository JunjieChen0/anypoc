"""Registry for bug-scanning strategies."""

from __future__ import annotations

from typing import TypeVar

from scanner.types import BugScanStrategy

_REGISTRY: dict[str, type[BugScanStrategy]] = {}

T = TypeVar("T", bound=type[BugScanStrategy])


def register_strategy(cls: T) -> T:
    """Class decorator that registers a strategy by its `name` attribute."""
    name = getattr(cls, "name", None)
    if not name:
        raise ValueError(f"Strategy {cls.__name__} must define a class-level `name`.")
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(f"Strategy name {name!r} is already registered.")
    _REGISTRY[name] = cls
    return cls


def get_strategy(name: str) -> type[BugScanStrategy]:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy: {name!r}. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def all_strategies() -> list[type[BugScanStrategy]]:
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]
