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
        "data": ["audit", "clear", "collect-securities", "fetch", "inspect", "securities", "update", "validate"],
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
