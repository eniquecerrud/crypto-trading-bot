"""Paper trader: simulated fills at a mark price, including the risk gate."""

from datetime import datetime, timedelta, timezone

from cryptobot.config import load_config
from cryptobot.execution.paper import PaperTrader
from cryptobot.execution.portfolio import SpotPortfolio
from cryptobot.models import BacktestConfig
from cryptobot.risk.manager import RiskManager
from cryptobot.service import run_paper_exchange
from tests.conftest import flat_bars


def _trader(**overrides) -> PaperTrader:
    config = BacktestConfig(fee_rate=0, slippage_bps=0, **overrides)
    return PaperTrader(
        SpotPortfolio(config.initial_cash, config.fee_rate, config.slippage_bps),
        RiskManager(1.0, None),
        config,
        "BTC/USDT",
    )


def test_paper_long_round_trip() -> None:
    trader = _trader()
    opened = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert trader.step(1, 100, opened) == []
    closed = trader.step(0, 110, opened + timedelta(hours=1))
    assert len(closed) == 1
    assert closed[0].pnl == 1000
    assert trader.portfolio.side == 0
    assert len(trader.marks) == 2


def test_paper_stop_and_daily_loss_block_reentry() -> None:
    config = BacktestConfig(fee_rate=0, slippage_bps=0, stop_loss_pct=0.05, position_size_pct=1)
    trader = PaperTrader(
        SpotPortfolio(10_000, 0, 0),
        RiskManager(1.0, 0.05),
        config,
        "BTC/USDT",
    )
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    trader.step(1, 100, start)
    stopped = trader.step(1, 90, start + timedelta(hours=1))
    assert stopped[0].exit_reason == "stop_loss"
    assert trader.portfolio.equity(90) == 9000
    trader.step(1, 90, start + timedelta(hours=2))
    assert trader.portfolio.side == 0
    assert len(trader.portfolio.trades) == 1


def test_exchange_paper_loop_uses_injected_prices() -> None:
    config = load_config("configs/example.yaml")
    history = flat_bars(40)
    prices = iter([100.0, 100.0, 101.0])

    def fetch_closed():
        return history

    def fetch_price() -> float:
        return next(prices)

    trader = run_paper_exchange(
        config,
        iterations=3,
        fetch_closed=fetch_closed,
        fetch_price=fetch_price,
        clock=lambda: datetime(2024, 1, 2, tzinfo=timezone.utc),
        sleep=lambda _seconds: None,
    )
    assert len(trader.marks) == 3
    assert trader.portfolio.cash <= config.backtest.initial_cash
