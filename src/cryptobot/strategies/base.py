"""Strategy interface.

A strategy looks at closed candles and returns the position it wants to hold
after each bar. It does not place orders. The backtester and the paper trader
turn the latest target into a fill on the *next* price they are allowed to
see, which keeps indicator lookahead out of the execution model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import pandas as pd

from cryptobot.data.ohlcv import require_ohlcv
from cryptobot.exceptions import StrategyError


class Strategy(ABC):
    """Pluggable signal generator.

    Subclasses set ``name``, ``description``, and ``defaults``. User parameters
    override ``defaults``. ``allow_short`` is supplied by the runner; when it
    is false the strategy must not emit ``-1``.
    """

    name: str
    description: str
    defaults: dict[str, Any]

    def __init__(
        self,
        params: Mapping[str, Any] | None = None,
        allow_short: bool = False,
    ) -> None:
        merged = dict(self.defaults)
        merged.update(dict(params or {}))
        self.params = merged
        self.allow_short = allow_short

    @abstractmethod
    def generate(self, data: pd.DataFrame) -> pd.Series:
        """Return targets aligned with ``data``.

        Values are ``1`` (long), ``0`` (flat), or ``-1`` (short). The value at
        bar ``t`` may depend only on bars at or before ``t``.
        """

    def _prepare(self, data: pd.DataFrame) -> pd.DataFrame:
        require_ohlcv(data)
        return data

    def _clamp(self, signal: pd.Series) -> pd.Series:
        values = signal.astype("int64").copy()
        if not self.allow_short:
            values = values.clip(lower=0)
        invalid = ~values.isin((-1, 0, 1))
        if invalid.any():
            raise ValueError(f"{self.name} produjo una señal fuera de {{-1, 0, 1}}.")
        return values


def as_int(value: Any, name: str, minimum: int) -> int:
    """Coerce an integral parameter, rejecting bools and fractional numbers."""
    if isinstance(value, bool):
        raise StrategyError(f"{name} debe ser un entero.")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise StrategyError(f"{name} debe ser un entero.")
    if value < minimum:
        raise StrategyError(f"{name} debe ser >= {minimum}.")
    return value
