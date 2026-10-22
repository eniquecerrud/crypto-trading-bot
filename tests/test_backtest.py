"""Backtest fills, costs, stops, and the daily-loss gate."""

from __future__ import annotations

import math

from cryptobot.backtest.engine import run_backtest
from cryptobot.models import BacktestConfig
from cryptobot.risk.manager import RiskManager
from tests.conftest import ScriptedStrategy, flat_bars, make_bars


def _run(rows, signals, **overrides):
    config = BacktestConfig(**overrides)
    return run_backtest(make_bars(rows), ScriptedStrategy(signals, config.allow_short), config)


def test_signal_fills_on_the_next_open_not_the_signal_close() -> None:
    # Bar 0 closes at 50, which would be a lookahead fill. The order is the
    # next open, 100, and the flat signal on bar 1 exits on bar 2.
    rows = [
        (10, 50, 10, 50),
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 100, 100, 100),
    ]
    result = _run(rows, [1, 0, 0, 0], fee_rate=0, slippage_bps=0)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == 100
    assert trade.exit_price == 100
    assert trade.entry_time == result.equity.index[1]
    assert trade.exit_time == result.equity.index[2]
    assert trade.exit_reason == "signal"


def test_round_trip_on_a_flat_market_loses_the_fees() -> None:
    rows = [(100, 100, 100, 100)] * 4
    result = _run(rows, [1, 0, 0, 0], fee_rate=0.001, slippage_bps=0, position_size_pct=1)
    expected = 10_000 * 99.9 / 100.1
    assert math.isclose(result.equity.iloc[-1], expected, rel_tol=1e-12)
    assert result.trades[0].pnl < 0
    assert result.final_side == 0


def test_slippage_worsens_both_sides() -> None:
    rows = [(100, 100, 100, 100)] * 4
    result = _run(rows, [1, 0, 0, 0], fee_rate=0, slippage_bps=10, position_size_pct=1)
    trade = result.trades[0]
    assert math.isclose(trade.entry_price, 100 * 1.001)
    assert math.isclose(trade.exit_price, 100 * 0.999)


def test_stop_loss_fills_at_the_level() -> None:
    rows = [
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 101, 90, 95),
        (100, 100, 100, 100),
    ]
    result = _run(
        rows,
        [1, 1, 0, 0],
        fee_rate=0,
        slippage_bps=0,
        stop_loss_pct=0.05,
    )
    assert len(result.trades) == 1
    assert result.final_side == 0
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_price == 95
    assert math.isclose(result.equity.iloc[-1], 9500)


def test_gap_through_the_stop_fills_at_the_open() -> None:
    rows = [
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (80, 82, 78, 81),
        (80, 80, 80, 80),
    ]
    result = _run(rows, [1, 1, 0, 0], fee_rate=0, slippage_bps=0, stop_loss_pct=0.05)
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_price == 80
    assert math.isclose(result.equity.iloc[-1], 8000)


def test_take_profit_and_stop_on_the_same_bar_takes_the_stop() -> None:
    rows = [
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 120, 90, 110),
        (100, 100, 100, 100),
    ]
    result = _run(
        rows,
        [1, 1, 0, 0],
        fee_rate=0,
        slippage_bps=0,
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
    )
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_price == 95


def test_take_profit_alone() -> None:
    rows = [
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 120, 100, 115),
        (100, 100, 100, 100),
    ]
    result = _run(rows, [1, 1, 0, 0], fee_rate=0, slippage_bps=0, take_profit_pct=0.10)
    assert result.final_side == 0
    assert result.trades[0].exit_reason == "take_profit"
    assert math.isclose(result.trades[0].exit_price, 110)
    assert math.isclose(result.equity.iloc[-1], 11000)


def test_short_profits_when_price_falls() -> None:
    rows = [
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (80, 80, 80, 80),
        (80, 80, 80, 80),
    ]
    result = _run(rows, [-1, 0, 0, 0], fee_rate=0, slippage_bps=0, allow_short=True)
    assert result.trades[0].side == "short"
    assert math.isclose(result.trades[0].pnl, 2000)
    assert math.isclose(result.equity.iloc[-1], 12000)


def test_position_cap_limits_notional() -> None:
    result = run_backtest(
        flat_bars(3),
        ScriptedStrategy([1, 1, 1]),
        BacktestConfig(fee_rate=0, slippage_bps=0, position_size_pct=1),
        RiskManager(max_position_pct=0.25, max_daily_loss_pct=None),
    )
    assert math.isclose(result.final_quantity, 25)
    assert math.isclose(result.equity.iloc[-1], 10_000)


def test_daily_loss_limit_blocks_the_next_entry() -> None:
    rows = [
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 100, 80, 90),
        (100, 100, 100, 100),
        (100, 100, 100, 100),
    ]
    result = run_backtest(
        make_bars(rows),
        ScriptedStrategy([1, 1, 1, 0, 0]),
        BacktestConfig(fee_rate=0, slippage_bps=0, stop_loss_pct=0.10),
        RiskManager(max_position_pct=1, max_daily_loss_pct=0.05),
    )
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.final_side == 0
    assert math.isclose(result.equity.iloc[-1], 9000)


def test_close_at_end_realizes_the_open_trade() -> None:
    result = _run(
        [(100, 100, 100, 100)] * 3,
        [1, 1, 1],
        fee_rate=0,
        slippage_bps=0,
        close_at_end=True,
    )
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "end"
    assert result.final_side == 0
