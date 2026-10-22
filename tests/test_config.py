"""Configuration parsing, secret rejection, and TOML support."""

from pathlib import Path

import pytest

from cryptobot.config import load_config
from cryptobot.exceptions import ConfigError


def test_example_yaml_loads() -> None:
    config = load_config("configs/example.yaml")
    assert config.strategy.name == "sma_crossover"
    assert config.data.source == "csv"
    assert config.live.enabled is False
    assert config.backtest.to_runtime().fee_rate == 0.001
    rsi = load_config("configs/rsi.example.yaml")
    assert rsi.strategy.name == "rsi_mean_reversion"
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "CRYPTOBOT_ENABLE_LIVE=false" in example
    assert "CRYPTOBOT_API_KEY=\n" in example
    assert "CRYPTOBOT_API_SECRET=\n" in example


def test_toml_config_and_secret_rejection(tmp_path: Path) -> None:
    path = tmp_path / "bot.toml"
    path.write_text(
        """
exchange = "binance"
symbol = "ETH/USDT"
timeframe = "15m"

[data]
source = "csv"
csv_path = "data/sample/BTC-USDT-1h.csv"

[strategy]
name = "ema_crossover"

[strategy.params]
fast_window = 5
slow_window = 20

[live]
enabled = false
sandbox = true
""".strip(),
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded.symbol == "ETH/USDT"
    assert loaded.timeframe == "15m"
    assert loaded.strategy.params["fast_window"] == 5

    path.write_text(path.read_text(encoding="utf-8") + '\napi_key = "should-not-be-here"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="secreto"):
        load_config(path)


def test_unknown_key_and_bad_suffix(tmp_path: Path) -> None:
    bad = tmp_path / "bot.yaml"
    bad.write_text(
        "data:\n  source: csv\n  csv_path: data.csv\nstrategy:\n  name: sma_crossover\n  nope: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="desconocidas"):
        load_config(bad)
    other = tmp_path / "bot.json"
    other.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="yaml"):
        load_config(other)
