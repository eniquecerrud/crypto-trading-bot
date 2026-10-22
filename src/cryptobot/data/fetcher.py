"""Download OHLCV candles through any object that exposes ``fetch_ohlcv``.

The ccxt client is constructed lazily in :func:`build_exchange` so importing
this module, and the offline test suite, never opens a socket.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import pandas as pd

from cryptobot.data.ohlcv import rows_to_frame, timeframe_to_seconds
from cryptobot.exceptions import ConfigError, DataError


class OHLCVExchange(Protocol):
    """Minimal exchange surface used by the downloader."""

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[float]]:
        """Return rows of ``[timestamp_ms, open, high, low, close, volume]``."""


def fetch_ohlcv(
    exchange: OHLCVExchange,
    symbol: str,
    timeframe: str,
    since_ms: int | None = None,
    until_ms: int | None = None,
    limit: int = 1000,
    pause_seconds: float = 0.0,
    max_batches: int = 10_000,
    paginate: bool = True,
) -> pd.DataFrame:
    """Page through ``exchange.fetch_ohlcv`` and return a validated frame.

    Pagination stops on an empty page, a short page, or a timestamp that does
    not move forward. Set ``paginate=False`` to keep a single recent page,
    which is what paper trading wants. ``pause_seconds`` is optional; ccxt's
    own rate limiter is preferred when the real client is used.
    """
    if limit <= 0:
        raise DataError("limit debe ser positivo.")
    if not paginate:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        if until_ms is not None:
            batch = [row for row in batch if int(row[0]) <= until_ms]
        if not batch:
            raise DataError(f"No se descargaron velas para {symbol} {timeframe}.")
        return rows_to_frame(batch)
    collected: list[list[float]] = []
    since = since_ms
    for _ in range(max_batches):
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        if not batch:
            break
        if until_ms is not None:
            batch = [row for row in batch if int(row[0]) <= until_ms]
            if not batch:
                break
        collected.extend(batch)
        last_ms = int(batch[-1][0])
        if until_ms is not None and last_ms >= until_ms:
            break
        if len(batch) < limit:
            break
        next_since = last_ms + 1
        if since is not None and next_since <= since:
            break
        since = next_since
        if pause_seconds > 0:
            time.sleep(pause_seconds)
    if not collected:
        raise DataError(f"No se descargaron velas para {symbol} {timeframe}.")
    return rows_to_frame(collected)


def drop_incomplete(data: pd.DataFrame, timeframe: str, now: datetime | None = None) -> pd.DataFrame:
    """Remove the last candle when it is still forming.

    ccxt timestamps are the candle open time. The bar is closed only after a
    full timeframe has elapsed.
    """
    if data.empty:
        return data
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    last_open = data.index[-1].to_pydatetime()
    if last_open.tzinfo is None:
        last_open = last_open.replace(tzinfo=timezone.utc)
    if last_open + timedelta(seconds=timeframe_to_seconds(timeframe)) > moment:
        return data.iloc[:-1].copy()
    return data


def build_exchange(
    exchange_id: str,
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    password: str | None = None,
    sandbox: bool = False,
) -> Any:
    """Construct a ccxt exchange. Credentials are optional for public data."""
    import ccxt

    if not exchange_id or not exchange_id.replace("_", "").isalnum():
        raise ConfigError(f"Identificador de exchange no válido: {exchange_id!r}.")
    if not hasattr(ccxt, exchange_id):
        raise ConfigError(f"ccxt no conoce el exchange {exchange_id!r}.")
    params: dict[str, Any] = {"enableRateLimit": True}
    if api_key and api_secret:
        params["apiKey"] = api_key
        params["secret"] = api_secret
        if password:
            params["password"] = password
    exchange = getattr(ccxt, exchange_id)(params)
    if sandbox:
        if not hasattr(exchange, "set_sandbox_mode"):
            raise ConfigError(f"El exchange {exchange_id!r} no expone modo sandbox en ccxt.")
        exchange.set_sandbox_mode(True)
    return exchange
