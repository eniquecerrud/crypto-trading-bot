"""Built-in strategies stay causal and honor the short-selling switch."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cryptobot.exceptions import StrategyError
from cryptobot.strategies import available_strategies, create_strategy
from cryptobot.strategies.bollinger import _step_breakout, _step_reversion
from tests.conftest import flat_bars


def _wave(n: int = 80) -> pd.DataFrame:
    step = np.arange(n, dtype=float)
    close = 100 + 8 * np.sin(step / 4) + 0.05 * step
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    index = pd.Timestamp("2024-01-01T00:00:00Z") + pd.to_timedelta(step, unit="h")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1.0},
        index=pd.DatetimeIndex(index, name="timestamp"),
    )


def test_registry_lists_the_builtin_names() -> None:
    names = [item[0] for item in available_strategies()]
    assert names == [
        "bollinger_breakout",
        "bollinger_reversion",
        "ema_crossover",
        "rsi_mean_reversion",
        "sma_crossover",
    ]


def test_unknown_strategy_names_the_alternatives() -> None:
    try:
        create_strategy("martingale")
    except StrategyError as exc:
        message = str(exc)
    else:
        raise AssertionError("debía fallar")
    assert "sma_crossover" in message


def test_crossover_is_long_only_unless_shorts_are_enabled() -> None:
    data = _wave()
    long_only = create_strategy("sma_crossover", {"fast_window": 3, "slow_window": 8})
    both = create_strategy(
        "sma_crossover",
        {"fast_window": 3, "slow_window": 8},
        allow_short=True,
    )
    long_signal = long_only.generate(data)
    short_signal = both.generate(data)
    assert set(long_signal.unique()).issubset({0, 1})
    assert -1 in set(short_signal.unique())
    assert (long_signal.iloc[:7] == 0).all()


def test_strategies_are_causal() -> None:
    data = _wave(90)
    names = [
        "sma_crossover",
        "ema_crossover",
        "rsi_mean_reversion",
        "bollinger_reversion",
        "bollinger_breakout",
    ]
    for name in names:
        strategy = create_strategy(name, allow_short=True)
        full = strategy.generate(data)
        for end in (40, 60, 90):
            partial = strategy.generate(data.iloc[:end])
            assert int(partial.iloc[-1]) == int(full.iloc[end - 1]), name


def test_rsi_buys_a_decline_and_ignores_a_rally() -> None:
    rally = flat_bars(5)
    rally["close"] = [100 + i for i in range(5)]
    rally["open"] = [100 + max(i - 1, 0) for i in range(5)]
    rally["high"] = rally[["open", "close"]].max(axis=1) + 0.1
    rally["low"] = rally[["open", "close"]].min(axis=1) - 0.1
    # A long monotone decline pushes RSI to 0 and keeps the long on.
    decline_close = list(range(80, 40, -1))
    decline = flat_bars(len(decline_close))
    decline["close"] = decline_close
    decline["open"] = [decline_close[0], *decline_close[:-1]]
    decline["high"] = decline[["open", "close"]].max(axis=1) + 0.1
    decline["low"] = decline[["open", "close"]].min(axis=1) - 0.1
    strategy = create_strategy(
        "rsi_mean_reversion",
        {"window": 5, "oversold": 30, "overbought": 70, "exit_long": 50, "exit_short": 50},
    )
    assert strategy.generate(rally).eq(0).all() or strategy.generate(rally).max() == 0
    signal = strategy.generate(decline)
    assert signal.iloc[-1] == 1


def test_invalid_crossover_windows_raise() -> None:
    data = _wave(20)
    strategy = create_strategy("ema_crossover", {"fast_window": 10, "slow_window": 5})
    try:
        strategy.generate(data)
    except StrategyError as exc:
        assert "fast_window" in str(exc)
    else:
        raise AssertionError("debía fallar")


def test_bollinger_state_machine() -> None:
    assert _step_reversion(0, price=9, lower=10, upper=12, middle=11, allow_short=False) == 1
    assert _step_reversion(1, price=11, lower=10, upper=12, middle=11, allow_short=False) == 0
    assert _step_reversion(0, price=13, lower=10, upper=12, middle=11, allow_short=True) == -1
    assert _step_breakout(0, price=13, lower=10, upper=12, middle=11, allow_short=False) == 1
    assert _step_breakout(1, price=10.5, lower=10, upper=12, middle=11, allow_short=False) == 0
    assert _step_breakout(0, price=9, lower=10, upper=12, middle=11, allow_short=False) == 0
