"""Performance statistics computed from an equity curve and closed trades."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from cryptobot.execution.portfolio import Trade

SECONDS_PER_YEAR = 365.25 * 24 * 3600


def infer_periods_per_year(index: pd.DatetimeIndex) -> float:
    """Annualize with the median bar spacing. Crypto markets do not close."""
    if len(index) < 2:
        return math.nan
    seconds = index.to_series().diff().dt.total_seconds().dropna()
    median = float(seconds.median())
    if median <= 0 or math.isnan(median):
        return math.nan
    return SECONDS_PER_YEAR / median


def compute_metrics(equity: pd.Series, trades: list[Trade]) -> dict[str, float]:
    """Return total return, CAGR, Sharpe, Sortino, drawdown, and trade stats.

    Sharpe and Sortino use mark-to-market bar returns and a zero risk-free
    rate. Sortino's denominator is the square root of the mean squared
    negative return (positive bars contribute zero). A zero denominator with
    a positive mean is reported as infinity.
    """
    if equity.empty:
        raise ValueError("equity curve is empty")
    initial = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    total_return = (final / initial - 1.0) if initial else math.nan
    returns = equity.pct_change().dropna()
    scale = math.sqrt(infer_periods_per_year(pd.DatetimeIndex(equity.index)))
    mean = float(returns.mean()) if not returns.empty else math.nan
    std = float(returns.std(ddof=1)) if len(returns) > 1 else math.nan
    downside = _downside_deviation(returns)
    drawdown = equity / equity.cummax() - 1.0
    wins = sum(1 for trade in trades if trade.pnl > 0)
    win_rate = (wins / len(trades)) if trades else math.nan
    return {
        "initial_equity": initial,
        "final_equity": final,
        "total_return": total_return,
        "cagr": _cagr(equity),
        "sharpe": _ratio(mean, std, scale),
        "sortino": _ratio(mean, downside, scale),
        "max_drawdown": float(drawdown.min()),
        "win_rate": win_rate,
        "num_trades": float(len(trades)),
    }


def _cagr(equity: pd.Series) -> float:
    initial = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    if initial <= 0 or final <= 0 or len(equity) < 2:
        return math.nan
    seconds = (equity.index[-1] - equity.index[0]).total_seconds()
    years = seconds / SECONDS_PER_YEAR
    if years <= 0:
        return math.nan
    try:
        return (final / initial) ** (1.0 / years) - 1.0
    except OverflowError:
        return math.inf if final > initial else -math.inf


def _downside_deviation(returns: pd.Series) -> float:
    if returns.empty:
        return math.nan
    negative = np.minimum(returns.to_numpy(dtype=float), 0.0)
    return float(np.sqrt(np.mean(negative**2)))


def _ratio(mean: float, denominator: float, scale: float) -> float:
    if math.isnan(mean) or math.isnan(denominator) or math.isnan(scale):
        return math.nan
    if denominator == 0:
        if mean > 0:
            return math.inf
        if mean < 0:
            return -math.inf
        return math.nan
    return mean / denominator * scale
