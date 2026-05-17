from datetime import date

import pandas as pd

from tradescope.data.quality import build_quality_report
from tradescope.data.maintenance import update_stored_dataset
from tradescope.data.store import MarketDataStore
from tradescope.data.yfinance_provider import (
    expand_yfinance_components,
    normalize_component_frame,
    normalize_yfinance_frame,
)


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


def test_update_stored_dataset_extends_existing_processed_data(tmp_path, monkeypatch) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    index = pd.date_range("2024-01-01", "2024-01-02", freq="D", name="timestamp")
    existing = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "adj_close": [1.5, 2.5],
            "volume": [100, 100],
            "symbol": "SPY",
            "source": "test",
        },
        index=index,
    )
    store.write_processed("yfinance", "SPY", date(2024, 1, 1), date(2024, 1, 3), "1d", existing)

    def fake_fetch_raw(_self, symbols, start, end, interval):
        assert symbols == ["SPY"]
        assert start == date(2024, 1, 3)
        assert end == date(2024, 1, 5)
        assert interval == "1d"
        raw_index = pd.date_range("2024-01-03", "2024-01-04", freq="D", name="timestamp")
        return {
            "SPY": pd.DataFrame(
                {
                    "Open": [3.0, 4.0],
                    "High": [4.0, 5.0],
                    "Low": [2.5, 3.5],
                    "Close": [3.5, 4.5],
                    "Adj Close": [3.5, 4.5],
                    "Volume": [100, 100],
                },
                index=raw_index,
            )
        }

    monkeypatch.setattr("tradescope.data.yfinance_provider.YFinanceProvider.fetch_raw", fake_fetch_raw)

    counts = update_stored_dataset(
        tmp_path / "raw",
        tmp_path / "processed",
        end=date(2024, 1, 5),
    )
    updated = store.read_processed("yfinance", "SPY", date(2024, 1, 1), date(2024, 1, 5), "1d")

    assert counts == {"ohlcv_symbols": 1, "skipped_symbols": 0}
    assert updated is not None
    assert list(updated.index) == list(pd.date_range("2024-01-01", "2024-01-04", freq="D"))


def test_expand_yfinance_research_bundle_includes_advanced_components() -> None:
    components = expand_yfinance_components(["ohlcv", "research_bundle"])

    assert "ohlcv" in components
    assert "income_stmt" in components
    assert "quarterly_balance_sheet" in components
    assert "earnings_estimate" in components
    assert "institutional_holders" in components
    assert "news" in components
    assert "option_chains" not in components


def test_normalize_component_frame_handles_list_payloads() -> None:
    frame = normalize_component_frame(
        "SPY",
        "news",
        [{"title": "Example", "nested": {"publisher": "Test"}}],
    )

    assert frame.loc[0, "title"] == "Example"
    assert frame.loc[0, "nested"] == "{'publisher': 'Test'}"
    assert frame.loc[0, "symbol"] == "SPY"
    assert frame.loc[0, "component"] == "news"


def test_build_quality_report_warns_on_missing_close() -> None:
    data = pd.DataFrame(
        {"close": [1.0, None]},
        index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="timestamp"),
    )

    report = build_quality_report("SPY", data)

    assert report.status == "warning"
    assert report.missing_close == 1
