"""Command line interface.

``backtest`` and ``paper`` never send orders. ``live`` is a separate command
and returns an error unless configuration, ``--i-understand-live-trading``,
and ``CRYPTOBOT_ENABLE_LIVE=true`` all agree.
"""

from __future__ import annotations

import functools
import logging
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from dotenv import load_dotenv

from cryptobot import __version__
from cryptobot.config import AppConfig, load_config
from cryptobot.exceptions import CryptobotError
from cryptobot.execution.guards import authorize_live
from cryptobot.execution.live import LiveTrader, utcnow
from cryptobot.logsetup import configure_logging, log_event
from cryptobot.service import (
    download_ohlcv,
    exchange_fetchers,
    make_risk,
    make_strategy,
    run_configured_backtest,
    run_paper_exchange,
    run_paper_replay,
    write_outputs,
)
from cryptobot.strategies import available_strategies

logger = logging.getLogger(__name__)
_F = TypeVar("_F", bound=Callable[..., Any])

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Backtesting y trading de criptomonedas. El modo paper es el predeterminado.",
)


def main() -> None:
    """Console-script entry point."""
    load_dotenv(override=False)
    try:
        app()
    except CryptobotError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None


def _guarded(func: _F) -> _F:
    """Turn expected failures into exit code 2, including under ``CliRunner``."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except CryptobotError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from None

    return wrapper  # type: ignore[return-value]


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", help="Muestra la versión y sale.", is_eager=True),
    ] = False,
) -> None:
    """Aplicación de backtest y paper trading."""
    if version:
        typer.echo(f"cryptobot {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command("list-strategies")
@_guarded
def list_strategies_command() -> None:
    """Lista las estrategias incluidas y sus parámetros por defecto."""
    configure_logging("INFO", json_logs=False)
    for name, description, defaults in available_strategies():
        rendered = ", ".join(f"{key}={value}" for key, value in defaults.items())
        typer.echo(f"{name:22} {description}")
        typer.echo(f"{'':22} parámetros: {rendered}")


@app.command()
@_guarded
def backtest(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", exists=True, dir_okay=False, help="Archivo YAML o TOML."),
    ],
    equity_plot: Annotated[
        Path | None,
        typer.Option("--equity-plot", help="Ruta del PNG. Sustituye a output.equity_curve."),
    ] = None,
    trades_csv: Annotated[
        Path | None,
        typer.Option("--trades-csv", help="Ruta del CSV de operaciones."),
    ] = None,
) -> None:
    """Ejecuta un backtest con el CSV o la caché descritos en la configuración."""
    loaded = _prepare(config)
    result, metrics = run_configured_backtest(loaded)
    plot_path = equity_plot or Path(loaded.output.equity_curve)
    trades_path = trades_csv or Path(loaded.output.trades_csv)
    title = f"{loaded.symbol} · {loaded.strategy.name}"
    plot, blotter = write_outputs(result, plot_path, trades_path, title)
    _print_report(loaded, metrics, result.final_side, result.final_quantity)
    typer.echo(f"Gráfico           {plot}")
    typer.echo(f"Operaciones CSV   {blotter}")


@app.command()
@_guarded
def paper(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", exists=True, dir_okay=False, help="Archivo YAML o TOML."),
    ],
    iterations: Annotated[
        int | None,
        typer.Option("--iterations", min=1, help="Máximo de velas (CSV) o de consultas (exchange)."),
    ] = None,
    pace: Annotated[
        float,
        typer.Option("--pace", min=0, help="Segundos entre líneas del replay CSV. 0 no espera."),
    ] = 0.0,
) -> None:
    """Simula una cartera. Con source csv no usa la red; con exchange solo lee mercado."""
    loaded = _prepare(config)
    if loaded.data.source == "csv":
        result, metrics = run_paper_replay(loaded, bars=iterations)
        _replay_pace(result.equity, pace)
        _print_report(loaded, metrics, result.final_side, result.final_quantity)
        typer.echo("Modo              replay CSV (mismos fills que el backtest, sin órdenes)")
        return
    fetch_closed, fetch_price = exchange_fetchers(loaded)
    trader = run_paper_exchange(
        loaded,
        iterations=iterations,
        fetch_closed=fetch_closed,
        fetch_price=fetch_price,
    )
    if not trader.marks:
        typer.echo("No hubo marcas. Revisa el símbolo, la temporalidad y la conexión.")
        raise typer.Exit(code=2)
    last_equity = trader.marks[-1][1]
    typer.echo(f"Consultas         {len(trader.marks)}")
    typer.echo(f"Capital estimado  {last_equity:,.2f}")
    typer.echo(f"Posición          {_side_label(trader.portfolio.side)}")
    typer.echo(f"Operaciones       {len(trader.portfolio.trades)}")
    typer.echo("Modo              paper contra el exchange (cartera simulada, sin órdenes)")


@app.command()
@_guarded
def fetch(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", exists=True, dir_okay=False, help="Archivo YAML o TOML."),
    ],
    since: Annotated[
        str | None,
        typer.Option("--since", help="Inicio ISO-8601 UTC, por ejemplo 2024-01-01T00:00:00Z."),
    ] = None,
) -> None:
    """Descarga velas OHLCV y las guarda en la caché local (CSV o SQLite)."""
    loaded = _prepare(config)
    since_ms = _parse_since(since) if since else None
    frame = download_ohlcv(loaded, since_ms=since_ms)
    typer.echo(f"Velas en caché    {len(frame)}")
    typer.echo(f"Desde             {frame.index[0].isoformat()}")
    typer.echo(f"Hasta             {frame.index[-1].isoformat()}")
    typer.echo(f"Backend           {loaded.data.cache_backend}")


@app.command()
@_guarded
def live(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", exists=True, dir_okay=False, help="Archivo YAML o TOML."),
    ],
    i_understand_live_trading: Annotated[
        bool,
        typer.Option(
            "--i-understand-live-trading",
            help="Confirmación explícita de que se enviarán órdenes reales con dinero real.",
        ),
    ] = False,
    iterations: Annotated[
        int | None,
        typer.Option("--iterations", min=1, help="Máximo de consultas antes de parar."),
    ] = None,
) -> None:
    """Envía órdenes spot. Bloqueado salvo opt-in triple (config, flag y entorno)."""
    import os

    loaded = _prepare(config)
    credentials = authorize_live(
        config_enabled=loaded.live.enabled,
        cli_opt_in=i_understand_live_trading,
        environ=os.environ,
    )
    from cryptobot.data.fetcher import build_exchange

    exchange = build_exchange(
        loaded.exchange,
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
        password=credentials.password,
        sandbox=loaded.live.sandbox,
    )
    runtime = loaded.backtest.to_runtime()
    trader = LiveTrader(
        exchange,
        loaded.symbol,
        make_risk(loaded),
        runtime,
        secrets=(credentials.api_key, credentials.api_secret, credentials.password or ""),
    )
    strategy = make_strategy(loaded)
    completed = _live_loop(loaded, exchange, trader, strategy, iterations)
    typer.echo(f"Consultas         {completed}")
    typer.echo(f"Órdenes enviadas  {len(trader.orders)}")
    typer.echo("Modo              live spot (órdenes reales)")


def _live_loop(
    loaded: AppConfig,
    exchange: Any,
    trader: LiveTrader,
    strategy: Any,
    iterations: int | None,
) -> int:
    from cryptobot.data.fetcher import drop_incomplete, fetch_ohlcv
    from cryptobot.exceptions import DataError
    from cryptobot.execution.targets import latest_target

    completed = 0
    try:
        while iterations is None or completed < iterations:
            frame = fetch_ohlcv(
                exchange,
                loaded.symbol,
                loaded.timeframe,
                limit=loaded.paper.lookback,
                paginate=False,
            )
            closed = drop_incomplete(frame, loaded.timeframe)
            if closed.empty:
                raise DataError("Todavía no hay una vela cerrada.")
            ticker = exchange.fetch_ticker(loaded.symbol)
            last = ticker.get("last")
            if last is None:
                raise DataError("El ticker no incluyó el último precio.")
            target = latest_target(strategy, closed, loaded.backtest.allow_short)
            trader.step(target, float(last), utcnow())
            completed += 1
            if iterations is None or completed < iterations:
                time.sleep(loaded.paper.poll_seconds)
    except KeyboardInterrupt:
        log_event(logger, logging.INFO, "live interrumpido por el usuario", polls=completed)
    return completed


def _prepare(path: Path) -> AppConfig:
    loaded = load_config(path)
    configure_logging(loaded.logging.level, loaded.logging.json)
    log_event(
        logger,
        logging.INFO,
        "configuración cargada",
        symbol=loaded.symbol,
        strategy=loaded.strategy.name,
        source=loaded.data.source,
    )
    return loaded


def _parse_since(value: str) -> int:
    import pandas as pd

    from cryptobot.exceptions import ConfigError

    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    if pd.isna(stamp):
        raise ConfigError(f"No se pudo interpretar --since {value!r}.")
    return int(stamp.value // 1_000_000)


def _replay_pace(equity: object, pace: float) -> None:
    import pandas as pd

    if pace <= 0 or not isinstance(equity, pd.Series):
        return
    for stamp, value in equity.items():
        typer.echo(f"{stamp.isoformat()}  capital={value:,.2f}")  # type: ignore[union-attr]
        time.sleep(pace)


def _print_report(config: AppConfig, metrics: dict[str, float], side: int, quantity: float) -> None:
    rows = [
        ("Símbolo", config.symbol),
        ("Estrategia", config.strategy.name),
        ("Retorno total", _fmt(metrics["total_return"], "pct")),
        ("CAGR", _fmt(metrics["cagr"], "pct")),
        ("Sharpe", _fmt(metrics["sharpe"], "num")),
        ("Sortino", _fmt(metrics["sortino"], "num")),
        ("Drawdown máximo", _fmt(metrics["max_drawdown"], "pct")),
        ("Tasa de aciertos", _fmt(metrics["win_rate"], "pct")),
        ("Operaciones", _fmt(metrics["num_trades"], "int")),
        ("Capital inicial", _fmt(metrics["initial_equity"], "money")),
        ("Capital final", _fmt(metrics["final_equity"], "money")),
        ("Posición abierta", f"{_side_label(side)} {quantity:.6f}".rstrip("0").rstrip(".")),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        typer.echo(f"{label:<{width}}  {value}")


def _side_label(side: int) -> str:
    if side > 0:
        return "larga"
    if side < 0:
        return "corta"
    return "plana"


def _fmt(value: float, kind: str) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    if kind == "pct":
        return f"{value * 100:.2f}%"
    if kind == "int":
        return str(int(value))
    if kind == "money":
        return f"{value:,.2f}"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return f"{value:.3f}"
