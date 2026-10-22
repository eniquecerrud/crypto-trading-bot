"""Paper trading against a mark price, with a simulated portfolio."""

from __future__ import annotations

from datetime import datetime

from cryptobot.execution.portfolio import ExitReason, SpotPortfolio, Trade, protective_price
from cryptobot.models import BacktestConfig
from cryptobot.risk.manager import RiskManager


class PaperTrader:
    """Rebalance a :class:`SpotPortfolio` when the target or a stop changes.

    Fills use the supplied mark (a ticker last price, or a replayed open).
    Intrabar highs and lows are not invented: pass a bar through the backtester
    when you need that path. Here the mark is both the fill and the stop check.
    """

    def __init__(
        self,
        portfolio: SpotPortfolio,
        risk: RiskManager,
        config: BacktestConfig,
        symbol: str,
    ) -> None:
        self.portfolio = portfolio
        self.risk = risk
        self.config = config
        self.symbol = symbol
        self.marks: list[tuple[datetime, float]] = []

    def step(self, target: int, price: float, when: datetime) -> list[Trade]:
        """Apply ``target`` at ``price`` and return any trades closed on this step."""
        if target < 0 and not self.config.allow_short:
            target = 0
        if target not in (-1, 0, 1):
            raise ValueError("target must be -1, 0, or 1")
        closed: list[Trade] = []
        self.risk.update(when, self.portfolio.equity(price))
        if self.portfolio.side != target:
            if self.portfolio.side != 0:
                closed.append(self.portfolio.close(price, when, "signal"))
            if target != 0 and self.risk.allow_entry():
                equity = self.portfolio.equity(price)
                fraction = self.risk.position_fraction(self.config.position_size_pct)
                self.portfolio.open_to(target, price, when, equity, fraction, self.symbol)
        elif self.portfolio.side != 0 and self.portfolio.entry_price is not None:
            trigger = protective_price(
                side=self.portfolio.side,
                entry_price=self.portfolio.entry_price,
                bar_open=price,
                bar_high=price,
                bar_low=price,
                stop_loss_pct=self.config.stop_loss_pct,
                take_profit_pct=self.config.take_profit_pct,
            )
            if trigger is not None:
                raw, reason = trigger
                closed.append(self._close(raw, when, reason))
        self.risk.update(when, self.portfolio.equity(price))
        self.marks.append((when, self.portfolio.equity(price)))
        return closed

    def _close(self, raw: float, when: datetime, reason: ExitReason) -> Trade:
        return self.portfolio.close(raw, when, reason)
