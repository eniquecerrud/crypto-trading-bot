"""Load YAML or TOML configuration.

Secrets are rejected if they appear anywhere in the file. API keys belong in
the environment (see ``.env.example``), never in a committed config.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cryptobot.data.ohlcv import timeframe_to_seconds
from cryptobot.exceptions import ConfigError
from cryptobot.models import BacktestConfig

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "password",
    "passphrase",
    "token",
    "private_key",
}
_TOP_LEVEL = {
    "exchange",
    "symbol",
    "timeframe",
    "data",
    "strategy",
    "backtest",
    "risk",
    "paper",
    "live",
    "logging",
    "output",
}
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass
class DataSettings:
    """Where candles come from."""

    source: str = "csv"
    csv_path: str | None = None
    cache_dir: str = "data/cache"
    cache_backend: str = "csv"
    sqlite_path: str = "data/cache/ohlcv.sqlite"


@dataclass
class StrategySettings:
    """Strategy name plus the parameters passed to its constructor."""

    name: str = "sma_crossover"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestSettings:
    """Mirrors :class:`cryptobot.models.BacktestConfig` as it appears on disk."""

    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 0.0
    position_size_pct: float = 1.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    allow_short: bool = False
    close_at_end: bool = False

    def to_runtime(self) -> BacktestConfig:
        """Build a validated runtime config or raise ``ConfigError``."""
        runtime = BacktestConfig(
            initial_cash=self.initial_cash,
            fee_rate=self.fee_rate,
            slippage_bps=self.slippage_bps,
            position_size_pct=self.position_size_pct,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            allow_short=self.allow_short,
            close_at_end=self.close_at_end,
        )
        try:
            runtime.validate()
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        return runtime


@dataclass
class RiskSettings:
    """Caps applied on top of the backtest position size."""

    max_position_pct: float = 1.0
    max_daily_loss_pct: float | None = 0.05


@dataclass
class PaperSettings:
    """Polling controls for exchange paper trading."""

    poll_seconds: float = 60.0
    lookback: int = 300


@dataclass
class LiveSettings:
    """Live trading stays off unless this flag is also confirmed on the CLI and in the environment."""

    enabled: bool = False
    sandbox: bool = True


@dataclass
class LoggingSettings:
    """Process-wide log level and format."""

    level: str = "INFO"
    json: bool = False


@dataclass
class OutputSettings:
    """Artifacts written by the backtest command. Paths are relative to the working directory."""

    equity_curve: str = "artifacts/equity.png"
    trades_csv: str = "artifacts/trades.csv"


@dataclass
class AppConfig:
    """Full application configuration."""

    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    data: DataSettings = field(default_factory=DataSettings)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    backtest: BacktestSettings = field(default_factory=BacktestSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    paper: PaperSettings = field(default_factory=PaperSettings)
    live: LiveSettings = field(default_factory=LiveSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    output: OutputSettings = field(default_factory=OutputSettings)


def load_config(path: str | Path) -> AppConfig:
    """Parse ``path`` and return a validated :class:`AppConfig`."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"No existe el archivo de configuración: {config_path}")
    raw = _load_mapping(config_path)
    _reject_secrets(raw)
    _reject_unknown(raw, _TOP_LEVEL, "raíz")
    exchange = _as_str(raw.get("exchange", "binance"), "exchange").lower()
    symbol = _as_str(raw.get("symbol", "BTC/USDT"), "symbol")
    timeframe = _as_str(raw.get("timeframe", "1h"), "timeframe")
    timeframe_to_seconds(timeframe)
    return AppConfig(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        data=_data(raw.get("data")),
        strategy=_strategy(raw.get("strategy")),
        backtest=_backtest(raw.get("backtest")),
        risk=_risk(raw.get("risk")),
        paper=_paper(raw.get("paper")),
        live=_live(raw.get("live")),
        logging=_logging(raw.get("logging")),
        output=_output(raw.get("output")),
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            loaded = yaml.safe_load(text)
        elif suffix == ".toml":
            loaded = tomllib.loads(text)
        else:
            raise ConfigError("La configuración debe ser un archivo .yaml, .yml o .toml.")
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML no válido en {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML no válido en {path}: {exc}") from exc
    if loaded is None:
        raise ConfigError(f"El archivo de configuración está vacío: {path}")
    if not isinstance(loaded, dict):
        raise ConfigError("La configuración debe ser un mapa de claves.")
    return loaded


def _reject_secrets(value: Any, location: str = "raíz") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in _SECRET_KEYS:
                raise ConfigError(
                    f"La clave {key!r} en {location} parece un secreto. "
                    "No guardes credenciales en el archivo de configuración; usa variables de entorno."
                )
            _reject_secrets(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{location}[{index}]")


def _reject_unknown(section: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(
            f"Claves desconocidas en {name}: {', '.join(unknown)}. "
            f"Claves válidas: {', '.join(sorted(allowed))}."
        )


def _section(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"La sección {name} debe ser un mapa.")
    return value


def _data(value: Any) -> DataSettings:
    section = _section(value, "data")
    _reject_unknown(section, {"source", "csv_path", "cache_dir", "cache_backend", "sqlite_path"}, "data")
    source = _as_str(section.get("source", "csv"), "data.source")
    if source not in {"csv", "exchange"}:
        raise ConfigError("data.source debe ser csv o exchange.")
    backend = _as_str(section.get("cache_backend", "csv"), "data.cache_backend")
    if backend not in {"csv", "sqlite"}:
        raise ConfigError("data.cache_backend debe ser csv o sqlite.")
    csv_path = section.get("csv_path")
    if csv_path is not None:
        csv_path = _as_str(csv_path, "data.csv_path")
    if source == "csv" and not csv_path:
        raise ConfigError("data.csv_path es obligatorio cuando data.source es csv.")
    return DataSettings(
        source=source,
        csv_path=csv_path,
        cache_dir=_as_str(section.get("cache_dir", "data/cache"), "data.cache_dir"),
        cache_backend=backend,
        sqlite_path=_as_str(section.get("sqlite_path", "data/cache/ohlcv.sqlite"), "data.sqlite_path"),
    )


def _strategy(value: Any) -> StrategySettings:
    section = _section(value, "strategy")
    _reject_unknown(section, {"name", "params"}, "strategy")
    if "name" not in section:
        raise ConfigError("Falta strategy.name.")
    params = section.get("params") or {}
    if not isinstance(params, dict):
        raise ConfigError("strategy.params debe ser un mapa.")
    return StrategySettings(name=_as_str(section["name"], "strategy.name"), params=dict(params))


def _backtest(value: Any) -> BacktestSettings:
    section = _section(value, "backtest")
    allowed = {
        "initial_cash",
        "fee_rate",
        "slippage_bps",
        "position_size_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "allow_short",
        "close_at_end",
    }
    _reject_unknown(section, allowed, "backtest")
    settings = BacktestSettings(
        initial_cash=_as_float(section.get("initial_cash", 10_000.0), "backtest.initial_cash"),
        fee_rate=_as_float(section.get("fee_rate", 0.001), "backtest.fee_rate"),
        slippage_bps=_as_float(section.get("slippage_bps", 0.0), "backtest.slippage_bps"),
        position_size_pct=_as_float(section.get("position_size_pct", 1.0), "backtest.position_size_pct"),
        stop_loss_pct=_as_optional_float(section.get("stop_loss_pct"), "backtest.stop_loss_pct"),
        take_profit_pct=_as_optional_float(section.get("take_profit_pct"), "backtest.take_profit_pct"),
        allow_short=_as_bool(section.get("allow_short", False), "backtest.allow_short"),
        close_at_end=_as_bool(section.get("close_at_end", False), "backtest.close_at_end"),
    )
    settings.to_runtime()
    return settings


def _risk(value: Any) -> RiskSettings:
    section = _section(value, "risk")
    _reject_unknown(section, {"max_position_pct", "max_daily_loss_pct"}, "risk")
    return RiskSettings(
        max_position_pct=_as_float(section.get("max_position_pct", 1.0), "risk.max_position_pct"),
        max_daily_loss_pct=_as_optional_float(
            section.get("max_daily_loss_pct", 0.05),
            "risk.max_daily_loss_pct",
        ),
    )


def _paper(value: Any) -> PaperSettings:
    section = _section(value, "paper")
    _reject_unknown(section, {"poll_seconds", "lookback"}, "paper")
    lookback = section.get("lookback", 300)
    if isinstance(lookback, float) and lookback.is_integer():
        lookback = int(lookback)
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
        raise ConfigError("paper.lookback debe ser un entero >= 2.")
    poll_seconds = _as_float(section.get("poll_seconds", 60.0), "paper.poll_seconds")
    if poll_seconds < 0:
        raise ConfigError("paper.poll_seconds no puede ser negativo.")
    return PaperSettings(poll_seconds=poll_seconds, lookback=lookback)


def _live(value: Any) -> LiveSettings:
    section = _section(value, "live")
    _reject_unknown(section, {"enabled", "sandbox"}, "live")
    return LiveSettings(
        enabled=_as_bool(section.get("enabled", False), "live.enabled"),
        sandbox=_as_bool(section.get("sandbox", True), "live.sandbox"),
    )


def _logging(value: Any) -> LoggingSettings:
    section = _section(value, "logging")
    _reject_unknown(section, {"level", "json"}, "logging")
    level = _as_str(section.get("level", "INFO"), "logging.level").upper()
    if level not in _LOG_LEVELS:
        raise ConfigError("logging.level debe ser DEBUG, INFO, WARNING, ERROR o CRITICAL.")
    return LoggingSettings(level=level, json=_as_bool(section.get("json", False), "logging.json"))


def _output(value: Any) -> OutputSettings:
    section = _section(value, "output")
    _reject_unknown(section, {"equity_curve", "trades_csv"}, "output")
    return OutputSettings(
        equity_curve=_as_str(section.get("equity_curve", "artifacts/equity.png"), "output.equity_curve"),
        trades_csv=_as_str(section.get("trades_csv", "artifacts/trades.csv"), "output.trades_csv"),
    )


def _as_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} debe ser un texto no vacío.")
    return value.strip()


def _as_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} debe ser numérico.")
    return float(value)


def _as_optional_float(value: Any, name: str) -> float | None:
    if value is None:
        return None
    return _as_float(value, name)


def _as_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} debe ser true o false.")
    return value
