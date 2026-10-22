"""Bar-by-bar backtest.

A signal stamped on bar ``t`` is filled at the open of bar ``t + 1``. Stops
and take-profits are then tested against that bar's high and low. This avoids
using the signal bar's close as a fill. If a bar touches both the stop and
the target, the stop is taken.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from cryptobot.data.ohlcv import validate_ohlcv
from cryptobot.exceptions import DataError
from cryptobot.execution.portfolio import SpotPortfolio, Trade, protective_price
from cryptobot.execution.targets import coerce_target
from cryptobot.logsetup import log_event
from cryptobot.models import BacktestConfig
from cryptobot.risk.manager import RiskManager
from cryptobot.strategies.base import Strategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Equity curve, closed trades, and the position still open at the end."""

    equity: pd.Series
    trades: list[Trade]
    final_side: int
    final_quantity: float


def run_backtest(
    data: pd.DataFrame,
    strategy: Strategy,
    config: BacktestConfig,
    risk: RiskManager | None = None,
    symbol: str = "BTC/USDT",
) -> BacktestResult:
    """Simulate ``strategy`` on ``data`` and return the marked equity curve."""
    config.validate()
    frame = validate_ohlcv(data)
    signals = strategy.generate(frame)
    if len(signals) != len(frame) or not signals.index.equals(frame.index):
        raise DataError("La estrategia devolvió señales que no alinean con las velas.")
    manager = risk or RiskManager(max_position_pct=1.0, max_daily_loss_pct=None)
    portfolio = SpotPortfolio(config.initial_cash, config.fee_rate, config.slippage_bps)
    pending = 0
    equities: list[float] = []
    index: list[pd.Timestamp] = []

    for i in range(len(frame)):
        ts = frame.index[i]
        bar_open = float(frame["open"].iloc[i])
        bar_high = float(frame["high"].iloc[i])
        bar_low = float(frame["low"].iloc[i])
        bar_close = float(frame["close"].iloc[i])
        moment = ts.to_pydatetime()
        manager.update(moment, portfolio.equity(bar_open))
        target = pending

        if portfolio.side != target:
            if portfolio.side != 0:
                _record(portfolio.close(bar_open, ts, "signal"))
            if target != 0 and manager.allow_entry():
                fraction = manager.position_fraction(config.position_size_pct)
                portfolio.open_to(
                    target,
                    bar_open,
                    ts,
                    portfolio.equity(bar_open),
                    fraction,
                    symbol,
                )
            elif target != 0:
                log_event(
                    logger,
                    logging.INFO,
                    "entrada bloqueada por el límite de pérdida diaria",
                    time=str(ts),
                    symbol=symbol,
                )

        if portfolio.side != 0 and portfolio.entry_price is not None:
            trigger = protective_price(
                side=portfolio.side,
                entry_price=portfolio.entry_price,
                bar_open=bar_open,
                bar_high=bar_high,
                bar_low=bar_low,
                stop_loss_pct=config.stop_loss_pct,
                take_profit_pct=config.take_profit_pct,
            )
            if trigger is not None:
                raw, reason = trigger
                _record(portfolio.close(raw, ts, reason))

        equities.append(portfolio.equity(bar_close))
        index.append(ts)
        pending = coerce_target(signals.iloc[i], config.allow_short)
        manager.update(moment, equities[-1])

    if config.close_at_end and portfolio.side != 0:
        last_ts = frame.index[-1]
        last_close = float(frame["close"].iloc[-1])
        _record(portfolio.close(last_close, last_ts, "end"))
        equities[-1] = portfolio.equity(last_close)

    equity = pd.Series(equities, index=pd.DatetimeIndex(index, name="timestamp"), name="equity")
    return BacktestResult(
        equity=equity,
        trades=list(portfolio.trades),
        final_side=portfolio.side,
        final_quantity=abs(portfolio.position),
    )


def _record(trade: Trade) -> None:
    log_event(
        logger,
        logging.INFO,
        "operación cerrada",
        symbol=trade.symbol,
        side=trade.side,
        reason=trade.exit_reason,
        pnl=round(trade.pnl, 4),
    )


def trades_frame(trades: list[Trade]) -> pd.DataFrame:
    """Tabular view of closed trades, including the header when there are none."""
    rows = [
        {
            "symbol": trade.symbol,
            "side": trade.side,
            "quantity": trade.quantity,
            "entry_time": trade.entry_time.isoformat(),
            "exit_time": trade.exit_time.isoformat(),
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "pnl": trade.pnl,
            "return_pct": trade.return_pct,
            "fees": trade.fees,
            "exit_reason": trade.exit_reason,
        }
        for trade in trades
    ]
    columns = [
        "symbol",
        "side",
        "quantity",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "pnl",
        "return_pct",
        "fees",
        "exit_reason",
    ]
    return pd.DataFrame(rows, columns=columns)


__all__ = ["BacktestResult", "run_backtest", "trades_frame"]
