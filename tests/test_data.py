from datetime import date

import pandas as pd

from tradingv2.data.quality import build_quality_report
from tradingv2.data.store import MarketDataStore
from tradingv2.data.yfinance_provider import normalize_yfinance_frame


def test_normalize_yfinance_frame() -> None:
    raw = pd.DataFrame(
        {
            "Open": [1.0],
            "High": [2.0],
            "Low": [0.5],
            "Close": [1.5],
            "Adj Close": [1.4],
            "Volume": [100],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )

    normalized = normalize_yfinance_frame("SPY", raw)

    assert list(normalized.columns) == [
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "symbol",
        "source",
    ]
    assert normalized.loc[pd.Timestamp("2024-01-02"), "symbol"] == "SPY"


def test_market_data_store_writes_processed_parquet(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    data = pd.DataFrame(
        {"close": [1.0], "symbol": ["SPY"]},
        index=pd.DatetimeIndex(["2024-01-02"], name="timestamp"),
    )

    path = store.write_processed("yfinance", "SPY", date(2024, 1, 1), date(2024, 1, 3), "1d", data)
    processed = store.read_processed("yfinance", "SPY", date(2024, 1, 1), date(2024, 1, 3), "1d")

    assert path.suffix == ".parquet"
    assert processed is not None
    assert processed.loc[pd.Timestamp("2024-01-02"), "close"] == 1.0


def test_market_data_store_reads_covering_processed_range(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    index = pd.date_range("2024-01-01", "2024-01-05", freq="D", name="timestamp")
    data = pd.DataFrame({"close": range(len(index)), "symbol": "SPY"}, index=index)
    store.write_processed("yfinance", "SPY", date(2024, 1, 1), date(2024, 1, 6), "1d", data)

    processed = store.read_processed("yfinance", "SPY", date(2024, 1, 2), date(2024, 1, 4), "1d")

    assert processed is not None
    assert list(processed.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]


def test_market_data_store_lists_and_clears_entries(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    data = pd.DataFrame(
        {"close": [1.0, 2.0], "symbol": ["SPY", "SPY"]},
        index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="timestamp"),
    )
    store.write_raw("yfinance", "SPY", date(2024, 1, 1), date(2024, 1, 4), "1d", data)
    store.write_processed("yfinance", "SPY", date(2024, 1, 1), date(2024, 1, 4), "1d", data)

    entries = store.list_entries(symbol="SPY")
    removed = store.clear(layer="processed", symbol="SPY")

    assert len(entries) == 2
    assert {entry.layer for entry in entries} == {"raw", "processed"}
    assert all(entry.symbol == "SPY" for entry in entries)
    assert all(entry.rows == 2 for entry in entries)
    assert len(removed) == 1
    assert [entry.layer for entry in store.list_entries(symbol="SPY")] == ["raw"]


def test_market_data_store_marks_unavailable_symbols(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.mark_unavailable(
        "yfinance",
        "AACBR",
        date(2015, 1, 1),
        date(2026, 1, 1),
        "1d",
        "no rows",
    )

    entry = store.unavailable_entry(
        "yfinance",
        "AACBR",
        date(2015, 1, 1),
        date(2026, 1, 1),
        "1d",
    )

    assert entry is not None
    assert entry.symbol == "AACBR"
    assert store.list_unavailable()[0].reason == "no rows"

    different_window = store.unavailable_entry(
        "yfinance",
        "AACBR",
        date(2020, 1, 1),
        date(2021, 1, 1),
        "1d",
    )

    assert different_window is None


def test_build_quality_report_warns_on_missing_close() -> None:
    data = pd.DataFrame(
        {"close": [1.0, None]},
        index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="timestamp"),
    )

    report = build_quality_report("SPY", data)

    assert report.status == "warning"
    assert report.missing_close == 1
