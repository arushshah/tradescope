from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from typing import Any

import pandas as pd

from tradescope.data.base import MarketDataProvider
from tradescope.data.validation import validate_ohlcv
from tradescope.exceptions import DataError, NoDataError


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def fetch(
        self,
        symbols: list[str],
        start: date,
        end: date | None,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        return {
            symbol: validate_ohlcv(symbol, normalize_yfinance_frame(symbol, raw))
            for symbol, raw in self.fetch_raw(symbols, start, end, interval).items()
        }

    def fetch_raw(
        self,
        symbols: list[str],
        start: date,
        end: date | None,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise DataError("yfinance is required for provider 'yfinance'") from exc

        data_by_symbol: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                raw = yf.download(
                    symbol,
                    start=start.isoformat(),
                    end=end.isoformat() if end else None,
                    interval=interval,
                    auto_adjust=False,
                    progress=False,
                    group_by="column",
                )
            if raw.empty:
                raise NoDataError(f"{symbol}: yfinance returned no rows")
            raw.index = pd.to_datetime(raw.index)
            raw.index.name = "timestamp"
            data_by_symbol[symbol] = raw
        return data_by_symbol

    def normalize(self, symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
        return normalize_yfinance_frame(symbol, raw)

    def fetch_component(self, symbol: str, component: str) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise DataError("yfinance is required for provider 'yfinance'") from exc

        component = component.lower()
        ticker = yf.Ticker(symbol)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            if component == "actions":
                data = ticker.actions
            elif component == "dividends":
                data = ticker.dividends
            elif component == "splits":
                data = ticker.splits
            elif component == "capital_gains":
                data = ticker.capital_gains
            elif component in {"info", "fast_info"}:
                data = dict(ticker.fast_info) if component == "fast_info" else ticker.get_info()
            else:
                raise DataError(f"unsupported yfinance component: {component}")
        return normalize_component_frame(symbol, component, data)


def normalize_yfinance_frame(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        raise NoDataError(f"{symbol}: yfinance returned no rows")

    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    frame = frame.rename(columns=rename_map)
    if "adj_close" not in frame.columns and "close" in frame.columns:
        frame["adj_close"] = frame["close"]

    frame.index = pd.to_datetime(frame.index)
    frame.index.name = "timestamp"
    frame["symbol"] = symbol
    frame["source"] = "yfinance"
    return frame[["open", "high", "low", "close", "adj_close", "volume", "symbol", "source"]]


def normalize_component_frame(symbol: str, component: str, data: Any) -> pd.DataFrame:
    if isinstance(data, pd.Series):
        frame = data.to_frame(name=component)
    elif isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, dict):
        frame = pd.DataFrame([flatten_mapping(data)])
    else:
        frame = pd.DataFrame([{"value": data}])

    if frame.empty:
        frame = pd.DataFrame(columns=["symbol", "source", "component"])
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.RangeIndex(len(frame))
    else:
        frame.index = pd.to_datetime(frame.index)
        frame.index.name = "timestamp"
    frame["symbol"] = symbol.upper()
    frame["source"] = "yfinance"
    frame["component"] = component
    return frame


def flatten_mapping(data: dict[str, Any]) -> dict[str, Any]:
    flattened = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            flattened[key] = value
        else:
            flattened[key] = str(value)
    return flattened
