"""Risk checks consulted before a new position is opened.

The manager caps notional as a fraction of equity and, once the UTC day's
loss reaches ``max_daily_loss_pct``, blocks new entries until the next UTC
day. Exits, stops, and take-profits are never blocked. The anchor is the
equity observed on the first update of that UTC day.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from cryptobot.exceptions import ConfigError


class RiskManager:
    """Stateful daily risk gate. Create a fresh instance per run."""

    def __init__(self, max_position_pct: float, max_daily_loss_pct: float | None) -> None:
        if not 0 < max_position_pct <= 1:
            raise ConfigError("risk.max_position_pct debe estar en (0, 1].")
        if max_daily_loss_pct is not None and not 0 < max_daily_loss_pct <= 1:
            raise ConfigError("risk.max_daily_loss_pct debe estar en (0, 1] o omitirse.")
        self.max_position_pct = max_position_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.halted = False
        self._day: date | None = None
        self._day_start_equity: float | None = None

    def update(self, now: datetime, equity: float) -> None:
        """Refresh the UTC day anchor and the halt flag from ``equity``."""
        day = _utc_date(now)
        if day != self._day:
            self._day = day
            self._day_start_equity = equity
            self.halted = False
        if self.max_daily_loss_pct is None or self._day_start_equity is None:
            return
        if self._day_start_equity <= 0:
            self.halted = True
            return
        loss = (self._day_start_equity - equity) / self._day_start_equity
        if loss >= self.max_daily_loss_pct:
            self.halted = True

    def allow_entry(self) -> bool:
        """Return whether a new position may be opened right now."""
        return not self.halted

    def position_fraction(self, requested_pct: float) -> float:
        """Return the allowed fraction, never above the configured cap."""
        if requested_pct <= 0:
            return 0.0
        return min(requested_pct, self.max_position_pct)


def _utc_date(now: datetime) -> date:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).date()
