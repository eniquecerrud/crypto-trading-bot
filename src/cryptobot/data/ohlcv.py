"""OHLCV frames, CSV persistence, and validation.

A canonical frame has a UTC ``DatetimeIndex`` named ``timestamp`` and the
columns ``open``, ``high``, ``low``, ``close``, and ``volume``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from cryptobot.exceptions import DataError

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_TIMEFRAME_RE = re.compile(r"^(\d+)([mhdw])$")
_TIMEFRAME_SECONDS = {"m": 60, "h": 3600, "d": 86_400, "w": 604_800}
_COLUMN_ALIASES = {
    "timestamp": "timestamp",
    "time": "timestamp",
    "date": "timestamp",
    "datetime": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "vol": "volume",
}


def timeframe_to_seconds(timeframe: str) -> int:
    """Convert a ccxt-style timeframe such as ``1h`` or ``15m`` to seconds."""
    match = _TIMEFRAME_RE.fullmatch(timeframe.strip().lower())
    if match is None:
        raise DataError(f"Temporalidad no soportada: {timeframe!r}. Usa valores como 1m, 5m, 1h o 1d.")
    count = int(match.group(1))
    if count <= 0:
        raise DataError(f"Temporalidad no soportada: {timeframe!r}.")
    return count * _TIMEFRAME_SECONDS[match.group(2)]


def require_ohlcv(data: pd.DataFrame) -> None:
    """Raise ``DataError`` unless ``data`` matches the canonical OHLCV contract."""
    if not isinstance(data.index, pd.DatetimeIndex):
        raise DataError("El índice de las velas debe ser un DatetimeIndex (timestamp).")
    missing = [column for column in OHLCV_COLUMNS if column not in data.columns]
    if missing:
        raise DataError(f"Faltan columnas OHLCV: {', '.join(missing)}.")
    if data.empty:
        raise DataError("No hay velas para procesar.")


def validate_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted copy of ``data`` or raise ``DataError`` if it is unusable.

    High must cover the bar and low must sit under the bar. Prices cannot be
    missing or negative, and timestamps must be unique and increasing.
    """
    require_ohlcv(data)
    frame = data.loc[:, list(OHLCV_COLUMNS)].copy()
    frame.index = pd.DatetimeIndex(frame.index)
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")
    frame.index.name = "timestamp"
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise DataError("Hay timestamps duplicados en las velas.")
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    if numeric[list(OHLCV_COLUMNS)].isna().any().any():
        raise DataError("Hay valores no numéricos o vacíos en OHLCV.")
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataError("Los precios deben ser positivos.")
    if (numeric["volume"] < 0).any():
        raise DataError("El volumen no puede ser negativo.")
    tolerance = 1e-9
    upper = numeric[["open", "close", "low"]].max(axis=1)
    lower = numeric[["open", "close", "high"]].min(axis=1)
    if (numeric["high"] + tolerance < upper).any():
        raise DataError("Hay velas cuyo high está por debajo de open, close o low.")
    if (numeric["low"] - tolerance > lower).any():
        raise DataError("Hay velas cuyo low está por encima de open, close o high.")
    return numeric


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = {column: _COLUMN_ALIASES.get(str(column).strip().lower(), column) for column in frame.columns}
    frame = frame.rename(columns=renamed)
    if "timestamp" not in frame.columns:
        raise DataError("El CSV debe incluir una columna timestamp, time o date.")
    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise DataError(f"Faltan columnas en el CSV: {', '.join(missing)}.")
    return frame


def _parse_timestamp(values: pd.Series) -> pd.DatetimeIndex:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        # 1e12 separates epoch seconds from epoch milliseconds for modern dates.
        unit = "ms" if float(numeric.max()) >= 1e12 else "s"
        parsed = pd.to_datetime(numeric, unit=unit, utc=True)
    else:
        parsed = pd.to_datetime(values, utc=True, errors="coerce")
    if parsed.isna().any():
        raise DataError("No se pudo interpretar alguna marca de tiempo.")
    return pd.DatetimeIndex(parsed)


def read_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """Load a canonical OHLCV frame from a CSV file. Does not touch the network."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise DataError(f"No existe el CSV de velas: {csv_path}")
    frame = pd.read_csv(csv_path)
    if frame.empty:
        raise DataError(f"El CSV está vacío: {csv_path}")
    frame = _normalize_columns(frame)
    index = _parse_timestamp(frame["timestamp"])
    frame = frame.loc[:, list(OHLCV_COLUMNS)]
    frame.index = index
    return validate_ohlcv(frame)


def write_ohlcv_csv(data: pd.DataFrame, path: str | Path) -> Path:
    """Write ``data`` as CSV with ISO-8601 UTC timestamps."""
    frame = validate_ohlcv(data)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    exported = frame.reset_index()
    exported["timestamp"] = [stamp.isoformat().replace("+00:00", "Z") for stamp in exported["timestamp"]]
    exported.to_csv(destination, index=False)
    return destination


def rows_to_frame(rows: list[list[float]]) -> pd.DataFrame:
    """Build a frame from ccxt-style rows ``[ms, open, high, low, close, volume]``."""
    if not rows:
        raise DataError("El exchange no devolvió velas.")
    frame = pd.DataFrame(rows, columns=["timestamp_ms", *OHLCV_COLUMNS])
    index = pd.to_datetime(frame.pop("timestamp_ms"), unit="ms", utc=True)
    frame.index = pd.DatetimeIndex(index)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return validate_ohlcv(frame)
