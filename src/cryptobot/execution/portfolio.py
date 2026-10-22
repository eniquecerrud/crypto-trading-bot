"""Spot (and simplified short) portfolio accounting.

Long trades spend cash, including fees, and cannot exceed the cash balance.
Short trades are a simplified margin model: selling increases cash and a
later buy covers the position. Shorts can drive cash negative if price gaps
through the stop; leave them disabled unless you want that model. The runner
applies slippage once, inside :meth:`SpotPortfolio.open_to` and
:meth:`SpotPortfolio.close`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

ExitReason = Literal["signal", "stop_loss", "take_profit", "end"]


@dataclass(frozen=True)
class Trade:
    """A round trip from flat to flat."""

    symbol: str
    side: Literal["long", "short"]
    quantity: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    pnl: float
    return_pct: float
    fees: float
    exit_reason: ExitReason


def _as_timestamp(value: datetime | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


class SpotPortfolio:
    """Cash plus a single signed base-asset position."""

    def __init__(self, cash: float, fee_rate: float, slippage_bps: float) -> None:
        if cash <= 0:
            raise ValueError("cash must be positive")
        if fee_rate < 0 or slippage_bps < 0:
            raise ValueError("fee_rate and slippage_bps must be >= 0")
        self.cash = float(cash)
        self.fee_rate = float(fee_rate)
        self.slippage_bps = float(slippage_bps)
        self.position = 0.0
        self.entry_price: float | None = None
        self.entry_time: pd.Timestamp | None = None
        self.symbol = ""
        self.fees_paid = 0.0
        self._cash_before_entry = self.cash
        self._fees_before_entry = 0.0
        self.trades: list[Trade] = []

    @property
    def side(self) -> int:
        """``1`` long, ``-1`` short, ``0`` flat."""
        if self.position > 0:
            return 1
        if self.position < 0:
            return -1
        return 0

    def equity(self, mark: float) -> float:
        """Mark the open position to ``mark``."""
        return self.cash + self.position * mark

    def open_to(
        self,
        target_side: int,
        raw_price: float,
        when: datetime | pd.Timestamp,
        equity: float,
        fraction: float,
        symbol: str,
    ) -> bool:
        """Open a position from flat. Return whether an order was filled."""
        if self.position != 0:
            raise RuntimeError("open_to requires a flat portfolio")
        if target_side not in (1, -1) or fraction <= 0 or equity <= 0 or raw_price <= 0:
            return False
        buy = target_side == 1
        fill = self._fill(raw_price, buy=buy)
        if buy:
            spendable = min(equity * fraction, self.cash)
            quantity = spendable / (fill * (1.0 + self.fee_rate))
        else:
            quantity = (equity * fraction) / fill
        if quantity <= 1e-12:
            return False
        self._cash_before_entry = self.cash
        self._fees_before_entry = self.fees_paid
        self.symbol = symbol
        if buy:
            self._apply_buy(quantity, fill)
        else:
            self._apply_sell(quantity, fill)
        self.entry_price = fill
        self.entry_time = _as_timestamp(when)
        return True

    def close(
        self,
        raw_price: float,
        when: datetime | pd.Timestamp,
        reason: ExitReason,
    ) -> Trade:
        """Close the whole position at ``raw_price`` before slippage."""
        if self.position == 0 or self.entry_price is None or self.entry_time is None:
            raise RuntimeError("close requires an open position")
        quantity = abs(self.position)
        side: Literal["long", "short"] = "long" if self.position > 0 else "short"
        buy = self.position < 0
        fill = self._fill(raw_price, buy=buy)
        if buy:
            self._apply_buy(quantity, fill)
        else:
            self._apply_sell(quantity, fill)
        self.position = 0.0
        notional = self.entry_price * quantity
        pnl = self.cash - self._cash_before_entry
        trade = Trade(
            symbol=self.symbol,
            side=side,
            quantity=quantity,
            entry_time=self.entry_time,
            exit_time=_as_timestamp(when),
            entry_price=self.entry_price,
            exit_price=fill,
            pnl=pnl,
            return_pct=(pnl / notional) if notional else 0.0,
            fees=self.fees_paid - self._fees_before_entry,
            exit_reason=reason,
        )
        self.trades.append(trade)
        self.entry_price = None
        self.entry_time = None
        return trade

    def _fill(self, raw_price: float, *, buy: bool) -> float:
        bump = self.slippage_bps / 10_000.0
        return raw_price * (1.0 + bump) if buy else raw_price * (1.0 - bump)

    def _apply_buy(self, quantity: float, fill: float) -> None:
        cost = quantity * fill
        fee = cost * self.fee_rate
        self.cash -= cost + fee
        self.position += quantity
        self.fees_paid += fee

    def _apply_sell(self, quantity: float, fill: float) -> None:
        proceeds = quantity * fill
        fee = proceeds * self.fee_rate
        self.cash += proceeds - fee
        self.position -= quantity
        self.fees_paid += fee


def protective_price(
    *,
    side: int,
    entry_price: float,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
) -> tuple[float, ExitReason] | None:
    """Return the raw exit price when a stop or target is touched.

    Stops are evaluated before take-profits. If a bar spans both, the stop
    wins. A gap through the level fills at the open instead of at the level.
    """
    if side == 0:
        return None
    if side == 1:
        return _long_exit(entry_price, bar_open, bar_high, bar_low, stop_loss_pct, take_profit_pct)
    return _short_exit(entry_price, bar_open, bar_high, bar_low, stop_loss_pct, take_profit_pct)


def _long_exit(
    entry: float,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
) -> tuple[float, ExitReason] | None:
    if stop_loss_pct is not None:
        level = entry * (1.0 - stop_loss_pct)
        if bar_low <= level:
            raw = bar_open if bar_open <= level else level
            return raw, "stop_loss"
    if take_profit_pct is not None:
        level = entry * (1.0 + take_profit_pct)
        if bar_high >= level:
            raw = bar_open if bar_open >= level else level
            return raw, "take_profit"
    return None


def _short_exit(
    entry: float,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
) -> tuple[float, ExitReason] | None:
    if stop_loss_pct is not None:
        level = entry * (1.0 + stop_loss_pct)
        if bar_high >= level:
            raw = bar_open if bar_open >= level else level
            return raw, "stop_loss"
    if take_profit_pct is not None:
        level = entry * (1.0 - take_profit_pct)
        if bar_low <= level:
            raw = bar_open if bar_open <= level else level
            return raw, "take_profit"
    return None
