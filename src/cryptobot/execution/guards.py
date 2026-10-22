"""Opt-in gate for live orders.

Paper trading does not call this module. Live trading requires all of:

* ``live.enabled: true`` in the configuration file
* the CLI flag ``--i-understand-live-trading``
* the environment variable ``CRYPTOBOT_ENABLE_LIVE=true``
* ``CRYPTOBOT_API_KEY`` and ``CRYPTOBOT_API_SECRET`` in the environment

Keys are never read from the configuration file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cryptobot.exceptions import LiveTradingDisabled

LIVE_ENABLE_ENV = "CRYPTOBOT_ENABLE_LIVE"
API_KEY_ENV = "CRYPTOBOT_API_KEY"
API_SECRET_ENV = "CRYPTOBOT_API_SECRET"
API_PASSWORD_ENV = "CRYPTOBOT_API_PASSWORD"


@dataclass(frozen=True)
class LiveCredentials:
    """Exchange credentials held only in memory for the current process."""

    api_key: str
    api_secret: str
    password: str | None


def authorize_live(
    *,
    config_enabled: bool,
    cli_opt_in: bool,
    environ: Mapping[str, str],
) -> LiveCredentials:
    """Return credentials or raise ``LiveTradingDisabled`` with every failed check."""
    reasons: list[str] = []
    if not config_enabled:
        reasons.append("live.enabled es false")
    if not cli_opt_in:
        reasons.append("falta el flag --i-understand-live-trading")
    flag = str(environ.get(LIVE_ENABLE_ENV, "")).strip().lower()
    if flag != "true":
        reasons.append(f"{LIVE_ENABLE_ENV} no es 'true'")
    api_key = str(environ.get(API_KEY_ENV, "")).strip()
    api_secret = str(environ.get(API_SECRET_ENV, "")).strip()
    if not api_key or not api_secret:
        reasons.append(f"faltan {API_KEY_ENV} y {API_SECRET_ENV} en el entorno")
    if reasons:
        detail = "; ".join(reasons)
        raise LiveTradingDisabled(
            "Trading en vivo bloqueado. El modo paper es el predeterminado. " + detail + "."
        )
    password = str(environ.get(API_PASSWORD_ENV, "")).strip() or None
    return LiveCredentials(api_key=api_key, api_secret=api_secret, password=password)
