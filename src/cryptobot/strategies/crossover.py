"""Moving-average crossover strategies."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from cryptobot.exceptions import StrategyError
from cryptobot.indicators import ema, sma
from cryptobot.strategies.base import Strategy, as_int
from cryptobot.strategies.registry import register


class _Crossover(Strategy):
    """Stay long while the fast average is above the slow average."""

    smoother: Callable[[pd.Series, int], pd.Series]

    def generate(self, data: pd.DataFrame) -> pd.Series:
        frame = self._prepare(data)
        fast_window = as_int(self.params["fast_window"], "fast_window", minimum=2)
        slow_window = as_int(self.params["slow_window"], "slow_window", minimum=2)
        if fast_window >= slow_window:
            raise StrategyError("fast_window debe ser menor que slow_window.")
        close = frame["close"]
        fast = self.smoother(close, fast_window)
        slow = self.smoother(close, slow_window)
        signal = pd.Series(0, index=frame.index, dtype="int64")
        valid = fast.notna() & slow.notna()
        signal.loc[valid & (fast > slow)] = 1
        if self.allow_short:
            signal.loc[valid & (fast < slow)] = -1
        return self._clamp(signal)


@register
class SmaCrossover(_Crossover):
    """Long when the fast SMA is above the slow SMA."""

    name = "sma_crossover"
    description = "Cruce de medias móviles simples (SMA)."
    defaults = {"fast_window": 10, "slow_window": 30}
    smoother = staticmethod(sma)


@register
class EmaCrossover(_Crossover):
    """Long when the fast EMA is above the slow EMA."""

    name = "ema_crossover"
    description = "Cruce de medias móviles exponenciales (EMA)."
    defaults = {"fast_window": 12, "slow_window": 26}
    smoother = staticmethod(ema)
