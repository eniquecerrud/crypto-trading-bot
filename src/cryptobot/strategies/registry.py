"""Name-based lookup for built-in strategies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cryptobot.exceptions import StrategyError
from cryptobot.strategies.base import Strategy

REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """Add ``cls`` to the process-wide registry. Used as a class decorator."""
    REGISTRY[cls.name] = cls
    return cls


def available_strategies() -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``(name, description, defaults)`` sorted by name."""
    _ensure_registered()
    return [(cls.name, cls.description, dict(cls.defaults)) for _, cls in sorted(REGISTRY.items())]


def create_strategy(
    name: str,
    params: Mapping[str, Any] | None = None,
    allow_short: bool = False,
) -> Strategy:
    """Instantiate a registered strategy or raise ``StrategyError``."""
    _ensure_registered()
    try:
        cls = REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(REGISTRY)) or "(ninguna)"
        raise StrategyError(f"Estrategia desconocida: {name!r}. Disponibles: {known}.") from exc
    try:
        return cls(params=params, allow_short=allow_short)
    except StrategyError:
        raise
    except ValueError as exc:
        raise StrategyError(str(exc)) from exc


def _ensure_registered() -> None:
    """Import built-in strategy modules so their decorators fill ``REGISTRY``."""
    import cryptobot.strategies  # noqa: F401
