"""CSV, SQLite cache, and the offline-friendly downloader."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from cryptobot.data.cache import CSVCache, SQLiteCache
from cryptobot.data.fetcher import drop_incomplete, fetch_ohlcv
from cryptobot.data.ohlcv import read_ohlcv_csv, timeframe_to_seconds, write_ohlcv_csv
from cryptobot.exceptions import DataError
from tests.conftest import flat_bars, make_bars


def test_csv_roundtrip_accepts_epoch_milliseconds(tmp_path) -> None:
    frame = flat_bars(4, price=20)
    path = write_ohlcv_csv(frame, tmp_path / "candles.csv")
    loaded = read_ohlcv_csv(path)
    assert loaded.index.equals(frame.index)
    assert loaded["close"].tolist() == [20, 20, 20, 20]

    raw = pd.read_csv(path)
    millis = (pd.to_datetime(raw["timestamp"], utc=True).astype("int64") // 1_000_000).astype(str)
    raw["timestamp"] = millis
    millis_path = tmp_path / "millis.csv"
    raw.to_csv(millis_path, index=False)
    from_millis = read_ohlcv_csv(millis_path)
    assert from_millis.index.equals(frame.index)


def test_invalid_candle_and_duplicate_timestamp_are_rejected(tmp_path) -> None:
    broken = make_bars([(100, 90, 80, 100)])
    with pytest.raises(DataError):
        write_ohlcv_csv(broken, tmp_path / "bad.csv")
    frame = flat_bars(2)
    path = write_ohlcv_csv(frame, tmp_path / "dup.csv")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    path.write_text("\n".join([lines[0], lines[1], lines[1]]) + "\n", encoding="utf-8")
    with pytest.raises(DataError):
        read_ohlcv_csv(path)


def test_csv_and_sqlite_caches_upsert(tmp_path) -> None:
    first = flat_bars(2, price=10)
    second = flat_bars(2, price=12, start="2024-01-01T02:00:00Z")
    for cache in (CSVCache(tmp_path / "csv"), SQLiteCache(tmp_path / "ohlcv.sqlite")):
        cache.save("binance", "BTC/USDT", "1h", first)
        merged = cache.upsert("binance", "BTC/USDT", "1h", second)
        assert len(merged) == 4
        again = cache.load("binance", "BTC/USDT", "1h")
        assert again is not None
        assert len(again) == 4
        assert again["close"].iloc[-1] == 12


class _Pages:
    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows
        self.calls = 0

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None, limit: int | None = None):
        self.calls += 1
        data = self.rows if since is None else [row for row in self.rows if row[0] >= since]
        if limit is not None:
            data = data[:limit]
        return data


def test_fetch_paginates_without_a_network() -> None:
    start = int(pd.Timestamp("2024-01-01T00:00:00Z").value // 1_000_000)
    hour = 3_600_000
    rows = [[start + i * hour, 10, 11, 9, 10.5, 1] for i in range(5)]
    exchange = _Pages(rows)
    frame = fetch_ohlcv(exchange, "BTC/USDT", "1h", limit=2)
    assert len(frame) == 5
    assert exchange.calls >= 3
    assert frame["close"].iloc[-1] == 10.5


def test_drop_incomplete_removes_the_forming_bar() -> None:
    frame = flat_bars(2)
    opened = frame.index[-1].to_pydatetime()
    assert len(drop_incomplete(frame, "1h", opened + timedelta(minutes=30))) == 1
    assert len(drop_incomplete(frame, "1h", opened + timedelta(hours=1))) == 2


def test_timeframe_parser() -> None:
    assert timeframe_to_seconds("15m") == 900
    assert timeframe_to_seconds("4h") == 14_400
    assert timeframe_to_seconds("1d") == 86_400
    with pytest.raises(DataError):
        timeframe_to_seconds("2x")


def test_sample_file_is_offline_and_valid() -> None:
    frame = read_ohlcv_csv("data/sample/BTC-USDT-1h.csv")
    assert len(frame) >= 200
    assert frame.index.tz is not None
