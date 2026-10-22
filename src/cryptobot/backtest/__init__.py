"""Backtest engine, metrics, and equity-curve export."""

from cryptobot.backtest.engine import BacktestResult, run_backtest, trades_frame
from cryptobot.backtest.metrics import compute_metrics
from cryptobot.backtest.plot import save_equity_plot

__all__ = [
    "BacktestResult",
    "compute_metrics",
    "run_backtest",
    "save_equity_plot",
    "trades_frame",
]
