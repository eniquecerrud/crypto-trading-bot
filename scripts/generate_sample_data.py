"""Write the deterministic sample OHLCV used by the README and the tests.

The series is a sine wave plus a gentle drift and a fixed random seed. It is
not a market recording. Run from the repository root:

    python scripts/generate_sample_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cryptobot.data.ohlcv import write_ohlcv_csv


def build_sample(bars: int = 480, seed: int = 7) -> pd.DataFrame:
    """Return a valid hourly OHLCV frame starting at 2024-01-01 UTC."""
    rng = np.random.default_rng(seed)
    step = np.arange(bars, dtype=float)
    close = 42_000 + 2_500 * np.sin(2 * np.pi * step / 72) + 4.0 * step
    close = close + rng.normal(0, 80, bars)
    close = np.maximum(close, 100.0)
    open_ = np.empty(bars)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    wick = np.maximum(np.abs(close - open_) * 0.25, close * 0.0015)
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volume = rng.uniform(5, 40, bars)
    index = pd.Timestamp("2024-01-01T00:00:00Z") + pd.to_timedelta(np.arange(bars), unit="h")
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=pd.DatetimeIndex(index, name="timestamp"),
    )
    return frame


def main() -> None:
    destination = Path("data/sample/BTC-USDT-1h.csv")
    path = write_ohlcv_csv(build_sample(), destination)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
