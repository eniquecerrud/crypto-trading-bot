"""CLI commands against the offline sample. No sockets."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cryptobot.cli import app

runner = CliRunner()


def test_list_strategies() -> None:
    result = runner.invoke(app, ["list-strategies"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "sma_crossover" in result.stdout
    assert "bollinger_reversion" in result.stdout
    assert "rsi_mean_reversion" in result.stdout


def test_backtest_writes_plot_and_trades(tmp_path: Path) -> None:
    plot = tmp_path / "equity.png"
    trades = tmp_path / "trades.csv"
    result = runner.invoke(
        app,
        [
            "backtest",
            "--config",
            "configs/example.yaml",
            "--equity-plot",
            str(plot),
            "--trades-csv",
            str(trades),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Retorno total" in result.stdout
    assert "Sharpe" in result.stdout
    assert plot.is_file() and plot.stat().st_size > 0
    assert "exit_reason" in trades.read_text(encoding="utf-8").splitlines()[0]


def test_paper_replay_is_offline() -> None:
    result = runner.invoke(app, ["paper", "--config", "configs/example.yaml", "--iterations", "80"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "replay CSV" in result.stdout
    assert "Operaciones" in result.stdout


def test_live_is_refused_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("el cliente del exchange no debería construirse")

    monkeypatch.setattr("cryptobot.data.fetcher.build_exchange", explode)
    result = runner.invoke(app, ["live", "--config", "configs/example.yaml"])
    combined = result.stdout + result.stderr
    assert result.exit_code == 2
    assert "bloqueado" in combined
    assert "paper" in combined


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "cryptobot" in result.stdout
