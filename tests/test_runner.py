import pandas as pd
import pytest

from tradescope.backtesting.runner import BacktestRunner, make_close_matrix
from tradescope.backtesting.runner import validate_signals
from tradescope.config import load_config
from tradescope.data.store import MarketDataStore
from tradescope.data.yfinance_provider import YFinanceProvider
from tradescope.exceptions import DataError, NoDataError, StrategyError


def test_equal_weight_sizing() -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    runner = BacktestRunner(config)
    close = pd.DataFrame(
        {"AAA": [10.0, 11.0], "BBB": [20.0, 21.0]},
        index=pd.date_range("2024-01-01", periods=2),
    )
    entries = pd.DataFrame(
        {"AAA": [True, False], "BBB": [True, True]},
        index=close.index,
    )

    kwargs = runner._sizing_kwargs(close, entries, {})

    assert kwargs["size_type"] == "percent"
    assert kwargs["size"].iloc[0].to_dict() == {"AAA": 0.5, "BBB": 0.5}
    assert kwargs["size"].iloc[1].to_dict() == {"AAA": 0.0, "BBB": 1.0}


def test_validate_signals_requires_entries_and_exits() -> None:
    with pytest.raises(StrategyError):
        validate_signals({"entries": None, "exits": pd.Series(dtype=bool)})


def test_runner_offline_multisymbol_processed_data(tmp_path) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.name = "offline_multisymbol"
    config.symbols = ["AAA", "BBB"]
    config.start = pd.Timestamp("2024-01-01").date()
    config.end = pd.Timestamp("2024-05-01").date()
    config.data.use_canonical_coverage = False
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"
    config.data.refresh = False
    config.results.output_dir = tmp_path / "results"
    config.results.save_plots = False
    config.portfolio.benchmark = None
    config.strategy.params = {"fast_window": 5, "slow_window": 20}

    index = pd.date_range("2024-01-01", periods=90, freq="D", name="timestamp")
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)
    for offset, symbol in enumerate(config.symbols):
        close = pd.Series(range(100 + offset, 190 + offset), index=index, dtype=float)
        frame = pd.DataFrame(
            {
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "adj_close": close,
                "volume": 1000,
                "symbol": symbol,
                "source": "test",
            },
            index=index,
        )
        store.write_processed("yfinance", symbol, config.start, config.end, config.interval, frame)

    result = BacktestRunner(config).run()

    assert result.run_id.endswith("offline_multisymbol")
    assert result.stats["Total Trades"] > 0
    assert (tmp_path / "results" / result.run_id / "signals" / "entries.csv").exists()
    assert (tmp_path / "results" / result.run_id / "signals" / "exits.csv").exists()


def test_runner_uses_covering_processed_data_without_fetch(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["AAA"]
    config.start = pd.Timestamp("2024-02-01").date()
    config.end = pd.Timestamp("2024-03-01").date()
    config.data.use_canonical_coverage = False
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"

    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)
    frame = processed_frame("AAA", "2024-01-01", "2024-05-01")
    store.write_processed(
        "yfinance",
        "AAA",
        pd.Timestamp("2024-01-01").date(),
        pd.Timestamp("2024-05-01").date(),
        "1d",
        frame,
    )

    def fail_fetch(*args, **kwargs):
        raise AssertionError("fetch_raw should not be called")

    monkeypatch.setattr(YFinanceProvider, "fetch_raw", fail_fetch)

    data = BacktestRunner(config)._load_data()

    assert data["AAA"].index.min() == pd.Timestamp("2024-02-01")
    assert data["AAA"].index.max() == pd.Timestamp("2024-02-29")


def test_runner_fetches_canonical_coverage_and_returns_requested_slice(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["AAA"]
    config.start = pd.Timestamp("2024-02-01").date()
    config.end = pd.Timestamp("2024-03-01").date()
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"
    config.data.use_canonical_coverage = True
    config.data.coverage_start = pd.Timestamp("2024-01-01").date()
    config.data.coverage_end = pd.Timestamp("2024-05-01").date()
    calls = []

    def fake_fetch(self, symbols, start, end, interval):
        calls.append((symbols, start, end, interval))
        return {symbols[0]: raw_frame(symbols[0], start, end)}

    monkeypatch.setattr(YFinanceProvider, "fetch_raw", fake_fetch)

    data = BacktestRunner(config)._load_data()

    assert calls == [
        (
            ["AAA"],
            pd.Timestamp("2024-01-01").date(),
            pd.Timestamp("2024-05-01").date(),
            "1d",
        )
    ]
    assert data["AAA"].index.min() == pd.Timestamp("2024-02-01")
    assert data["AAA"].index.max() == pd.Timestamp("2024-02-29")


def test_runner_fetches_only_missing_processed_tail(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["AAA"]
    config.start = pd.Timestamp("2024-01-01").date()
    config.end = pd.Timestamp("2024-05-01").date()
    config.data.use_canonical_coverage = False
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"

    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)
    store.write_processed(
        "yfinance",
        "AAA",
        pd.Timestamp("2024-01-01").date(),
        pd.Timestamp("2024-03-01").date(),
        "1d",
        processed_frame("AAA", "2024-01-01", "2024-03-01"),
    )
    calls = []

    def fake_fetch(self, symbols, start, end, interval):
        calls.append((symbols, start, end, interval))
        return {symbols[0]: raw_frame(symbols[0], start, end)}

    monkeypatch.setattr(YFinanceProvider, "fetch_raw", fake_fetch)

    data = BacktestRunner(config)._load_data()

    assert calls == [(["AAA"], pd.Timestamp("2024-03-01").date(), config.end, "1d")]
    assert data["AAA"].index.min() == pd.Timestamp("2024-01-01")
    assert data["AAA"].index.max() == pd.Timestamp("2024-04-30")
    assert store.read_processed("yfinance", "AAA", config.start, config.end, "1d") is not None


def test_runner_fetches_only_missing_processed_head(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["AAA"]
    config.start = pd.Timestamp("2024-01-01").date()
    config.end = pd.Timestamp("2024-05-01").date()
    config.data.use_canonical_coverage = False
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"

    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)
    store.write_processed(
        "yfinance",
        "AAA",
        pd.Timestamp("2024-03-01").date(),
        pd.Timestamp("2024-05-01").date(),
        "1d",
        processed_frame("AAA", "2024-03-01", "2024-05-01"),
    )
    calls = []

    def fake_fetch(self, symbols, start, end, interval):
        calls.append((symbols, start, end, interval))
        return {symbols[0]: raw_frame(symbols[0], start, end)}

    monkeypatch.setattr(YFinanceProvider, "fetch_raw", fake_fetch)

    data = BacktestRunner(config)._load_data()

    assert calls == [(["AAA"], config.start, pd.Timestamp("2024-03-01").date(), "1d")]
    assert data["AAA"].index.min() == pd.Timestamp("2024-01-01")
    assert data["AAA"].index.max() == pd.Timestamp("2024-04-30")


def test_runner_marks_no_data_symbol_and_continues(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["AAA", "BAD"]
    config.start = pd.Timestamp("2024-01-01").date()
    config.end = pd.Timestamp("2024-02-01").date()
    config.data.use_canonical_coverage = False
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"

    def fake_fetch(self, symbols, start, end, interval):
        symbol = symbols[0]
        if symbol == "BAD":
            raise NoDataError("BAD: no data")
        return {symbol: raw_frame(symbol, start, end)}

    monkeypatch.setattr(YFinanceProvider, "fetch_raw", fake_fetch)

    data = BacktestRunner(config)._load_data()
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)

    assert list(data) == ["AAA"]
    assert store.unavailable_entry("yfinance", "BAD", config.start, config.end, "1d") is not None


def test_runner_skips_known_unavailable_symbol(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["AAA", "BAD"]
    config.start = pd.Timestamp("2024-01-01").date()
    config.end = pd.Timestamp("2024-02-01").date()
    config.data.use_canonical_coverage = False
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)
    store.write_processed(
        "yfinance",
        "AAA",
        config.start,
        config.end,
        "1d",
        processed_frame("AAA", "2024-01-01", "2024-02-01"),
    )
    store.mark_unavailable("yfinance", "BAD", config.start, config.end, "1d", "BAD: no data")

    def fail_fetch(*args, **kwargs):
        raise AssertionError("known unavailable symbol should not be fetched")

    monkeypatch.setattr(YFinanceProvider, "fetch_raw", fail_fetch)

    data = BacktestRunner(config)._load_data()

    assert list(data) == ["AAA"]


def test_runner_skips_known_unavailable_symbol_even_on_refresh(tmp_path, monkeypatch) -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.symbols = ["BAD"]
    config.start = pd.Timestamp("2024-01-01").date()
    config.end = pd.Timestamp("2024-02-01").date()
    config.data.use_canonical_coverage = False
    config.data.raw_dir = tmp_path / "raw"
    config.data.processed_dir = tmp_path / "processed"
    config.data.refresh = True
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)
    store.mark_unavailable("yfinance", "BAD", config.start, config.end, "1d", "BAD: no data")

    def fail_fetch(*args, **kwargs):
        raise AssertionError("known unavailable symbol should not be fetched")

    monkeypatch.setattr(YFinanceProvider, "fetch_raw", fail_fetch)

    with pytest.raises(DataError, match="no market data loaded"):
        BacktestRunner(config)._load_data()


def raw_frame(symbol: str, start, end) -> pd.DataFrame:
    index = pd.date_range(start, pd.Timestamp(end) - pd.Timedelta(days=1), freq="D", name="timestamp")
    values = pd.Series(range(100, 100 + len(index)), index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": values,
            "High": values + 1,
            "Low": values - 1,
            "Close": values,
            "Adj Close": values,
            "Volume": 1000,
        },
        index=index,
    )


def processed_frame(symbol: str, start: str, end: str) -> pd.DataFrame:
    raw = raw_frame(symbol, pd.Timestamp(start), pd.Timestamp(end))
    return YFinanceProvider().normalize(symbol, raw)


def test_execution_price_next_open() -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.portfolio.execution.price = "next_open"
    runner = BacktestRunner(config)
    index = pd.date_range("2024-01-01", periods=3)
    data = {
        "AAA": pd.DataFrame(
            {
                "open": [9.0, 11.0, 13.0],
                "high": [10.0, 12.0, 14.0],
                "low": [8.0, 10.0, 12.0],
                "close": [10.0, 12.0, 14.0],
            },
            index=index,
        )
    }

    price = runner._execution_price(data, make_close_matrix(data))

    assert price["AAA"].iloc[0] == 11.0
    assert pd.isna(price["AAA"].iloc[-1])


def test_risk_kwargs() -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.portfolio.risk.stop_loss = 0.05
    config.portfolio.risk.take_profit = 0.15
    config.portfolio.risk.trailing_stop = True

    kwargs = BacktestRunner(config)._risk_kwargs()

    assert kwargs == {"sl_stop": 0.05, "tp_stop": 0.15, "sl_trail": True}


def test_golden_fixed_share_backtest() -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.portfolio.init_cash = 1000
    config.portfolio.fees = 0
    config.portfolio.slippage = 0
    config.portfolio.benchmark = None
    config.portfolio.sizing.method = "fixed_shares"
    config.portfolio.sizing.value = 1
    config.portfolio.execution.price = "close"
    runner = BacktestRunner(config)
    index = pd.date_range("2024-01-01", periods=4)
    data = {
        "AAA": pd.DataFrame(
            {
                "open": [10.0, 12.0, 14.0, 16.0],
                "high": [10.0, 12.0, 14.0, 16.0],
                "low": [10.0, 12.0, 14.0, 16.0],
                "close": [10.0, 12.0, 14.0, 16.0],
            },
            index=index,
        )
    }
    close = make_close_matrix(data)
    signals = {
        "entries": pd.DataFrame({"AAA": [True, False, False, False]}, index=index),
        "exits": pd.DataFrame({"AAA": [False, False, False, True]}, index=index),
    }

    portfolio = runner._build_portfolio(data, close, signals)
    stats = portfolio.stats(silence_warnings=True)

    assert stats["Total Trades"] == 1
    assert stats["End Value"] == pytest.approx(1006.0)
    assert stats["Total Return [%]"] == pytest.approx(0.6)


def test_golden_fixed_share_backtest_with_fees() -> None:
    portfolio = golden_portfolio(fees=0.10)
    stats = portfolio.stats(silence_warnings=True)

    assert stats["Total Trades"] == 1
    assert stats["Total Fees Paid"] == pytest.approx(2.6)
    assert stats["End Value"] == pytest.approx(1003.4)


def test_golden_fixed_share_backtest_with_slippage() -> None:
    portfolio = golden_portfolio(slippage=0.01)
    stats = portfolio.stats(silence_warnings=True)
    trade = portfolio.trades.records_readable.iloc[0]

    assert trade["Avg Entry Price"] == pytest.approx(10.1)
    assert trade["Avg Exit Price"] == pytest.approx(15.84)
    assert stats["End Value"] == pytest.approx(1005.74)


def test_golden_next_open_execution_uses_next_bar_open() -> None:
    config = golden_config()
    config.portfolio.execution.price = "next_open"
    runner = BacktestRunner(config)
    index = pd.date_range("2024-01-01", periods=4)
    data = {
        "AAA": pd.DataFrame(
            {
                "open": [9.0, 11.0, 13.0, 17.0],
                "high": [10.0, 12.0, 14.0, 18.0],
                "low": [8.0, 10.0, 12.0, 16.0],
                "close": [10.0, 12.0, 14.0, 16.0],
            },
            index=index,
        )
    }
    close = make_close_matrix(data)
    signals = {
        "entries": pd.DataFrame({"AAA": [True, False, False, False]}, index=index),
        "exits": pd.DataFrame({"AAA": [False, False, True, False]}, index=index),
    }

    portfolio = runner._build_portfolio(data, close, signals)
    trade = portfolio.trades.records_readable.iloc[0]

    assert trade["Avg Entry Price"] == pytest.approx(11.0)
    assert trade["Avg Exit Price"] == pytest.approx(17.0)
    assert portfolio.stats(silence_warnings=True)["End Value"] == pytest.approx(1006.0)


def golden_config():
    config = load_config("configs/examples/ma_cross.yaml")
    config.portfolio.init_cash = 1000
    config.portfolio.fees = 0
    config.portfolio.slippage = 0
    config.portfolio.benchmark = None
    config.portfolio.sizing.method = "fixed_shares"
    config.portfolio.sizing.value = 1
    config.portfolio.execution.price = "close"
    return config


def golden_portfolio(fees=0.0, slippage=0.0):
    config = golden_config()
    config.portfolio.fees = fees
    config.portfolio.slippage = slippage
    runner = BacktestRunner(config)
    index = pd.date_range("2024-01-01", periods=4)
    data = {
        "AAA": pd.DataFrame(
            {
                "open": [10.0, 12.0, 14.0, 16.0],
                "high": [10.0, 12.0, 14.0, 16.0],
                "low": [10.0, 12.0, 14.0, 16.0],
                "close": [10.0, 12.0, 14.0, 16.0],
            },
            index=index,
        )
    }
    close = make_close_matrix(data)
    signals = {
        "entries": pd.DataFrame({"AAA": [True, False, False, False]}, index=index),
        "exits": pd.DataFrame({"AAA": [False, False, False, True]}, index=index),
    }
    return runner._build_portfolio(data, close, signals)
