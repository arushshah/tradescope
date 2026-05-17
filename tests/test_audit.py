import pandas as pd

from tradingv2.backtesting.runner import BacktestRunner
from tradingv2.config import load_config
from tradingv2.data.store import MarketDataStore
from tradingv2.results.audit import audit_run


def test_audit_passes_clean_run(tmp_path) -> None:
    run_dir = make_run(tmp_path)

    report = audit_run(run_dir)

    assert report.passed
    assert "execution.price is close; same-bar close execution can be optimistic" in report.warnings


def test_audit_fails_missing_equity_curve(tmp_path) -> None:
    run_dir = make_run(tmp_path)
    (run_dir / "equity_curve.csv").unlink()

    report = audit_run(run_dir)

    assert not report.passed
    assert "missing equity_curve.csv" in report.errors


def test_audit_fails_misaligned_signals(tmp_path) -> None:
    run_dir = make_run(tmp_path)
    entries_path = run_dir / "signals" / "entries.csv"
    entries = pd.read_csv(entries_path)
    entries.loc[0, "timestamp"] = "1999-01-01"
    entries.to_csv(entries_path, index=False)

    report = audit_run(run_dir)

    assert not report.passed
    assert "entries index does not align with equity curve index" in report.errors


def test_audit_fails_corrupt_trade_pnl(tmp_path) -> None:
    run_dir = make_run(tmp_path)
    trades_path = run_dir / "trades.csv"
    trades = pd.read_csv(trades_path)
    trades.loc[0, "Status"] = "Closed"
    trades.loc[0, "Exit Timestamp"] = "2024-04-01"
    trades.loc[0, "Avg Exit Price"] = trades.loc[0, "Avg Entry Price"] + 10
    trades.loc[0, "Exit Fees"] = 0
    trades.loc[0, "PnL"] = 10 * trades.loc[0, "Size"]
    trades.loc[0, "PnL"] = trades.loc[0, "PnL"] + 100
    trades.to_csv(trades_path, index=False)

    report = audit_run(run_dir)

    assert not report.passed
    assert "trade PnL does not match prices, size, and fees" in report.errors


def test_audit_fails_negative_trade_fee(tmp_path) -> None:
    run_dir = make_run(tmp_path)
    trades_path = run_dir / "trades.csv"
    trades = pd.read_csv(trades_path)
    trades.loc[0, "Entry Fees"] = -1
    trades.to_csv(trades_path, index=False)

    report = audit_run(run_dir)

    assert not report.passed
    assert "trades contain negative Entry Fees" in report.errors


def test_audit_fails_trade_count_mismatch(tmp_path) -> None:
    run_dir = make_run(tmp_path)
    trades_path = run_dir / "trades.csv"
    trades = pd.read_csv(trades_path)
    trades.iloc[:-1].to_csv(trades_path, index=False)

    report = audit_run(run_dir)

    assert not report.passed
    assert any(
        error
        in {
            "stats Total Trades does not match trades.csv row count",
            "stats Total Trades is positive but trades.csv has no rows",
        }
        for error in report.errors
    )


def make_run(tmp_path):
    config = load_config("configs/examples/ma_cross.yaml")
    config.name = "audit_test"
    config.symbols = ["AAA"]
    config.start = pd.Timestamp("2024-01-01").date()
    config.end = pd.Timestamp("2024-05-01").date()
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"
    config.results.output_dir = tmp_path / "results"
    config.results.save_plots = False
    config.portfolio.benchmark = None
    config.strategy.params = {"fast_window": 5, "slow_window": 20}

    index = pd.date_range("2024-01-01", periods=90, freq="D", name="timestamp")
    close = pd.Series(range(100, 190), index=index, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adj_close": close,
            "volume": 1000,
            "symbol": "AAA",
            "source": "test",
        },
        index=index,
    )
    MarketDataStore(config.data.raw_dir, config.data.processed_dir).write_processed(
        "yfinance",
        "AAA",
        config.start,
        config.end,
        config.interval,
        frame,
    )

    result = BacktestRunner(config).run()
    run_dir = config.results.output_dir / result.run_id
    # Keep failed-test artifacts small if a test exits mid-run.
    assert run_dir.exists()
    return run_dir
