"""Runtime settings that do not depend on the configuration parser."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    """Execution assumptions shared by the backtester and the CSV replay.

    ``fee_rate`` is a fraction of notional charged on every fill (``0.001`` is
    0.1% or 10 basis points). ``slippage_bps`` is applied against the trader:
    buys fill higher and sells fill lower. ``position_size_pct`` is the
    fraction of equity allocated as notional when a position is opened.
    """

    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 0.0
    position_size_pct: float = 1.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    allow_short: bool = False
    close_at_end: bool = False

    def validate(self) -> None:
        """Raise ``ValueError`` when a field cannot be simulated safely."""
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if not 0 <= self.fee_rate < 1:
            raise ValueError("fee_rate must be in [0, 1)")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps must be >= 0")
        if not 0 < self.position_size_pct <= 1:
            raise ValueError("position_size_pct must be in (0, 1]")
        if self.stop_loss_pct is not None and not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be in (0, 1)")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive")
