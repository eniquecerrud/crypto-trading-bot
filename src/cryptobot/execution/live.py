"""Spot live trading. Construction is not enough: callers must opt in first.

This module sends market orders. :func:`run_live` refuses to build an
authenticated client until :func:`cryptobot.execution.guards.authorize_live`
succeeds. Shorts are not sent; a short signal is treated as flat.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptobot.exceptions import ConfigError, CryptobotError
from cryptobot.execution.guards import authorize_live
from cryptobot.logsetup import log_event
from cryptobot.models import BacktestConfig
from cryptobot.risk.manager import RiskManager

logger = logging.getLogger(__name__)

ExchangeFactory = Callable[..., Any]


@dataclass
class SentOrder:
    """A market order the live runner attempted."""

    side: str
    amount: float
    reason: str
    order_id: str


class LiveTrader:
    """Translate a target position into spot market orders.

    Quantities are read from the exchange balance on every step. The entry
    price used for stops is the average fill of the order this process sent,
    or the mark at the moment an existing balance is discovered.
    """

    dust = 1e-8

    def __init__(
        self,
        exchange: Any,
        symbol: str,
        risk: RiskManager,
        config: BacktestConfig,
        secrets: tuple[str, ...],
    ) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.base, self.quote = split_spot_symbol(symbol)
        self.risk = risk
        self.config = config
        self._secrets = tuple(secret for secret in secrets if secret)
        self.base_qty = 0.0
        self.quote_free = 0.0
        self.entry_price: float | None = None
        self.orders: list[SentOrder] = []

    def sync(self, mark: float) -> None:
        """Refresh free balances. Arm a stop basis if inventory appears."""
        balance = self.exchange.fetch_balance()
        self.base_qty = _currency_free(balance, self.base)
        self.quote_free = _currency_free(balance, self.quote)
        if self.base_qty <= self.dust:
            self.base_qty = 0.0
            self.entry_price = None
        elif self.entry_price is None:
            self.entry_price = mark

    def step(self, target: int, price: float, when: datetime) -> None:
        """Sync balances, honor stops, then rebalance toward ``target``."""
        if price <= 0:
            raise CryptobotError("El precio de mercado no es válido.")
        if target < 0:
            log_event(logger, logging.INFO, "señal short ignorada en spot", symbol=self.symbol)
            target = 0
        self.sync(price)
        equity = self.quote_free + self.base_qty * price
        self.risk.update(when, equity)
        if self._protective_exit(price):
            self.sync(price)
            equity = self.quote_free + self.base_qty * price
            self.risk.update(when, equity)
            return
        if target == 0 and self.base_qty > self.dust:
            self._sell_all(price, "signal")
        elif target == 1 and self.base_qty <= self.dust and self.risk.allow_entry():
            self._buy(price)

    def _protective_exit(self, price: float) -> bool:
        if self.entry_price is None or self.base_qty <= self.dust:
            return False
        stop = self.config.stop_loss_pct
        take = self.config.take_profit_pct
        if stop is not None and price <= self.entry_price * (1.0 - stop):
            self._sell_all(price, "stop_loss")
            return True
        if take is not None and price >= self.entry_price * (1.0 + take):
            self._sell_all(price, "take_profit")
            return True
        return False

    def _buy(self, price: float) -> None:
        fraction = self.risk.position_fraction(self.config.position_size_pct)
        buffer = max(self.config.fee_rate, 0.002)
        spendable = self.quote_free * fraction * (1.0 - buffer)
        if spendable <= 0:
            return
        amount = self._amount(spendable / price)
        if amount <= 0:
            return
        self._submit("buy", amount, "entry", price)

    def _sell_all(self, price: float, reason: str) -> None:
        amount = self._amount(self.base_qty)
        if amount <= 0:
            return
        self._submit("sell", amount, reason, price)

    def _amount(self, quantity: float) -> float:
        if quantity <= self.dust:
            return 0.0
        if hasattr(self.exchange, "amount_to_precision"):
            precise = self.exchange.amount_to_precision(self.symbol, quantity)
            return float(precise)
        return float(f"{quantity:.8f}")

    def _submit(self, side: str, amount: float, reason: str, fallback_price: float) -> None:
        try:
            response = self.exchange.create_order(self.symbol, "market", side, amount)
        except Exception as exc:
            safe = scrub(f"{type(exc).__name__}: {exc}", self._secrets)
            log_event(logger, logging.ERROR, "orden rechazada", side=side, reason=reason, error=safe)
            raise CryptobotError(f"La orden fue rechazada: {safe}") from None
        order_id = str(response.get("id", ""))
        self.orders.append(SentOrder(side=side, amount=amount, reason=reason, order_id=order_id))
        log_event(
            logger,
            logging.INFO,
            "orden enviada",
            symbol=self.symbol,
            side=side,
            amount=amount,
            reason=reason,
            order_id=order_id,
        )
        filled = float(response.get("filled") or amount)
        average = float(response.get("average") or fallback_price)
        if side == "buy":
            self.entry_price = average
            self.base_qty += filled
        else:
            self.base_qty = max(0.0, self.base_qty - filled)
            if self.base_qty <= self.dust:
                self.base_qty = 0.0
                self.entry_price = None


def run_live(
    *,
    exchange_id: str,
    symbol: str,
    sandbox: bool,
    config_enabled: bool,
    cli_opt_in: bool,
    environ: dict[str, str],
    config: BacktestConfig,
    risk: RiskManager,
    targets: list[tuple[int, float, datetime]],
    exchange_factory: ExchangeFactory,
) -> LiveTrader:
    """Authorize, build a client, and step through ``targets``.

    ``targets`` is a sequence of ``(target, price, time)`` so tests can drive
    the loop without a socket. The CLI builds that sequence from the exchange.
    """
    credentials = authorize_live(
        config_enabled=config_enabled,
        cli_opt_in=cli_opt_in,
        environ=environ,
    )
    exchange = exchange_factory(
        exchange_id=exchange_id,
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
        password=credentials.password,
        sandbox=sandbox,
    )
    trader = LiveTrader(
        exchange,
        symbol,
        risk,
        config,
        secrets=(credentials.api_key, credentials.api_secret, credentials.password or ""),
    )
    for target, price, when in targets:
        trader.step(target, price, when)
    return trader


def split_spot_symbol(symbol: str) -> tuple[str, str]:
    """Return ``(base, quote)`` for a spot symbol such as ``BTC/USDT``."""
    if symbol.count("/") != 1 or ":" in symbol:
        raise ConfigError(
            "El trading en vivo de esta versión es spot y exige un símbolo BASE/QUOTE (por ejemplo BTC/USDT)."
        )
    base, quote = symbol.split("/")
    if not base or not quote:
        raise ConfigError(f"Símbolo spot no válido: {symbol!r}.")
    return base, quote


def _currency_free(balance: dict[str, Any], currency: str) -> float:
    entry = balance.get(currency)
    if isinstance(entry, dict) and entry.get("free") is not None:
        return float(entry["free"])
    free = balance.get("free")
    if isinstance(free, dict) and free.get(currency) is not None:
        return float(free[currency])
    return 0.0


def scrub(message: str, secrets: tuple[str, ...]) -> str:
    """Remove credential material from a provider error string."""
    cleaned = message
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "***")
    return cleaned


def utcnow() -> datetime:
    """Current time in UTC. Isolated so tests do not depend on it."""
    return datetime.now(timezone.utc)
