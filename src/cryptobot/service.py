"""Wire configuration to the backtest, paper, and data commands."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from cryptobot.backtest import compute_metrics, run_backtest, save_equity_plot, trades_frame
from cryptobot.backtest.engine import BacktestResult
from cryptobot.config import AppConfig
from cryptobot.data.cache import build_cache
from cryptobot.data.fetcher import build_exchange, drop_incomplete, fetch_ohlcv
from cryptobot.data.ohlcv import read_ohlcv_csv
from cryptobot.exceptions import ConfigError, DataError
from cryptobot.execution.paper import PaperTrader
from cryptobot.execution.portfolio import SpotPortfolio
from cryptobot.execution.targets import latest_target
from cryptobot.logsetup import log_event
from cryptobot.risk.manager import RiskManager
from cryptobot.strategies import create_strategy
from cryptobot.strategies.base import Strategy

logger = logging.getLogger(__name__)


def make_strategy(config: AppConfig) -> Strategy:
    """Instantiate the strategy named in ``config``."""
    return create_strategy(
        config.strategy.name,
        config.strategy.params,
        allow_short=config.backtest.allow_short,
    )


def make_risk(config: AppConfig) -> RiskManager:
    """Instantiate the risk manager named in ``config``."""
    return RiskManager(config.risk.max_position_pct, config.risk.max_daily_loss_pct)


def load_frame(config: AppConfig) -> pd.DataFrame:
    """Load candles from CSV or from the configured exchange and cache."""
    if config.data.source == "csv":
        if not config.data.csv_path:
            raise DataError("data.csv_path es obligatorio cuando data.source es csv.")
        return read_ohlcv_csv(config.data.csv_path)
    if config.data.source != "exchange":
        raise ConfigError("data.source debe ser csv o exchange.")
    return download_ohlcv(config)


def download_ohlcv(
    config: AppConfig,
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> pd.DataFrame:
    """Fetch candles, merge them into the local cache, and return the series.

    This is the only path that opens a network connection for historical data.
    A cache hit is returned when the exchange yields nothing new.
    """
    cache = build_cache(config.data.cache_backend, config.data.cache_dir, config.data.sqlite_path)
    cached = cache.load(config.exchange, config.symbol, config.timeframe)
    start = since_ms
    if start is None and cached is not None and not cached.empty:
        start = int(cached.index[-1].value // 1_000_000) + 1
    exchange = build_exchange(config.exchange)
    try:
        fresh = fetch_ohlcv(
            exchange,
            config.symbol,
            config.timeframe,
            since_ms=start,
            until_ms=until_ms,
        )
    except DataError:
        if cached is not None:
            log_event(logger, logging.INFO, "sin velas nuevas; se usa la caché", symbol=config.symbol)
            return cached
        raise
    merged = cache.upsert(config.exchange, config.symbol, config.timeframe, fresh)
    log_event(
        logger,
        logging.INFO,
        "velas guardadas en caché",
        symbol=config.symbol,
        rows=len(merged),
        backend=config.data.cache_backend,
    )
    return merged


def run_configured_backtest(
    config: AppConfig,
    frame: pd.DataFrame | None = None,
) -> tuple[BacktestResult, dict[str, float]]:
    """Run the backtest described by ``config`` and compute its metrics."""
    candles = frame if frame is not None else load_frame(config)
    result = run_backtest(
        candles,
        make_strategy(config),
        config.backtest.to_runtime(),
        make_risk(config),
        symbol=config.symbol,
    )
    metrics = compute_metrics(result.equity, result.trades)
    return result, metrics


def write_outputs(
    result: BacktestResult,
    equity_path: str | Path,
    trades_path: str | Path,
    title: str,
) -> tuple[Path, Path]:
    """Persist the equity chart and the trade blotter."""
    plot = save_equity_plot(result.equity, equity_path, title)
    destination = Path(trades_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    trades_frame(result.trades).to_csv(destination, index=False)
    return plot, destination


def run_paper_replay(config: AppConfig, bars: int | None = None) -> tuple[BacktestResult, dict[str, float]]:
    """Replay a CSV through the backtest engine.

    Offline paper mode uses the same fills as a backtest, including next-bar
    execution and intrabar stops, so a replay and a backtest of the same file
    match. ``bars`` keeps only the first candles after validation.
    """
    frame = load_frame(config)
    if bars is not None:
        frame = frame.iloc[:bars]
    return run_configured_backtest(config, frame)


def run_paper_exchange(
    config: AppConfig,
    *,
    iterations: int | None,
    fetch_closed: Callable[[], pd.DataFrame],
    fetch_price: Callable[[], float],
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> PaperTrader:
    """Mark a simulated portfolio to a live price for ``iterations`` polls.

    Callers inject the data functions. The CLI passes ccxt wrappers; tests
    pass fakes. The loop stops cleanly on ``KeyboardInterrupt``.
    """
    runtime = config.backtest.to_runtime()
    trader = PaperTrader(
        SpotPortfolio(runtime.initial_cash, runtime.fee_rate, runtime.slippage_bps),
        make_risk(config),
        runtime,
        config.symbol,
    )
    strategy = make_strategy(config)
    now = clock or (lambda: datetime.now(timezone.utc))
    pause = sleep or time.sleep
    completed = 0
    try:
        while iterations is None or completed < iterations:
            closed = fetch_closed()
            price = fetch_price()
            target = latest_target(strategy, closed, runtime.allow_short)
            closed_trades = trader.step(target, price, now())
            log_event(
                logger,
                logging.INFO,
                "mark paper",
                symbol=config.symbol,
                target=target,
                price=price,
                equity=round(trader.portfolio.equity(price), 2),
                side=trader.portfolio.side,
                trades=len(closed_trades),
            )
            completed += 1
            if iterations is None or completed < iterations:
                pause(config.paper.poll_seconds)
    except KeyboardInterrupt:
        log_event(logger, logging.INFO, "paper interrumpido por el usuario", polls=completed)
    return trader


def exchange_fetchers(config: AppConfig) -> tuple[Callable[[], pd.DataFrame], Callable[[], float]]:
    """Build ccxt callables for one paper or live session. Opens a public client."""
    exchange = build_exchange(config.exchange)

    def fetch_closed() -> pd.DataFrame:
        frame = fetch_ohlcv(
            exchange,
            config.symbol,
            config.timeframe,
            limit=config.paper.lookback,
            paginate=False,
        )
        closed = drop_incomplete(frame, config.timeframe)
        if closed.empty:
            raise DataError("Todavía no hay una vela cerrada. Espera al cierre de la vela actual.")
        return closed

    def fetch_price() -> float:
        ticker = exchange.fetch_ticker(config.symbol)
        last = ticker.get("last")
        if last is None:
            raise DataError("El ticker no incluyó el último precio.")
        return float(last)

    return fetch_closed, fetch_price
