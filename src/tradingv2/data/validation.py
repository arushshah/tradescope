from __future__ import annotations

import pandas as pd

from tradingv2.exceptions import DataError

REQUIRED_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


def validate_ohlcv(symbol: str, data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        raise DataError(f"{symbol}: no data returned")

    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise DataError(f"{symbol}: missing required columns: {', '.join(missing)}")

    cleaned = data.copy()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    cleaned = cleaned.sort_index()

    if not cleaned.index.is_monotonic_increasing:
        raise DataError(f"{symbol}: timestamp index is not monotonic")

    price_columns = ["open", "high", "low", "close", "adj_close"]
    if cleaned[price_columns].isna().all(axis=None):
        raise DataError(f"{symbol}: price data is entirely empty")

    cleaned[price_columns] = cleaned[price_columns].ffill()
    cleaned["volume"] = cleaned["volume"].fillna(0)
    return cleaned

