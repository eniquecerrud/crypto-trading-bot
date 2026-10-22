"""Helpers for turning a strategy series into a single target."""

from __future__ import annotations

import math

import pandas as pd

from cryptobot.exceptions import DataError
from cryptobot.strategies.base import Strategy


def coerce_target(value: object, allow_short: bool) -> int:
    """Map a signal cell to ``-1``, ``0``, or ``1``."""
    if value is None:
        return 0
    if isinstance(value, float) and math.isnan(value):
        return 0
    try:
        if pd.isna(value):
            return 0
    except TypeError:
        pass
    target = int(value)  # type: ignore[arg-type]
    if target not in (-1, 0, 1):
        raise DataError(f"Señal inválida: {value!r}. Se espera -1, 0 o 1.")
    if target < 0 and not allow_short:
        return 0
    return target


def latest_target(strategy: Strategy, data: pd.DataFrame, allow_short: bool) -> int:
    """Target implied by the last closed bar. Empty history stays flat."""
    if data.empty:
        return 0
    signal = strategy.generate(data)
    if signal.empty:
        return 0
    return coerce_target(signal.iloc[-1], allow_short)
