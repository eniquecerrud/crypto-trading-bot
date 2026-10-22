"""RSI mean-reversion strategy."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from cryptobot.exceptions import StrategyError
from cryptobot.indicators import rsi
from cryptobot.strategies.base import Strategy, as_int
from cryptobot.strategies.registry import register


def _level(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyError(f"{name} debe ser numérico.")
    number = float(value)
    if not math.isfinite(number):
        raise StrategyError(f"{name} debe ser finito.")
    return number


@register
class RsiMeanReversion(Strategy):
    """Buy oversold RSI and exit when RSI mean-reverts.

    With ``allow_short``, the mirror trade sells overbought RSI. The position
    is sticky: a signal stays on until the exit threshold is crossed, so a
    single extreme bar does not open and close on the same decision.
    """

    name = "rsi_mean_reversion"
    description = "Reversión a la media con RSI."
    defaults = {
        "window": 14,
        "oversold": 30.0,
        "overbought": 70.0,
        "exit_long": 50.0,
        "exit_short": 50.0,
    }

    def generate(self, data: pd.DataFrame) -> pd.Series:
        frame = self._prepare(data)
        window = as_int(self.params["window"], "window", minimum=2)
        oversold = _level(self.params["oversold"], "oversold")
        overbought = _level(self.params["overbought"], "overbought")
        exit_long = _level(self.params["exit_long"], "exit_long")
        exit_short = _level(self.params["exit_short"], "exit_short")
        if not 0 < oversold < exit_long < overbought < 100:
            raise StrategyError("Se requiere 0 < oversold < exit_long < overbought < 100.")
        if not oversold < exit_short < overbought:
            raise StrategyError("exit_short debe estar entre oversold y overbought.")

        values = rsi(frame["close"], window).to_numpy()
        position = 0
        output: list[int] = []
        for reading in values:
            if np.isnan(reading):
                output.append(0)
                continue
            if position == 0:
                if reading < oversold:
                    position = 1
                elif self.allow_short and reading > overbought:
                    position = -1
            elif position == 1 and reading > exit_long:
                position = -1 if self.allow_short and reading > overbought else 0
            elif position == -1 and reading < exit_short:
                position = 1 if reading < oversold else 0
            output.append(position)
        return self._clamp(pd.Series(output, index=frame.index, dtype="int64"))
