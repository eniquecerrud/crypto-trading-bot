"""Equity and drawdown chart export."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_equity_plot(equity: pd.Series, path: str | Path, title: str) -> Path:
    """Write a two-panel PNG of equity and drawdown. Uses the Agg backend."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    drawdown = equity / equity.cummax() - 1.0
    timeline = equity.index.tz_convert("UTC").tz_localize(None)

    figure, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, height_ratios=(2, 1))
    axes[0].plot(timeline, equity.to_numpy(), color="#0f766e", linewidth=1.4)
    axes[0].set_title(title)
    axes[0].set_ylabel("Capital")
    axes[0].grid(True, alpha=0.3)
    axes[1].fill_between(timeline, drawdown.to_numpy(), 0.0, color="#b91c1c", alpha=0.35)
    axes[1].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=1.0))
    axes[1].set_ylabel("Drawdown")
    axes[1].grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(destination, dpi=120)
    plt.close(figure)
    return destination
