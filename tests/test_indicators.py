"""Indicator values checked against the textbook formulas."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from cryptobot.indicators import bollinger_bands, ema, rsi, sma


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_sma_matches_manual_window() -> None:
    result = sma(_series([1, 2, 3, 4, 5]), 3)
    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])
    assert result.iloc[2:].tolist() == [2, 3, 4]


def test_ema_matches_recursive_definition() -> None:
    result = ema(_series([1, 2, 3, 4, 5]), 3)
    # span 3 -> alpha 0.5, min_periods 3 hides the seed.
    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])
    assert result.iloc[2] == 2.25
    assert result.iloc[3] == 3.125
    assert result.iloc[4] == 4.0625


def test_rsi_is_bounded_and_extreme_on_monotone_series() -> None:
    rising = rsi(_series(list(range(1, 40))), 14)
    falling = rsi(_series(list(range(40, 1, -1))), 14)
    assert rising.dropna().between(0, 100).all()
    assert falling.dropna().between(0, 100).all()
    assert rising.dropna().iloc[-1] == 100
    assert falling.dropna().iloc[-1] == 0


def test_bollinger_uses_population_std() -> None:
    values = _series([1, 2, 3, 4, 5])
    bands = bollinger_bands(values, window=3, num_std=2)
    assert math.isnan(bands["middle"].iloc[1])
    assert bands["middle"].iloc[2] == 2
    expected_std = float(np.std([1, 2, 3], ddof=0))
    assert bands["std"].iloc[2] == expected_std
    assert bands["upper"].iloc[2] == 2 + 2 * expected_std
    assert bands["lower"].iloc[4] == bands["middle"].iloc[4] - 2 * bands["std"].iloc[4]
