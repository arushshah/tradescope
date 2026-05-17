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
    _coverage_label,
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


def test_coverage_label_ok_when_data_covers_full_window() -> None:
    label = _coverage_label(
        actual_start=date(2010, 1, 1),
        actual_end=date(2025, 12, 31),
        requested_start=date(2010, 1, 1),
        expected_last=date(2025, 12, 31),
        ipo_date=None,
        delisting_date=None,
    )
    assert label == "ok"


def test_coverage_label_partial_when_start_missing_and_no_ipo() -> None:
    label = _coverage_label(
        actual_start=date(2015, 1, 1),
        actual_end=date(2025, 12, 31),
        requested_start=date(2010, 1, 1),
        expected_last=date(2025, 12, 31),
        ipo_date=None,
        delisting_date=None,
    )
    assert label == "partial"


def test_coverage_label_partial_ipo_when_ipo_after_requested_start() -> None:
    label = _coverage_label(
        actual_start=date(2015, 1, 5),
        actual_end=date(2025, 12, 31),
        requested_start=date(2010, 1, 1),
        expected_last=date(2025, 12, 31),
        ipo_date=date(2015, 1, 1),
        delisting_date=None,
    )
    assert label == "partial_ipo"


def test_coverage_label_partial_delisted_when_delisting_before_expected_end() -> None:
    label = _coverage_label(
        actual_start=date(2010, 1, 1),
        actual_end=date(2020, 6, 1),
        requested_start=date(2010, 1, 1),
        expected_last=date(2025, 12, 31),
        ipo_date=None,
        delisting_date=date(2020, 6, 1),
    )
    assert label == "partial_delisted"


def test_coverage_label_partial_ipo_when_both_ipo_and_delisting_clip() -> None:
    # Both ends of the requested range are clipped by listing events; both are explained.
    # "partial_ipo" is the label (IPO takes precedence when both gaps are explained).
    label = _coverage_label(
        actual_start=date(2015, 1, 1),
        actual_end=date(2020, 6, 1),
        requested_start=date(2010, 1, 1),
        expected_last=date(2025, 12, 31),
        ipo_date=date(2015, 1, 1),
        delisting_date=date(2020, 6, 1),
    )
    assert label == "partial_ipo"


def test_coverage_label_partial_ipo_when_ipo_before_requested_start() -> None:
    # IPO is before the requested start → no clipping, gap is unexplained.
    label = _coverage_label(
        actual_start=date(2012, 1, 1),
        actual_end=date(2025, 12, 31),
        requested_start=date(2010, 1, 1),
        expected_last=date(2025, 12, 31),
        ipo_date=date(2008, 1, 1),
        delisting_date=None,
    )
    assert label == "partial"


def test_audit_dataset_labels_ipo_partial_as_valid(tmp_path) -> None:
    from tradescope.data.alpha_vantage import ListingStatusRecord
    from tradescope.data.maintenance import audit_dataset
    from tradescope.config import BacktestConfig, DataConfig, PortfolioConfig, ResultsConfig, StrategyConfig

    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status([
        ListingStatusRecord(
            symbol="NEWCO",
            name="NewCo",
            exchange="NYSE",
            asset_type="Stock",
            ipo_date="2015-01-01",
            delisting_date=None,
            status="Active",
            source="test",
            as_of_date="2026-01-01",
        )
    ])

    # Data only available from IPO date — normal for a recent IPO
    index = pd.date_range("2015-01-01", "2024-12-31", freq="D", name="timestamp")
    close = pd.Series(range(100, 100 + len(index)), index=index, dtype=float)
    frame = pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                          "adj_close": close, "volume": 1000, "symbol": "NEWCO", "source": "test"}, index=index)
    store.write_processed("yfinance", "NEWCO", date(2010, 1, 1), date(2025, 1, 1), "1d", frame)

    config = BacktestConfig(
        name="test",
        symbols=["NEWCO"],
        start=date(2010, 1, 1),
        end=date(2025, 1, 1),
        interval="1d",
        data=DataConfig(
            provider="yfinance",
            raw_dir=tmp_path / "raw",
            processed_dir=tmp_path / "processed",
            coverage_start=None,
            coverage_end=None,
        ),
        strategy=StrategyConfig(name="buy_hold"),
        portfolio=PortfolioConfig(benchmark=None),
        results=ResultsConfig(save_trades=False, save_equity_curve=False, save_plots=False),
    )
    rows = audit_dataset(config)

    assert len(rows) == 1
    assert rows[0].coverage == "partial_ipo"


def test_audit_dataset_labels_delisting_partial_as_valid(tmp_path) -> None:
    from tradescope.data.alpha_vantage import ListingStatusRecord
    from tradescope.data.maintenance import audit_dataset
    from tradescope.config import BacktestConfig, DataConfig, PortfolioConfig, ResultsConfig, StrategyConfig

    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status([
        ListingStatusRecord(
            symbol="OLDCO",
            name="OldCo",
            exchange="NYSE",
            asset_type="Stock",
            ipo_date=None,
            delisting_date="2020-06-01",
            status="Delisted",
            source="test",
            as_of_date="2026-01-01",
        )
    ])

    # Data ends at delisting date
    index = pd.date_range("2010-01-01", "2020-06-01", freq="D", name="timestamp")
    close = pd.Series(range(100, 100 + len(index)), index=index, dtype=float)
    frame = pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                          "adj_close": close, "volume": 1000, "symbol": "OLDCO", "source": "test"}, index=index)
    store.write_processed("yfinance", "OLDCO", date(2010, 1, 1), date(2025, 1, 1), "1d", frame)

    config = BacktestConfig(
        name="test",
        symbols=["OLDCO"],
        start=date(2010, 1, 1),
        end=date(2025, 1, 1),
        interval="1d",
        data=DataConfig(
            provider="yfinance",
            raw_dir=tmp_path / "raw",
            processed_dir=tmp_path / "processed",
            coverage_start=None,
            coverage_end=None,
        ),
        strategy=StrategyConfig(name="buy_hold"),
        portfolio=PortfolioConfig(benchmark=None),
        results=ResultsConfig(save_trades=False, save_equity_curve=False, save_plots=False),
    )
    rows = audit_dataset(config)

    assert len(rows) == 1
    assert rows[0].coverage == "partial_delisted"


def test_audit_dataset_flags_unexplained_partial_as_repair_needed(tmp_path) -> None:
    from tradescope.data.maintenance import audit_dataset, symbols_needing_repair
    from tradescope.config import BacktestConfig, DataConfig, PortfolioConfig, ResultsConfig, StrategyConfig

    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    # No listing metadata — gap has no IPO/delisting explanation
    index = pd.date_range("2015-01-01", "2024-12-31", freq="D", name="timestamp")
    close = pd.Series(range(100, 100 + len(index)), index=index, dtype=float)
    frame = pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                          "adj_close": close, "volume": 1000, "symbol": "GAPPY", "source": "test"}, index=index)
    store.write_processed("yfinance", "GAPPY", date(2010, 1, 1), date(2025, 1, 1), "1d", frame)

    config = BacktestConfig(
        name="test",
        symbols=["GAPPY"],
        start=date(2010, 1, 1),
        end=date(2025, 1, 1),
        interval="1d",
        data=DataConfig(
            provider="yfinance",
            raw_dir=tmp_path / "raw",
            processed_dir=tmp_path / "processed",
            coverage_start=None,
            coverage_end=None,
        ),
        strategy=StrategyConfig(name="buy_hold"),
        portfolio=PortfolioConfig(benchmark=None),
        results=ResultsConfig(save_trades=False, save_equity_curve=False, save_plots=False),
    )
    rows = audit_dataset(config)

    assert rows[0].coverage == "partial"
    assert "GAPPY" in symbols_needing_repair(rows)


def test_symbols_needing_repair_excludes_valid_partials() -> None:
    from tradescope.data.maintenance import DataAuditRow, symbols_needing_repair

    rows = [
        DataAuditRow("IPO_CO", "ok", "partial_ipo", 100, "2015-01-01", "2025-01-01", 0, 0, False, 0),
        DataAuditRow("DEL_CO", "ok", "partial_delisted", 100, "2010-01-01", "2020-01-01", 0, 0, False, 0),
        DataAuditRow("GAPPY", "ok", "partial", 100, "2015-01-01", "2025-01-01", 0, 0, False, 0),
    ]
    needing_repair = symbols_needing_repair(rows)

    assert "IPO_CO" not in needing_repair
    assert "DEL_CO" not in needing_repair
    assert "GAPPY" in needing_repair


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


# ---------------------------------------------------------------------------
# Universe membership tests
# ---------------------------------------------------------------------------

def test_universe_membership_store_upsert_and_read(tmp_path) -> None:
    from tradescope.data.universe_memberships import UniverseMembership, UniverseMembershipStore

    store = UniverseMembershipStore(tmp_path / "universe_memberships.parquet")
    store.upsert([
        UniverseMembership("us_listed", "AAPL", "1980-12-12", None, "security_master", "2026-01-01"),
        UniverseMembership("us_listed", "ENRN", "1985-11-01", "2001-12-02", "security_master", "2026-01-01"),
    ])

    frame = store.read()
    assert len(frame) == 2
    assert set(frame["symbol"]) == {"AAPL", "ENRN"}


def test_universe_members_on_includes_active_symbol(tmp_path) -> None:
    from tradescope.data.universe_memberships import UniverseMembership, UniverseMembershipStore

    store = UniverseMembershipStore(tmp_path / "universe_memberships.parquet")
    store.upsert([UniverseMembership("us_listed", "AAPL", "1980-12-12", None, "security_master", "2026-01-01")])

    members = store.members_on("us_listed", date(2018, 6, 15))
    assert "AAPL" in members


def test_universe_members_on_excludes_not_yet_listed(tmp_path) -> None:
    from tradescope.data.universe_memberships import UniverseMembership, UniverseMembershipStore

    store = UniverseMembershipStore(tmp_path / "universe_memberships.parquet")
    store.upsert([UniverseMembership("us_listed", "NEWCO", "2020-01-01", None, "security_master", "2026-01-01")])

    members = store.members_on("us_listed", date(2019, 12, 31))
    assert "NEWCO" not in members


def test_universe_members_on_excludes_delisted_symbol(tmp_path) -> None:
    from tradescope.data.universe_memberships import UniverseMembership, UniverseMembershipStore

    store = UniverseMembershipStore(tmp_path / "universe_memberships.parquet")
    store.upsert([UniverseMembership("us_listed", "ENRN", "1985-11-01", "2001-12-02", "security_master", "2026-01-01")])

    assert "ENRN" not in store.members_on("us_listed", date(2002, 1, 1))
    assert "ENRN" in store.members_on("us_listed", date(2001, 6, 1))


def test_universe_members_on_includes_delisted_on_delisting_date(tmp_path) -> None:
    from tradescope.data.universe_memberships import UniverseMembership, UniverseMembershipStore

    store = UniverseMembershipStore(tmp_path / "universe_memberships.parquet")
    store.upsert([UniverseMembership("us_listed", "ENRN", "1985-11-01", "2001-12-02", "security_master", "2026-01-01")])

    # Should be included on the exact delisting date (inclusive end).
    assert "ENRN" in store.members_on("us_listed", date(2001, 12, 2))


def test_universe_members_on_empty_when_no_memberships(tmp_path) -> None:
    from tradescope.data.universe_memberships import UniverseMembershipStore

    store = UniverseMembershipStore(tmp_path / "universe_memberships.parquet")
    assert store.members_on("us_listed", date(2020, 1, 1)) == []


def test_build_us_listed_uses_ipo_date_as_start(tmp_path) -> None:
    from tradescope.data.alpha_vantage import ListingStatusRecord
    from tradescope.data.security_master import SecurityMaster, default_security_master_path
    from tradescope.data.universe_memberships import build_us_listed_from_security_master

    master = SecurityMaster(default_security_master_path(tmp_path / "processed"))
    master.upsert_listing_status([
        ListingStatusRecord(
            symbol="AAPL",
            name="Apple",
            exchange="NASDAQ",
            asset_type="Stock",
            ipo_date="1980-12-12",
            delisting_date=None,
            status="Active",
            source="test",
            as_of_date="2026-01-01",
        )
    ])

    memberships = build_us_listed_from_security_master(master, "2026-01-01")
    assert len(memberships) == 1
    m = memberships[0]
    assert m.symbol == "AAPL"
    assert m.start_date == "1980-12-12"
    assert m.end_date is None
    assert m.universe == "us_listed"


def test_build_us_listed_sets_end_date_for_delisted(tmp_path) -> None:
    from tradescope.data.alpha_vantage import ListingStatusRecord
    from tradescope.data.security_master import SecurityMaster, default_security_master_path
    from tradescope.data.universe_memberships import build_us_listed_from_security_master

    master = SecurityMaster(default_security_master_path(tmp_path / "processed"))
    master.upsert_listing_status([
        ListingStatusRecord(
            symbol="ENRN",
            name="Enron",
            exchange="NYSE",
            asset_type="Stock",
            ipo_date="1985-11-01",
            delisting_date="2001-12-02",
            status="Delisted",
            source="test",
            as_of_date="2026-01-01",
        )
    ])

    memberships = build_us_listed_from_security_master(master, "2026-01-01")
    assert len(memberships) == 1
    m = memberships[0]
    assert m.end_date == "2001-12-02"


# ---------------------------------------------------------------------------
# S&P 500 ingestion tests
# ---------------------------------------------------------------------------

def test_clean_ticker_strips_yyyymm_suffix() -> None:
    from tradescope.data.sp500 import _clean_ticker

    assert _clean_ticker("AAL-199702") == "AAL"
    assert _clean_ticker("AAMRQ-201312") == "AAMRQ"
    assert _clean_ticker("ENRNQ-200411") == "ENRNQ"


def test_clean_ticker_preserves_legitimate_hyphens() -> None:
    from tradescope.data.sp500 import _clean_ticker

    assert _clean_ticker("BRK-B") == "BRK-B"
    assert _clean_ticker("AAPL") == "AAPL"
    assert _clean_ticker("BF.B") == "BF.B"


def test_build_sp500_memberships_first_row_all_become_members() -> None:
    from tradescope.data.sp500 import build_sp500_memberships

    changes = pd.DataFrame(
        {"tickers": ["AAPL,MSFT,GE"]},
        index=pd.to_datetime(["1996-01-02"]),
    )
    changes.index.name = "date"

    memberships = build_sp500_memberships(changes, "2026-01-01")

    symbols = {m.symbol for m in memberships}
    assert symbols == {"AAPL", "MSFT", "GE"}
    assert all(m.end_date is None for m in memberships)
    assert all(m.universe == "sp500" for m in memberships)
    assert all(m.source == "fja05680/sp500" for m in memberships)


def test_build_sp500_memberships_detects_removal() -> None:
    from tradescope.data.sp500 import build_sp500_memberships

    changes = pd.DataFrame(
        {"tickers": ["AAPL,MSFT,GE", "AAPL,MSFT"]},
        index=pd.to_datetime(["1996-01-02", "2001-06-01"]),
    )
    changes.index.name = "date"

    memberships = build_sp500_memberships(changes, "2026-01-01")

    ge = next(m for m in memberships if m.symbol == "GE")
    assert ge.start_date == "1996-01-02"
    assert ge.end_date == "2001-05-31"  # day before 2001-06-01 removal row

    aapl = next(m for m in memberships if m.symbol == "AAPL")
    assert aapl.end_date is None  # still in last row


def test_build_sp500_memberships_detects_addition() -> None:
    from tradescope.data.sp500 import build_sp500_memberships

    changes = pd.DataFrame(
        {"tickers": ["AAPL,MSFT", "AAPL,MSFT,TSLA"]},
        index=pd.to_datetime(["1996-01-02", "2020-12-21"]),
    )
    changes.index.name = "date"

    memberships = build_sp500_memberships(changes, "2026-01-01")

    tsla = next(m for m in memberships if m.symbol == "TSLA")
    assert tsla.start_date == "2020-12-21"
    assert tsla.end_date is None


def test_build_sp500_memberships_handles_multiple_tenures() -> None:
    from tradescope.data.sp500 import build_sp500_memberships

    # GE: starts 1996, removed 2018, re-added 2024
    changes = pd.DataFrame(
        {
            "tickers": [
                "AAPL,GE",
                "AAPL",
                "AAPL,GE",
            ]
        },
        index=pd.to_datetime(["1996-01-02", "2018-06-19", "2024-11-01"]),
    )
    changes.index.name = "date"

    memberships = build_sp500_memberships(changes, "2026-01-01")

    ge_records = [m for m in memberships if m.symbol == "GE"]
    assert len(ge_records) == 2

    ge_first = next(m for m in ge_records if m.start_date == "1996-01-02")
    assert ge_first.end_date == "2018-06-18"  # day before 2018-06-19 removal row

    ge_second = next(m for m in ge_records if m.start_date == "2024-11-01")
    assert ge_second.end_date is None


def test_build_sp500_memberships_strips_removal_date_suffix() -> None:
    from tradescope.data.sp500 import build_sp500_memberships

    changes = pd.DataFrame(
        {"tickers": ["AAPL,AAL-199702,MSFT"]},
        index=pd.to_datetime(["1996-01-02"]),
    )
    changes.index.name = "date"

    memberships = build_sp500_memberships(changes, "2026-01-01")

    symbols = {m.symbol for m in memberships}
    assert "AAL" in symbols
    assert "AAL-199702" not in symbols


def test_build_sp500_memberships_multiple_tenures_stored_separately(tmp_path) -> None:
    from tradescope.data.sp500 import build_sp500_memberships
    from tradescope.data.universe_memberships import UniverseMembershipStore

    changes = pd.DataFrame(
        {"tickers": ["AAPL,GE", "AAPL", "AAPL,GE"]},
        index=pd.to_datetime(["1996-01-02", "2018-06-19", "2024-11-01"]),
    )
    changes.index.name = "date"

    memberships = build_sp500_memberships(changes, "2026-01-01")
    store = UniverseMembershipStore(tmp_path / "universe_memberships.parquet")
    store.upsert(memberships)

    # GE should be a member in 1997 (first tenure) but not in 2019 (gap)
    assert "GE" in store.members_on("sp500", date(1997, 1, 1))
    assert "GE" not in store.members_on("sp500", date(2019, 1, 1))
    assert "GE" in store.members_on("sp500", date(2025, 1, 1))


def test_fetch_sp500_changes_uses_cache(tmp_path) -> None:
    from tradescope.data.sp500 import fetch_sp500_changes

    cache_path = tmp_path / "sp500_changes.csv"
    mock_df = pd.DataFrame(
        {"tickers": ["AAPL,MSFT"]},
        index=pd.to_datetime(["2024-01-01"]),
    )
    mock_df.index.name = "date"
    mock_df.to_csv(cache_path)

    loaded = fetch_sp500_changes(cache_path=cache_path)

    assert len(loaded) == 1
    assert "AAPL" in loaded.iloc[0]["tickers"]
