"""Bollinger band breakout and mean-reversion strategies."""

from __future__ import annotations

import math

import pandas as pd

from cryptobot.exceptions import StrategyError
from cryptobot.indicators import bollinger_bands
from cryptobot.strategies.base import Strategy, as_int
from cryptobot.strategies.registry import register


class _Bollinger(Strategy):
    """Shared state machine for the two Bollinger modes.

    Reversion buys below the lower band and exits at the middle band.
    Breakout buys above the upper band and exits when price falls back
    through the middle band. Shorts, when enabled, mirror those rules.
    """

    mode: str

    def generate(self, data: pd.DataFrame) -> pd.Series:
        frame = self._prepare(data)
        window = as_int(self.params["window"], "window", minimum=2)
        num_std = self.params["num_std"]
        if isinstance(num_std, bool) or not isinstance(num_std, (int, float)):
            raise StrategyError("num_std debe ser numérico.")
        if not math.isfinite(float(num_std)) or float(num_std) <= 0:
            raise StrategyError("num_std debe ser positivo.")
        bands = bollinger_bands(frame["close"], window, float(num_std))
        close = frame["close"].to_numpy()
        lower = bands["lower"].to_numpy()
        upper = bands["upper"].to_numpy()
        middle = bands["middle"].to_numpy()
        position = 0
        output: list[int] = []
        for price, lo, hi, mid in zip(close, lower, upper, middle, strict=True):
            if math.isnan(mid):
                output.append(0)
                continue
            if self.mode == "reversion":
                position = _step_reversion(position, price, lo, hi, mid, self.allow_short)
            elif self.mode == "breakout":
                position = _step_breakout(position, price, lo, hi, mid, self.allow_short)
            else:
                raise StrategyError(f"Modo Bollinger desconocido: {self.mode!r}.")
            output.append(position)
        return self._clamp(pd.Series(output, index=frame.index, dtype="int64"))


def _step_reversion(
    position: int,
    price: float,
    lower: float,
    upper: float,
    middle: float,
    allow_short: bool,
) -> int:
    if position == 0:
        if price < lower:
            return 1
        if allow_short and price > upper:
            return -1
        return 0
    if position == 1 and price >= middle:
        if allow_short and price > upper:
            return -1
        return 0
    if position == -1 and price <= middle:
        if price < lower:
            return 1
        return 0
    return position


def _step_breakout(
    position: int,
    price: float,
    lower: float,
    upper: float,
    middle: float,
    allow_short: bool,
) -> int:
    if position == 0:
        if price > upper:
            return 1
        if allow_short and price < lower:
            return -1
        return 0
    if position == 1 and price < middle:
        if allow_short and price < lower:
            return -1
        return 0
    if position == -1 and price > middle:
        if price > upper:
            return 1
        return 0
    return position


@register
class BollingerReversion(_Bollinger):
    """Fade moves that close outside the bands."""

    name = "bollinger_reversion"
    description = "Reversión a la media en bandas de Bollinger."
    defaults = {"window": 20, "num_std": 2.0}
    mode = "reversion"


@register
class BollingerBreakout(_Bollinger):
    """Follow closes that break out of the bands."""

    name = "bollinger_breakout"
    description = "Ruptura de bandas de Bollinger."
    defaults = {"window": 20, "num_std": 2.0}
    mode = "breakout"
