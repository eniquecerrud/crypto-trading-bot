"""Causal indicators.

Every value at position ``t`` depends only on samples at or before ``t``.
Warmup observations are ``NaN`` until ``window`` samples are available.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cryptobot.exceptions import StrategyError


def _window(window: int, name: str) -> int:
    if window < 1:
        raise StrategyError(f"{name} debe ser un entero >= 1.")
    return window


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average. ``NaN`` until ``window`` observations exist."""
    period = _window(window, "window")
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """Exponential moving average with ``adjust=False`` (recursive form).

    The smoothing factor is ``2 / (window + 1)``. Pandas still seeds the
    recursion at the first sample; values before ``window`` observations are
    hidden as ``NaN`` so the series lines up with :func:`sma`.
    """
    period = _window(window, "window")
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Wilder relative strength index, in the range 0 to 100.

    Average gain and loss use an exponential smoother with ``alpha = 1/window``.
    A stretch of pure gains (average loss of zero) is defined as 100.
    """
    period = _window(window, "window")
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    values = 100.0 - (100.0 / (1.0 + rs))
    values = values.mask((avg_loss == 0) & avg_gain.notna(), 100.0)
    values = values.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return values


def bollinger_bands(
    series: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger bands using the population standard deviation (``ddof=0``).

    Returns a frame with columns ``middle``, ``upper``, ``lower``, and ``std``.
    """
    period = _window(window, "window")
    if num_std <= 0:
        raise StrategyError("num_std debe ser positivo.")
    middle = sma(series, period)
    deviation = series.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame(
        {
            "middle": middle,
            "upper": middle + num_std * deviation,
            "lower": middle - num_std * deviation,
            "std": deviation,
        },
        index=series.index,
    )
