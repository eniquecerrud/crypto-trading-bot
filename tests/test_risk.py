"""Daily loss halt and position fraction."""

from datetime import datetime, timezone

import pytest

from cryptobot.exceptions import ConfigError
from cryptobot.risk.manager import RiskManager


def test_loss_limit_halts_until_the_next_utc_day() -> None:
    risk = RiskManager(max_position_pct=1, max_daily_loss_pct=0.05)
    monday = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    tuesday = datetime(2024, 1, 2, 0, 5, tzinfo=timezone.utc)
    risk.update(monday, 100)
    risk.update(monday, 94)
    assert risk.halted
    assert not risk.allow_entry()
    risk.update(tuesday, 94)
    assert not risk.halted
    assert risk.allow_entry()


def test_position_fraction_is_capped() -> None:
    risk = RiskManager(max_position_pct=0.2, max_daily_loss_pct=None)
    assert risk.position_fraction(0.9) == 0.2
    assert risk.position_fraction(0.1) == 0.1


def test_invalid_limits_are_rejected() -> None:
    with pytest.raises(ConfigError):
        RiskManager(max_position_pct=0, max_daily_loss_pct=0.1)
    with pytest.raises(ConfigError):
        RiskManager(max_position_pct=0.5, max_daily_loss_pct=0)
