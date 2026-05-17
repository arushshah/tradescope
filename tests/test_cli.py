from click.testing import CliRunner
import pandas as pd

from tradescope.cli import cli
from tradescope.data.alpha_vantage import ListingStatusRecord
from tradescope.data.store import MarketDataStore


def test_top_level_help_lists_documented_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ["backtest", "data", "reference", "results", "strategy", "universe"]:
        assert command in result.output
    assert "clear-data" not in result.output
    assert "fetch" not in result.output


def test_command_group_help_lists_documented_subcommands():
    runner = CliRunner()
    expected = {
        "backtest": ["run", "split", "sweep"],
        "data": ["audit", "clear", "collect-securities", "fetch", "inspect", "manifests", "securities", "update", "validate"],
        "results": ["audit", "best", "compare", "inspect", "show"],
        "strategy": ["describe", "init", "list"],
        "universe": ["list", "show"],
    }

    for group, commands in expected.items():
        result = runner.invoke(cli, [group, "--help"])

        assert result.exit_code == 0
        for command in commands:
            assert command in result.output


def test_data_clear_matches_documented_execution(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "data",
            "clear",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--processed-dir",
            str(tmp_path / "processed"),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "No data entries found." in result.output


def test_removed_top_level_data_shortcuts_are_not_available():
    runner = CliRunner()

    assert runner.invoke(cli, ["fetch", "--help"]).exit_code != 0
    assert runner.invoke(cli, ["clear-data", "--help"]).exit_code != 0


def test_reference_lists_full_command_tree():
    result = CliRunner().invoke(cli, ["reference"])

    assert result.exit_code == 0
    assert "tradescope backtest run --config VALUE" in result.output
    assert "tradescope data fetch --config VALUE" in result.output
    assert "tradescope data clear" in result.output
    assert "tradescope fetch" not in result.output
    assert "tradescope clear-data" not in result.output


def test_data_audit_all_audits_stored_processed_data(tmp_path):
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    index = pd.date_range("2024-01-01", "2024-01-05", freq="D", name="timestamp")
    store.write_processed(
        "yfinance",
        "SPY",
        index.min().date(),
        pd.Timestamp("2024-01-06").date(),
        "1d",
        pd.DataFrame(
            {
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "adj_close": 1.5,
                "volume": 100,
                "symbol": "SPY",
                "source": "test",
            },
            index=index,
        ),
    )

    result = CliRunner().invoke(
        cli,
        [
            "data",
            "audit",
            "--all",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--processed-dir",
            str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code == 0
    assert "SPY" in result.output
    assert "Data audit passed." in result.output


def test_data_update_requires_config_or_all():
    result = CliRunner().invoke(cli, ["data", "update"])

    assert result.exit_code != 0
    assert "provide --config" in result.output


def test_data_securities_shows_security_master(tmp_path):
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    index = pd.date_range("2024-01-01", "2024-01-02", freq="D", name="timestamp")
    store.write_processed(
        "yfinance",
        "SPY",
        pd.Timestamp("2024-01-01").date(),
        pd.Timestamp("2024-01-03").date(),
        "1d",
        pd.DataFrame({"close": [1.0, 2.0], "symbol": "SPY"}, index=index),
    )

    result = CliRunner().invoke(
        cli,
        ["data", "securities", "--processed-dir", str(tmp_path / "processed")],
    )

    assert result.exit_code == 0
    assert "SPY" in result.output
    assert "available" in result.output


def test_data_securities_ingests_alpha_vantage_listing_status(tmp_path, monkeypatch):
    def fake_fetch_listing_status(api_key, state, as_of_date=None):
        assert api_key == "demo"
        return [
            ListingStatusRecord(
                symbol=f"{state.upper()}1",
                name=f"{state} co",
                exchange="NYSE",
                asset_type="Stock",
                ipo_date="2010-01-01",
                delisting_date="2020-01-01" if state == "delisted" else None,
                status=state,
                source="alpha_vantage_listing_status",
                as_of_date=as_of_date.isoformat() if as_of_date else None,
            )
        ]

    monkeypatch.setattr("tradescope.cli.fetch_listing_status", fake_fetch_listing_status)

    result = CliRunner().invoke(
        cli,
        [
            "data",
            "securities",
            "ingest-alpha-vantage",
            "--api-key",
            "demo",
            "--processed-dir",
            str(tmp_path / "processed"),
            "--date",
            "2021-01-01",
        ],
    )

    assert result.exit_code == 0
    assert "Ingested 1 active listing(s)" in result.output
    assert "Ingested 1 delisted listing(s)" in result.output

    show_result = CliRunner().invoke(
        cli,
        ["data", "securities", "--processed-dir", str(tmp_path / "processed")],
    )
    assert show_result.exit_code == 0
    assert "ACTIVE1" in show_result.output
    assert "DELISTED1" in show_result.output


def test_data_securities_mappings_shows_provider_symbol_map(tmp_path):
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.symbol_map.upsert_active("BRK.B", "yfinance", "BRK-B", reason="test")

    result = CliRunner().invoke(
        cli,
        ["data", "securities", "mappings", "--processed-dir", str(tmp_path / "processed")],
    )

    assert result.exit_code == 0
    assert "BRK.B" in result.output
    assert "BRK-B" in result.output
    assert "yfinance" in result.output


def test_data_securities_mappings_add_upserts_mapping(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "data", "securities", "mappings", "add",
            "--source-symbol", "BRK.B",
            "--provider", "yfinance",
            "--provider-symbol", "BRK-B",
            "--reason", "manual verified",
            "--processed-dir", str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "BRK.B" in result.output
    assert "BRK-B" in result.output

    from tradescope.data.store import MarketDataStore
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    frame = store.symbol_map.read()
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_symbol"] == "BRK.B"
    assert row["provider_symbol"] == "BRK-B"
    assert row["status"] == "active"
    assert row["reason"] == "manual verified"


def test_data_securities_mappings_import_loads_csv(tmp_path):
    csv_path = tmp_path / "mappings.csv"
    csv_path.write_text("source_symbol,provider,provider_symbol,reason\nBRK.B,yfinance,BRK-B,manual\nAAPL,yfinance,AAPL,\n")

    result = CliRunner().invoke(
        cli,
        [
            "data", "securities", "mappings", "import",
            "--path", str(csv_path),
            "--processed-dir", str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "2 mapping(s)" in result.output

    from tradescope.data.store import MarketDataStore
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    frame = store.symbol_map.read()
    assert len(frame) == 2
    assert set(frame["source_symbol"]) == {"BRK.B", "AAPL"}


def test_data_securities_mappings_import_rejects_bad_csv(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("source_symbol,provider\nBRK.B,yfinance\n")

    result = CliRunner().invoke(
        cli,
        [
            "data", "securities", "mappings", "import",
            "--path", str(csv_path),
            "--processed-dir", str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code != 0
    assert "provider_symbol" in result.output


def test_data_collect_securities_fetches_from_security_master(tmp_path, monkeypatch):
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status(
        [
            ListingStatusRecord(
                symbol="SPY",
                name="SPDR S&P 500 ETF",
                exchange="NYSE ARCA",
                asset_type="Stock",
                ipo_date="1993-01-29",
                delisting_date=None,
                status="active",
                source="alpha_vantage_listing_status",
                as_of_date=None,
            )
        ]
    )

    def fake_update_symbols_dataset(**kwargs):
        assert kwargs["symbols"] == ["SPY"]
        assert kwargs["start"] == pd.Timestamp("2024-01-01").date()
        assert kwargs["end"] == pd.Timestamp("2024-01-03").date()

        class Config:
            name = "security_master_collection"
            symbols = ["SPY"]
            start = kwargs["start"]
            end = kwargs["end"]
            interval = kwargs["interval"]

            class Data:
                provider = "yfinance"
                raw_dir = tmp_path / "raw"
                processed_dir = tmp_path / "processed"
                component_dir = tmp_path / "components"
                coverage_start = kwargs["start"]
                coverage_end = kwargs["end"]
                components = kwargs["components"]

            data = Data()

        return Config(), {"ohlcv_symbols": 1, "component_files": 0}

    monkeypatch.setattr("tradescope.cli.update_symbols_dataset", fake_update_symbols_dataset)

    result = CliRunner().invoke(
        cli,
        [
            "data",
            "collect-securities",
            "--processed-dir",
            str(tmp_path / "processed"),
            "--raw-dir",
            str(tmp_path / "raw"),
            "--component-dir",
            str(tmp_path / "components"),
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
            "--offset",
            "0",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Matched security master symbol(s): 1" in result.output
    assert "Updated OHLCV for 1 symbol(s)" in result.output


def test_universe_commands_show_presets():
    runner = CliRunner()

    list_result = runner.invoke(cli, ["universe", "list"])
    show_result = runner.invoke(cli, ["universe", "show", "sp500"])

    assert list_result.exit_code == 0
    assert "sp500" in list_result.output
    assert show_result.exit_code == 0
    assert "AAPL" in show_result.output
    assert "BRK-B" in show_result.output


def test_data_universe_build_creates_us_listed_memberships(tmp_path):
    from tradescope.data.alpha_vantage import ListingStatusRecord
    from tradescope.data.store import MarketDataStore

    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status([
        ListingStatusRecord("AAPL", "Apple", "NASDAQ", "Stock", "1980-12-12", None, "Active", "test", "2026-01-01"),
        ListingStatusRecord("ENRN", "Enron", "NYSE", "Stock", "1985-11-01", "2001-12-02", "Delisted", "test", "2026-01-01"),
    ])

    result = CliRunner().invoke(
        cli,
        ["data", "universe", "build", "--processed-dir", str(tmp_path / "processed"), "--as-of", "2026-01-01"],
    )

    assert result.exit_code == 0, result.output
    assert "2 membership(s)" in result.output


def test_data_universe_members_returns_active_symbols(tmp_path):
    from tradescope.data.alpha_vantage import ListingStatusRecord
    from tradescope.data.store import MarketDataStore

    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status([
        ListingStatusRecord("AAPL", "Apple", "NASDAQ", "Stock", "1980-12-12", None, "Active", "test", "2026-01-01"),
        ListingStatusRecord("ENRN", "Enron", "NYSE", "Stock", "1985-11-01", "2001-12-02", "Delisted", "test", "2026-01-01"),
    ])
    CliRunner().invoke(
        cli,
        ["data", "universe", "build", "--processed-dir", str(tmp_path / "processed"), "--as-of", "2026-01-01"],
    )

    result = CliRunner().invoke(
        cli,
        [
            "data", "universe", "members",
            "--universe", "us_listed",
            "--as-of", "2000-01-01",
            "--processed-dir", str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "AAPL" in result.output
    assert "ENRN" in result.output


def test_data_universe_members_excludes_post_delisting(tmp_path):
    from tradescope.data.alpha_vantage import ListingStatusRecord
    from tradescope.data.store import MarketDataStore

    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status([
        ListingStatusRecord("ENRN", "Enron", "NYSE", "Stock", "1985-11-01", "2001-12-02", "Delisted", "test", "2026-01-01"),
    ])
    CliRunner().invoke(
        cli,
        ["data", "universe", "build", "--processed-dir", str(tmp_path / "processed"), "--as-of", "2026-01-01"],
    )

    result = CliRunner().invoke(
        cli,
        [
            "data", "universe", "members",
            "--universe", "us_listed",
            "--as-of", "2005-01-01",
            "--processed-dir", str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "ENRN" not in result.output
    assert "No members found" in result.output


def test_data_universe_ingest_sp500_upserts_memberships(tmp_path, monkeypatch):
    import pandas as pd

    mock_changes = pd.DataFrame(
        {"tickers": ["AAPL,MSFT,GE", "AAPL,MSFT"]},
        index=pd.to_datetime(["1996-01-02", "2018-06-19"]),
    )
    mock_changes.index.name = "date"

    monkeypatch.setattr("tradescope.cli.fetch_sp500_changes", lambda cache_path=None: mock_changes)

    result = CliRunner().invoke(
        cli,
        [
            "data", "universe", "ingest-sp500",
            "--as-of", "2026-01-01",
            "--processed-dir", str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "membership record(s)" in result.output

    from tradescope.data.universe_memberships import UniverseMembershipStore, default_universe_memberships_path
    store = UniverseMembershipStore(default_universe_memberships_path(tmp_path / "processed"))
    from datetime import date
    assert "AAPL" in store.members_on("sp500", date(2020, 1, 1))
    assert "GE" not in store.members_on("sp500", date(2020, 1, 1))
    assert "GE" in store.members_on("sp500", date(2000, 1, 1))


def test_collect_securities_skips_unavailable_symbols(tmp_path, monkeypatch):
    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status(
        [
            ListingStatusRecord("SPY", "SPDR", "NYSE", "Stock", "1993-01-29", None, "active", "alpha_vantage_listing_status", None),
            ListingStatusRecord("DEAD", "Dead Co", "NYSE", "Stock", "1990-01-01", "2005-01-01", "active", "alpha_vantage_listing_status", None),
        ]
    )
    store.mark_unavailable("yfinance", "DEAD", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-03").date(), "1d", "no data")

    collected = []

    def fake_update(symbols, **kwargs):
        collected.extend(symbols)

        class Config:
            name = "security_master_collection"
            symbols = collected[:]
            start = kwargs["start"]
            end = kwargs["end"]
            interval = kwargs["interval"]

            class Data:
                provider = "yfinance"
                raw_dir = tmp_path / "raw"
                processed_dir = tmp_path / "processed"
                component_dir = tmp_path / "components"
                coverage_start = kwargs["start"]
                coverage_end = kwargs["end"]
                components = kwargs["components"]

            data = Data()

        return Config(), {"ohlcv_symbols": len(collected), "component_files": 0}

    monkeypatch.setattr("tradescope.cli.update_symbols_dataset", fake_update)

    result = CliRunner().invoke(
        cli,
        [
            "data", "collect-securities",
            "--processed-dir", str(tmp_path / "processed"),
            "--raw-dir", str(tmp_path / "raw"),
            "--component-dir", str(tmp_path / "components"),
            "--start", "2024-01-01",
            "--end", "2024-01-03",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "DEAD" not in collected
    assert "SPY" in collected
    assert "already-unavailable" in result.output


def test_collect_securities_resume_last_advances_offset(tmp_path, monkeypatch):
    import json as _json
    from tradescope.data.collection_manifest import default_manifest_dir

    manifest_dir = default_manifest_dir(tmp_path / "processed")
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "security_master_collection_20260101T000000Z.json"
    manifest_path.write_text(_json.dumps({
        "kind": "security_master_collection",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "offset": 100,
        "symbols_requested": 50,
    }))

    store = MarketDataStore(tmp_path / "raw", tmp_path / "processed")
    store.security_master.upsert_listing_status(
        [ListingStatusRecord(f"SYM{i}", f"Co{i}", "NYSE", "Stock", "2000-01-01", None, "active", "alpha_vantage_listing_status", None) for i in range(200)]
    )

    captured_offset = []

    def fake_update(symbols, **kwargs):
        captured_offset.append(kwargs.get("offset", None))

        class Config:
            name = "security_master_collection"
            start = kwargs["start"]
            end = kwargs["end"]
            interval = kwargs["interval"]

            class Data:
                provider = "yfinance"
                raw_dir = tmp_path / "raw"
                processed_dir = tmp_path / "processed"
                component_dir = tmp_path / "components"
                coverage_start = kwargs["start"]
                coverage_end = kwargs["end"]
                components = kwargs["components"]

            data = Data()

        Config.symbols = symbols  # type: ignore[attr-defined]
        return Config(), {"ohlcv_symbols": len(symbols), "component_files": 0}

    monkeypatch.setattr("tradescope.cli.update_symbols_dataset", fake_update)

    result = CliRunner().invoke(
        cli,
        [
            "data", "collect-securities",
            "--processed-dir", str(tmp_path / "processed"),
            "--raw-dir", str(tmp_path / "raw"),
            "--component-dir", str(tmp_path / "components"),
            "--start", "2024-01-01",
            "--end", "2024-01-03",
            "--resume-last",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Resuming from offset 150" in result.output


def test_data_manifests_lists_recent_manifests(tmp_path):
    import json as _json
    from tradescope.data.collection_manifest import default_manifest_dir

    manifest_dir = default_manifest_dir(tmp_path / "processed")
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "security_master_collection_20260101T120000Z.json").write_text(
        _json.dumps({"kind": "security_master_collection", "generated_at": "2026-01-01T12:00:00+00:00"})
    )

    result = CliRunner().invoke(
        cli,
        ["data", "manifests", "--processed-dir", str(tmp_path / "processed")],
    )

    assert result.exit_code == 0, result.output
    assert "security_master_collection" in result.output


def test_data_manifests_show_prints_json(tmp_path):
    import json as _json
    from tradescope.data.collection_manifest import default_manifest_dir

    manifest_dir = default_manifest_dir(tmp_path / "processed")
    manifest_dir.mkdir(parents=True)
    manifest_file = manifest_dir / "security_master_collection_20260101T120000Z.json"
    manifest_file.write_text(_json.dumps({"kind": "security_master_collection", "symbols_requested": 42}))

    result = CliRunner().invoke(
        cli,
        [
            "data", "manifests", "show",
            "security_master_collection_20260101T120000Z",
            "--processed-dir", str(tmp_path / "processed"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "symbols_requested" in result.output
    assert "42" in result.output


def test_collect_securities_universe_flag_uses_membership_store(tmp_path, monkeypatch):
    from tradescope.data.universe_memberships import UniverseMembershipStore, default_universe_memberships_path, UniverseMembership

    store_path = default_universe_memberships_path(tmp_path / "processed")
    membership_store = UniverseMembershipStore(store_path)
    membership_store.upsert([
        UniverseMembership("sp500", "AAPL", "2010-01-01", None, "test", "2026-01-01"),
        UniverseMembership("sp500", "MSFT", "2010-01-01", None, "test", "2026-01-01"),
    ])

    collected = []

    def fake_update(symbols, **kwargs):
        collected.extend(symbols)

        class Config:
            name = "security_master_collection"
            symbols = collected[:]
            start = kwargs["start"]
            end = kwargs["end"]
            interval = kwargs["interval"]

            class Data:
                provider = "yfinance"
                raw_dir = tmp_path / "raw"
                processed_dir = tmp_path / "processed"
                component_dir = tmp_path / "components"
                coverage_start = kwargs["start"]
                coverage_end = kwargs["end"]
                components = kwargs["components"]

            data = Data()

        return Config(), {"ohlcv_symbols": len(collected), "component_files": 0}

    monkeypatch.setattr("tradescope.cli.update_symbols_dataset", fake_update)

    result = CliRunner().invoke(
        cli,
        [
            "data", "collect-securities",
            "--processed-dir", str(tmp_path / "processed"),
            "--raw-dir", str(tmp_path / "raw"),
            "--component-dir", str(tmp_path / "components"),
            "--universe", "sp500",
            "--start", "2024-01-01",
            "--end", "2024-01-03",
        ],
    )

    assert result.exit_code == 0, result.output
    assert sorted(collected) == ["AAPL", "MSFT"]
    assert "sp500" in result.output


def test_collect_securities_universe_flag_errors_when_store_missing(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "data", "collect-securities",
            "--processed-dir", str(tmp_path / "processed"),
            "--universe", "sp500",
        ],
    )

    assert result.exit_code != 0
    assert "ingest-sp500" in result.output
