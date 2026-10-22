"""Shared candle builders. Nothing here touches the network."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cryptobot.strategies.base import Strategy


def make_bars(
    rows: list[tuple[float, float, float, float]],
    start: str = "2024-01-01T00:00:00Z",
) -> pd.DataFrame:
    """Build a canonical OHLCV frame from ``(open, high, low, close)`` rows."""
    index = pd.Timestamp(start) + pd.to_timedelta(np.arange(len(rows)), unit="h")
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)
    frame["volume"] = 10.0
    frame.index.name = "timestamp"
    return frame


def flat_bars(n: int, price: float = 100.0, start: str = "2024-01-01T00:00:00Z") -> pd.DataFrame:
    """``n`` identical candles."""
    return make_bars([(price, price, price, price)] * n, start=start)


class ScriptedStrategy(Strategy):
    """Test double that emits a predetermined target on each bar."""

    name = "scripted"
    description = "Señales fijas para tests."
    defaults: dict[str, object] = {}

    def __init__(self, signals: list[int], allow_short: bool = False) -> None:
        super().__init__(allow_short=allow_short)
        self.signals = list(signals)

    def generate(self, data: pd.DataFrame) -> pd.Series:
        self._prepare(data)
        if len(self.signals) != len(data):
            raise AssertionError("La longitud de las señales no coincide con las velas.")
        return self._clamp(pd.Series(self.signals, index=data.index, dtype="int64"))
