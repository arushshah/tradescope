from pathlib import Path

import pandas as pd

from tradingv2.strategies.builtin.buy_hold import generate_signals as buy_hold
from tradingv2.strategies.builtin.bbands import generate_signals as bbands
from tradingv2.strategies.builtin.donchian import generate_signals as donchian
from tradingv2.strategies.builtin.ma_cross import generate_signals as ma_cross
from tradingv2.strategies.builtin.macd import generate_signals as macd
from tradingv2.strategies.builtin.momentum_regime import generate_signals as momentum_regime
from tradingv2.strategies.builtin.rebalance_momentum import generate_signals as rebalance_momentum
from tradingv2.strategies.loader import load_strategy
from tradingv2.strategies.registry import describe_strategy, list_strategy_metadata


def sample_data() -> dict[str, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=120, freq="D")
    close = pd.Series(range(1, 121), index=index, dtype=float)
    return {
        "SPY": pd.DataFrame(
            {
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
            },
            index=index,
        )
    }


def sample_multisymbol_data() -> dict[str, pd.DataFrame]:
    index = pd.date_range("2023-01-01", periods=260, freq="D")
    base = pd.Series(range(100, 360), index=index, dtype=float)
    return {
        "SPY": pd.DataFrame({"open": base, "high": base + 1, "low": base - 1, "close": base}, index=index),
        "AAA": pd.DataFrame({"open": base * 1.4, "high": base * 1.4 + 1, "low": base * 1.4 - 1, "close": base * 1.4}, index=index),
        "BBB": pd.DataFrame({"open": base * 0.8, "high": base * 0.8 + 1, "low": base * 0.8 - 1, "close": base * 0.8}, index=index),
    }


def sample_rebalance_data() -> dict[str, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=90, freq="D")
    day = pd.Series(range(90), index=index, dtype=float)
    spy = 100 + day
    aaa = 100 + day * 2.0
    bbb = 100 + day
    ccc = 100 - day * 0.1
    return {
        "SPY": pd.DataFrame({"open": spy, "high": spy + 1, "low": spy - 1, "close": spy}, index=index),
        "AAA": pd.DataFrame({"open": aaa, "high": aaa + 1, "low": aaa - 1, "close": aaa}, index=index),
        "BBB": pd.DataFrame({"open": bbb, "high": bbb + 1, "low": bbb - 1, "close": bbb}, index=index),
        "CCC": pd.DataFrame({"open": ccc, "high": ccc + 1, "low": ccc - 1, "close": ccc}, index=index),
    }


def sample_regime_failure_data() -> dict[str, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=45, freq="D")
    day = pd.Series(range(45), index=index, dtype=float)
    spy = pd.Series([100 + i for i in range(20)] + [120 - (i - 19) * 4 for i in range(20, 45)], index=index, dtype=float)
    aaa = 100 + day * 2.0
    bbb = 100 + day
    return {
        "SPY": pd.DataFrame({"open": spy, "high": spy + 1, "low": spy - 1, "close": spy}, index=index),
        "AAA": pd.DataFrame({"open": aaa, "high": aaa + 1, "low": aaa - 1, "close": aaa}, index=index),
        "BBB": pd.DataFrame({"open": bbb, "high": bbb + 1, "low": bbb - 1, "close": bbb}, index=index),
    }


def test_buy_hold_enters_first_row() -> None:
    signals = buy_hold(sample_data(), {})

    assert signals["entries"].iloc[0, 0]
    assert not signals["exits"].any().any()


def test_ma_cross_returns_aligned_signals() -> None:
    signals = ma_cross(sample_data(), {"fast_window": 5, "slow_window": 20})

    assert signals["entries"].shape == (120, 1)
    assert signals["exits"].shape == (120, 1)


def test_new_builtin_strategies_return_aligned_signals() -> None:
    for strategy in [bbands, macd, donchian]:
        signals = strategy(sample_data(), {})
        assert signals["entries"].shape == (120, 1)
        assert signals["exits"].shape == (120, 1)


def test_momentum_regime_returns_aligned_signals_and_does_not_trade_regime_symbol() -> None:
    signals = momentum_regime(
        sample_multisymbol_data(),
        {
            "momentum_window": 20,
            "trend_window": 10,
            "regime_window": 30,
            "entry_quantile": 0.5,
            "exit_quantile": 0.25,
            "regime_symbol": "SPY",
        },
    )

    assert signals["entries"].shape == (260, 3)
    assert signals["exits"].shape == (260, 3)
    assert not signals["entries"]["SPY"].any()
    assert signals["entries"][["AAA", "BBB"]].any().any()


def test_rebalance_momentum_selects_top_n_on_rebalance_dates_only() -> None:
    signals = rebalance_momentum(
        sample_rebalance_data(),
        {
            "momentum_window": 5,
            "top_n": 2,
            "rebalance": "monthly",
            "use_regime_filter": False,
            "use_trend_filter": False,
            "regime_symbol": "SPY",
        },
    )

    entries = signals["entries"]

    assert entries.shape == (90, 4)
    assert signals["exits"].shape == (90, 4)
    assert not entries["SPY"].any()
    assert set(entries.loc["2024-02-01"][entries.loc["2024-02-01"]].index) == {"AAA", "BBB"}
    assert entries.loc["2024-02-01"].sum() == 2
    assert not entries["CCC"].any()
    entry_dates = pd.DatetimeIndex(entries.index[entries.any(axis=1)])
    assert all(entry_dates.is_month_start)


def test_rebalance_momentum_exits_when_regime_fails() -> None:
    signals = rebalance_momentum(
        sample_regime_failure_data(),
        {
            "momentum_window": 3,
            "top_n": 1,
            "rebalance": "weekly",
            "regime_symbol": "SPY",
            "regime_window": 3,
            "use_regime_filter": True,
            "use_trend_filter": False,
            "exit_on_regime_fail": True,
        },
    )

    entries = signals["entries"][["AAA", "BBB"]]
    exits = signals["exits"][["AAA", "BBB"]]

    assert entries.any().any()
    first_entry_date = entries.index[entries.any(axis=1)][0]
    first_exit_date = exits.index[exits.any(axis=1)][0]
    assert first_exit_date > first_entry_date


def test_load_custom_strategy() -> None:
    strategy = load_strategy(path=Path("strategies/example_custom.py"))

    signals = strategy(sample_data(), {"window": 10})
    assert "entries" in signals


def test_load_custom_strategy_from_module() -> None:
    strategy = load_strategy(module="strategies.example_custom")

    signals = strategy(sample_data(), {"window": 10})
    assert "entries" in signals


def test_strategy_registry_metadata() -> None:
    names = {metadata.name for metadata in list_strategy_metadata()}

    assert {"bbands", "donchian", "macd", "ma_cross", "momentum_regime", "rebalance_momentum", "rsi"} <= names
    assert describe_strategy("ma_cross") is not None
