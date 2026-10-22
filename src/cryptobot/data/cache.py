"""Local OHLCV caches so repeated runs do not have to download the same candles."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

import pandas as pd

from cryptobot.data.ohlcv import OHLCV_COLUMNS, read_ohlcv_csv, validate_ohlcv, write_ohlcv_csv
from cryptobot.exceptions import DataError


def symbol_slug(symbol: str) -> str:
    """Turn ``BTC/USDT`` into a filename-safe slug."""
    return symbol.replace("/", "-").replace(":", "-").replace(" ", "")


class OHLCVCache(Protocol):
    """Store and retrieve candles for one exchange, symbol, and timeframe."""

    def load(self, exchange: str, symbol: str, timeframe: str) -> pd.DataFrame | None:
        """Return cached candles, or ``None`` when nothing is stored."""

    def save(self, exchange: str, symbol: str, timeframe: str, data: pd.DataFrame) -> None:
        """Replace the cached series with ``data``."""

    def upsert(self, exchange: str, symbol: str, timeframe: str, data: pd.DataFrame) -> pd.DataFrame:
        """Merge ``data`` into the cache and return the combined series."""


def _merge(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    incoming = validate_ohlcv(incoming)
    if existing is None or existing.empty:
        return incoming
    combined = pd.concat([validate_ohlcv(existing), incoming])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return validate_ohlcv(combined)


class CSVCache:
    """One CSV file per exchange, symbol, and timeframe under ``root``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, exchange: str, symbol: str, timeframe: str) -> Path:
        return self.root / exchange / symbol_slug(symbol) / f"{timeframe}.csv"

    def load(self, exchange: str, symbol: str, timeframe: str) -> pd.DataFrame | None:
        path = self.path_for(exchange, symbol, timeframe)
        if not path.is_file():
            return None
        return read_ohlcv_csv(path)

    def save(self, exchange: str, symbol: str, timeframe: str, data: pd.DataFrame) -> None:
        write_ohlcv_csv(data, self.path_for(exchange, symbol, timeframe))

    def upsert(self, exchange: str, symbol: str, timeframe: str, data: pd.DataFrame) -> pd.DataFrame:
        merged = _merge(self.load(exchange, symbol, timeframe), data)
        self.save(exchange, symbol, timeframe, merged)
        return merged


class SQLiteCache:
    """A single SQLite file holding every cached series."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ohlcv (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (exchange, symbol, timeframe, timestamp)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def load(self, exchange: str, symbol: str, timeframe: str) -> pd.DataFrame | None:
        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM ohlcv
            WHERE exchange = ? AND symbol = ? AND timeframe = ?
            ORDER BY timestamp
        """
        with self._connect() as connection:
            rows = connection.execute(query, (exchange, symbol, timeframe)).fetchall()
        if not rows:
            return None
        frame = pd.DataFrame(rows, columns=["timestamp_ms", *OHLCV_COLUMNS])
        frame.index = pd.to_datetime(frame.pop("timestamp_ms"), unit="ms", utc=True)
        frame.index.name = "timestamp"
        return validate_ohlcv(frame)

    def save(self, exchange: str, symbol: str, timeframe: str, data: pd.DataFrame) -> None:
        frame = validate_ohlcv(data)
        records = []
        for stamp, row in frame.iterrows():
            records.append(
                (
                    exchange,
                    symbol,
                    timeframe,
                    int(pd.Timestamp(stamp).value // 1_000_000),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"]),
                )
            )
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM ohlcv WHERE exchange = ? AND symbol = ? AND timeframe = ?",
                (exchange, symbol, timeframe),
            )
            connection.executemany(
                """
                INSERT INTO ohlcv (
                    exchange, symbol, timeframe, timestamp, open, high, low, close, volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

    def upsert(self, exchange: str, symbol: str, timeframe: str, data: pd.DataFrame) -> pd.DataFrame:
        merged = _merge(self.load(exchange, symbol, timeframe), data)
        self.save(exchange, symbol, timeframe, merged)
        return merged


def build_cache(backend: str, cache_dir: str | Path, sqlite_path: str | Path) -> OHLCVCache:
    """Construct the cache named by configuration (``csv`` or ``sqlite``)."""
    if backend == "csv":
        return CSVCache(cache_dir)
    if backend == "sqlite":
        return SQLiteCache(sqlite_path)
    raise DataError(f"Backend de caché desconocido: {backend!r}. Usa csv o sqlite.")
