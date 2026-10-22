"""Live trading stays off unless every opt-in is present, then sends spot orders."""

from datetime import datetime, timezone

import pytest

from cryptobot.exceptions import ConfigError, LiveTradingDisabled
from cryptobot.execution.guards import authorize_live
from cryptobot.execution.live import LiveTrader, run_live, scrub, split_spot_symbol
from cryptobot.models import BacktestConfig
from cryptobot.risk.manager import RiskManager


def _env(**overrides: str) -> dict[str, str]:
    base = {
        "CRYPTOBOT_ENABLE_LIVE": "false",
        "CRYPTOBOT_API_KEY": "",
        "CRYPTOBOT_API_SECRET": "",
    }
    base.update(overrides)
    return base


def test_authorize_reports_every_missing_gate() -> None:
    with pytest.raises(LiveTradingDisabled) as caught:
        authorize_live(config_enabled=False, cli_opt_in=False, environ=_env())
    message = str(caught.value)
    assert "live.enabled" in message
    assert "--i-understand-live-trading" in message
    assert "CRYPTOBOT_ENABLE_LIVE" in message
    assert "CRYPTOBOT_API_KEY" in message


def test_authorize_returns_credentials_only_when_complete() -> None:
    creds = authorize_live(
        config_enabled=True,
        cli_opt_in=True,
        environ=_env(
            CRYPTOBOT_ENABLE_LIVE="true",
            CRYPTOBOT_API_KEY="key-1",
            CRYPTOBOT_API_SECRET="secret-1",
            CRYPTOBOT_API_PASSWORD="pass-1",
        ),
    )
    assert creds.api_key == "key-1"
    assert creds.password == "pass-1"


def test_run_live_does_not_build_an_exchange_when_blocked() -> None:
    def factory(**kwargs):
        raise AssertionError(kwargs)

    with pytest.raises(LiveTradingDisabled):
        run_live(
            exchange_id="binance",
            symbol="BTC/USDT",
            sandbox=True,
            config_enabled=False,
            cli_opt_in=False,
            environ=_env(),
            config=BacktestConfig(),
            risk=RiskManager(1, None),
            targets=[],
            exchange_factory=factory,
        )


class _FakeExchange:
    def __init__(self) -> None:
        self.base = 0.0
        self.quote = 1_000.0
        self.price = 100.0
        self.orders: list[tuple[str, float]] = []

    def fetch_balance(self) -> dict:
        return {"BTC": {"free": self.base}, "USDT": {"free": self.quote}}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.6f}"

    def create_order(self, symbol: str, order_type: str, side: str, amount: float) -> dict:
        amount = float(amount)
        if side == "buy":
            self.quote -= amount * self.price
            self.base += amount
        else:
            self.quote += amount * self.price
            self.base = max(0.0, self.base - amount)
        self.orders.append((side, amount))
        return {"id": str(len(self.orders)), "filled": amount, "average": self.price, "status": "closed"}


def test_live_spot_buys_then_sells_and_scrubs_secrets() -> None:
    exchange = _FakeExchange()

    def factory(**kwargs):
        assert kwargs["api_key"] == "key-1"
        return exchange

    when = datetime(2024, 6, 1, tzinfo=timezone.utc)
    trader = run_live(
        exchange_id="binance",
        symbol="BTC/USDT",
        sandbox=False,
        config_enabled=True,
        cli_opt_in=True,
        environ=_env(
            CRYPTOBOT_ENABLE_LIVE="true",
            CRYPTOBOT_API_KEY="key-1",
            CRYPTOBOT_API_SECRET="secret-1",
        ),
        config=BacktestConfig(fee_rate=0, position_size_pct=1, stop_loss_pct=None),
        risk=RiskManager(1, None),
        targets=[(1, 100.0, when), (0, 100.0, when), (-1, 100.0, when)],
        exchange_factory=factory,
    )
    assert [order.side for order in trader.orders] == ["buy", "sell"]
    assert exchange.base == 0
    assert "key-1" not in scrub("auth failed key-1 / secret-1", ("key-1", "secret-1"))


def test_live_stop_sells_the_inventory() -> None:
    exchange = _FakeExchange()
    trader = LiveTrader(
        exchange,
        "BTC/USDT",
        RiskManager(1, None),
        BacktestConfig(fee_rate=0, stop_loss_pct=0.05),
        secrets=(),
    )
    start = datetime(2024, 6, 1, tzinfo=timezone.utc)
    trader.step(1, 100, start)
    exchange.price = 90
    trader.step(1, 90, start)
    assert [order.side for order in trader.orders] == ["buy", "sell"]
    assert trader.orders[1].reason == "stop_loss"


def test_futures_symbol_is_rejected() -> None:
    with pytest.raises(ConfigError):
        split_spot_symbol("BTC/USDT:USDT")
