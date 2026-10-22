"""Metric definitions on hand-built equity curves."""

from __future__ import annotations

import math

import pandas as pd

from cryptobot.backtest.metrics import SECONDS_PER_YEAR, compute_metrics
from cryptobot.execution.portfolio import Trade


def _equity(values: list[float], periods: int | None = None) -> pd.Series:
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    if periods is None:
        index = start + pd.to_timedelta(range(len(values)), unit="h")
    else:
        index = [start, start + pd.Timedelta(seconds=SECONDS_PER_YEAR)]
    return pd.Series(values, index=pd.DatetimeIndex(index, name="timestamp"))


def _trade(pnl: float) -> Trade:
    stamp = pd.Timestamp("2024-01-01T00:00:00Z")
    return Trade(
        symbol="BTC/USDT",
        side="long",
        quantity=1,
        entry_time=stamp,
        exit_time=stamp,
        entry_price=100,
        exit_price=100 + pnl,
        pnl=pnl,
        return_pct=pnl / 100,
        fees=0,
        exit_reason="signal",
    )


def test_drawdown_return_and_win_rate() -> None:
    metrics = compute_metrics(_equity([100, 80, 90]), [_trade(5), _trade(-5), _trade(1)])
    assert math.isclose(metrics["total_return"], -0.1)
    assert math.isclose(metrics["max_drawdown"], -0.2)
    assert metrics["win_rate"] == 2 / 3
    assert metrics["num_trades"] == 3


def test_constant_positive_returns_make_sharpe_infinite() -> None:
    metrics = compute_metrics(_equity([100, 110, 121]), [])
    assert math.isinf(metrics["sharpe"])
    assert math.isinf(metrics["sortino"])
    assert metrics["max_drawdown"] == 0
    assert math.isnan(metrics["win_rate"])


def test_cagr_doubles_over_one_year() -> None:
    metrics = compute_metrics(_equity([100, 200], periods=1), [])
    assert math.isclose(metrics["cagr"], 1.0)
