from datetime import date
import json

import pandas as pd

from tradescope.data.collection_manifest import (
    write_config_collection_manifest,
    write_store_update_manifest,
)
from tradescope.data.alpha_vantage import ListingStatusRecord, parse_listing_status_csv
from tradescope.data.quality import build_quality_report
from tradescope.data.maintenance import (
    fetch_configured_components,
    update_stored_dataset,
    update_symbols_dataset,
)
from tradescope.config import load_config
from tradescope.data.store import MarketDataStore
from tradescope.data.symbol_mapping import SymbolMap, yfinance_symbol_candidates
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
    security_master = store.security_master.read()
    assert security_master.loc[0, "symbol"] == "SPY"
    assert security_master.loc[0, "status"] == "available"
    assert security_master.loc[0, "history_start"] == "2024-01-02"
    assert security_master.loc[0, "history_end"] == "2024-01-02"


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
    security_master = store.security_master.read()
    assert security_master.loc[0, "status"] == "unavailable"
    assert security_master.loc[0, "reason"] == "no rows"

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


def test_security_master_marks_short_history_as_historical(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    data = pd.DataFrame(
        {"close": [1.0], "symbol": "OLD"},
        index=pd.DatetimeIndex(["2020-01-02"], name="timestamp"),
    )

    store.write_processed("yfinance", "OLD", date(2010, 1, 1), date(2026, 1, 1), "1d", data)
    security_master = store.security_master.read()

    assert security_master.loc[0, "symbol"] == "OLD"
    assert security_master.loc[0, "status"] == "historical"
    assert security_master.loc[0, "history_start"] == "2020-01-02"
    assert security_master.loc[0, "history_end"] == "2020-01-02"


def test_security_master_upserts_alpha_vantage_listing_status(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")

    count = store.security_master.upsert_listing_status(
        [
            ListingStatusRecord(
                symbol="OLD",
                name="Old Co",
                exchange="NYSE",
                asset_type="Stock",
                ipo_date="2000-01-01",
                delisting_date="2020-01-01",
                status="delisted",
                source="alpha_vantage_listing_status",
                as_of_date="2021-01-01",
            )
        ]
    )
    security_master = store.security_master.read()

    assert count == 1
    assert security_master.loc[0, "symbol"] == "OLD"
    assert security_master.loc[0, "status"] == "delisted"
    assert security_master.loc[0, "name"] == "Old Co"
    assert security_master.loc[0, "delisting_date"] == "2020-01-01"
    assert security_master.loc[0, "listing_source"] == "alpha_vantage_listing_status"
    assert store.security_master.symbols(statuses=["delisted"], exchanges=["NYSE"]) == ["OLD"]
    assert store.security_master.symbols(statuses=["delisted"], offset=1) == []


def test_security_master_copies_listing_metadata_to_price_history(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status(
        [
            ListingStatusRecord(
                symbol="OLD",
                name="Old Co",
                exchange="NYSE",
                asset_type="Stock",
                ipo_date="2000-01-01",
                delisting_date="2020-01-01",
                status="delisted",
                source="alpha_vantage_listing_status",
                as_of_date="2026-05-17",
            )
        ]
    )

    store.write_processed(
        "yfinance",
        "OLD",
        date(2010, 1, 1),
        date(2026, 1, 1),
        "1d",
        pd.DataFrame(
            {"close": [1.0], "symbol": "OLD"},
            index=pd.DatetimeIndex(["2019-12-31"], name="timestamp"),
        ),
    )

    security_master = store.security_master.read()
    row = security_master[
        (security_master["provider"] == "yfinance") & (security_master["symbol"] == "OLD")
    ].iloc[0]
    assert row["status"] == "historical"
    assert row["name"] == "Old Co"
    assert row["exchange"] == "NYSE"
    assert row["asset_type"] == "Stock"
    assert row["ipo_date"] == "2000-01-01"
    assert row["delisting_date"] == "2020-01-01"
    assert row["listing_source"] == "alpha_vantage_listing_status"
    assert row["listing_as_of_date"] == "2026-05-17"


def test_security_master_copies_listing_metadata_to_unavailable_symbols(tmp_path) -> None:
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status(
        [
            ListingStatusRecord(
                symbol="BAD",
                name="Bad Co",
                exchange="NASDAQ",
                asset_type="Stock",
                ipo_date="2001-01-01",
                delisting_date="2021-01-01",
                status="delisted",
                source="alpha_vantage_listing_status",
                as_of_date="2026-05-17",
            )
        ]
    )

    store.mark_unavailable(
        "yfinance",
        "BAD",
        date(2010, 1, 1),
        date(2026, 1, 1),
        "1d",
        "no rows",
    )

    security_master = store.security_master.read()
    row = security_master[
        (security_master["provider"] == "yfinance") & (security_master["symbol"] == "BAD")
    ].iloc[0]
    assert row["status"] == "unavailable"
    assert row["name"] == "Bad Co"
    assert row["exchange"] == "NASDAQ"
    assert row["asset_type"] == "Stock"
    assert row["ipo_date"] == "2001-01-01"
    assert row["delisting_date"] == "2021-01-01"
    assert row["listing_source"] == "alpha_vantage_listing_status"
    assert row["listing_as_of_date"] == "2026-05-17"
    assert row["reason"] == "no rows"


def test_parse_alpha_vantage_listing_status_csv() -> None:
    records = parse_listing_status_csv(
        "\n".join(
            [
                "symbol,name,exchange,assetType,ipoDate,delistingDate,status",
                "ABC,ABC Corp,NYSE,Stock,2010-01-01,null,Active",
                "XYZ,XYZ Corp,NASDAQ,Stock,2000-01-01,2020-01-01,Delisted",
            ]
        ),
        state="active",
    )

    assert [record.symbol for record in records] == ["ABC", "XYZ"]
    assert records[0].status == "Active"
    assert records[0].delisting_date is None
    assert records[1].delisting_date == "2020-01-01"


def test_yfinance_symbol_candidates_include_common_provider_variants() -> None:
    assert yfinance_symbol_candidates("BRK.B") == ["BRK.B", "BRK-B"]
    assert yfinance_symbol_candidates("AAC-W") == ["AAC-W", "AAC-WT"]
    assert yfinance_symbol_candidates("AAC-U") == ["AAC-U", "AAC-UN"]


def test_symbol_map_upsert_stores_custom_status(tmp_path) -> None:
    symbol_map = SymbolMap(tmp_path / "mappings.parquet")
    symbol_map.upsert("TICKER", "yfinance", "TICKER-A", status="inactive", reason="delisted")

    frame = symbol_map.read()
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_symbol"] == "TICKER"
    assert row["provider_symbol"] == "TICKER-A"
    assert row["status"] == "inactive"
    assert row["reason"] == "delisted"


def test_symbol_map_upsert_active_preserves_backward_compat(tmp_path) -> None:
    symbol_map = SymbolMap(tmp_path / "mappings.parquet")
    symbol_map.upsert_active("BRK.B", "yfinance", "BRK-B", reason="dot fix")

    frame = symbol_map.read()
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["status"] == "active"
    assert row["reason"] == "dot fix"


def test_symbol_map_import_csv_adds_mappings(tmp_path) -> None:
    csv_path = tmp_path / "mappings.csv"
    csv_path.write_text("source_symbol,provider,provider_symbol,status,reason\nBRK.B,yfinance,BRK-B,active,manual\n")
    symbol_map = SymbolMap(tmp_path / "mappings.parquet")

    count = symbol_map.import_csv(csv_path)

    assert count == 1
    frame = symbol_map.read()
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_symbol"] == "BRK.B"
    assert row["provider_symbol"] == "BRK-B"
    assert row["status"] == "active"
    assert row["reason"] == "manual"


def test_symbol_map_import_csv_defaults_optional_columns(tmp_path) -> None:
    csv_path = tmp_path / "mappings.csv"
    csv_path.write_text("source_symbol,provider,provider_symbol\nAAC-W,yfinance,AAC-WT\n")
    symbol_map = SymbolMap(tmp_path / "mappings.parquet")

    count = symbol_map.import_csv(csv_path)

    assert count == 1
    row = symbol_map.read().iloc[0]
    assert row["status"] == "active"
    assert row["source"] == "security_master"
    assert pd.isna(row["reason"])


def test_symbol_map_import_csv_raises_on_missing_columns(tmp_path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("source_symbol,provider\nBRK.B,yfinance\n")
    symbol_map = SymbolMap(tmp_path / "mappings.parquet")

    import pytest
    with pytest.raises(ValueError, match="provider_symbol"):
        symbol_map.import_csv(csv_path)


def test_symbol_map_import_csv_merges_with_existing(tmp_path) -> None:
    symbol_map = SymbolMap(tmp_path / "mappings.parquet")
    symbol_map.upsert_active("AAPL", "yfinance", "AAPL")
    csv_path = tmp_path / "mappings.csv"
    csv_path.write_text("source_symbol,provider,provider_symbol\nBRK.B,yfinance,BRK-B\n")

    symbol_map.import_csv(csv_path)

    frame = symbol_map.read()
    assert len(frame) == 2
    assert set(frame["source_symbol"]) == {"AAPL", "BRK.B"}


def test_update_symbols_dataset_fetches_arbitrary_security_master_symbols(tmp_path, monkeypatch) -> None:
    def fake_fetch_raw(_self, symbols, start, end, interval):
        assert symbols == ["SPY"]
        assert start == date(2024, 1, 1)
        assert end == date(2024, 1, 3)
        assert interval == "1d"
        return {
            "SPY": pd.DataFrame(
                {
                    "Open": [1.0, 2.0],
                    "High": [2.0, 3.0],
                    "Low": [0.5, 1.5],
                    "Close": [1.5, 2.5],
                    "Adj Close": [1.5, 2.5],
                    "Volume": [100, 100],
                },
                index=pd.date_range("2024-01-01", "2024-01-02", freq="D", name="timestamp"),
            )
        }

    monkeypatch.setattr("tradescope.data.yfinance_provider.YFinanceProvider.fetch_raw", fake_fetch_raw)

    _config, counts = update_symbols_dataset(
        symbols=["SPY"],
        start=date(2024, 1, 1),
        end=date(2024, 1, 3),
        interval="1d",
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        component_dir=tmp_path / "components",
        components=["ohlcv"],
    )

    assert counts == {"ohlcv_symbols": 1, "component_files": 0}


def test_fetch_configured_components_skips_existing_components(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["SPY"]
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"
    config.data.component_dir = tmp_path / "components"
    config.data.components = ["dividends"]
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir, config.data.component_dir)
    store.write_component(
        "yfinance",
        "SPY",
        "dividends",
        pd.DataFrame({"dividends": [1.0]}, index=pd.DatetimeIndex(["2024-01-02"])),
    )

    def fail_fetch_component(_self, _symbol, _component):
        raise AssertionError("existing component should not be fetched")

    monkeypatch.setattr(
        "tradescope.data.yfinance_provider.YFinanceProvider.fetch_component",
        fail_fetch_component,
    )

    assert fetch_configured_components(config) == 0


def test_write_config_collection_manifest_records_run_context(tmp_path) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["SPY"]
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"
    config.data.component_dir = tmp_path / "components"
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir, config.data.component_dir)
    store.write_processed(
        "yfinance",
        "SPY",
        date(2024, 1, 1),
        date(2024, 1, 3),
        "1d",
        pd.DataFrame(
            {"close": [1.0], "symbol": "SPY"},
            index=pd.DatetimeIndex(["2024-01-02"], name="timestamp"),
        ),
    )

    path = write_config_collection_manifest(
        config,
        {"ohlcv_symbols": 1, "component_files": 0},
        manifest_dir=tmp_path / "manifests",
    )
    payload = json.loads(path.read_text())

    assert payload["kind"] == "config"
    assert payload["name"] == config.name
    assert payload["symbols_requested"] == 1
    assert payload["counts"]["ohlcv_symbols"] == 1
    assert payload["security_status_counts"] == {"available": 1}


def test_write_store_update_manifest_records_update_context(tmp_path) -> None:
    path = write_store_update_manifest(
        tmp_path / "raw",
        tmp_path / "processed",
        {"ohlcv_symbols": 1, "skipped_symbols": 2},
        provider="yfinance",
        interval="1d",
        end=date(2026, 1, 1),
        manifest_dir=tmp_path / "manifests",
    )
    payload = json.loads(path.read_text())

    assert payload["kind"] == "store_update"
    assert payload["provider"] == "yfinance"
    assert payload["interval"] == "1d"
    assert payload["end"] == "2026-01-01"
    assert payload["counts"] == {"ohlcv_symbols": 1, "skipped_symbols": 2}


def test_expand_yfinance_research_bundle_includes_advanced_components() -> None:
    components = expand_yfinance_components(["ohlcv", "research_bundle"])

    assert "ohlcv" in components
    assert "actions" not in components
    assert "dividends" in components
    assert "splits" in components
    assert "capital_gains" in components
    assert "income_stmt" in components
    assert "quarterly_balance_sheet" in components
    assert "ttm_cash_flow" in components
    assert "earnings_history" in components
    assert "earnings_estimate" not in components
    assert "growth_estimates" not in components
    assert "recommendations" not in components
    assert "institutional_holders" not in components
    assert "news" not in components
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
