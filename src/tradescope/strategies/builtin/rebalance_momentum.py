from __future__ import annotations

from typing import Any

import pandas as pd
import vectorbt as vbt

from tradescope.strategies.base import SignalOutput
from tradescope.strategies.builtin._utils import symbol_columns


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    momentum_window = int(params.get("momentum_window", 126))
    top_n = int(params.get("top_n", 20))
    rebalance = str(params.get("rebalance", "monthly")).lower()
    regime_symbol = str(params.get("regime_symbol", "SPY")).upper()
    regime_window = int(params.get("regime_window", 200))
    use_regime_filter = bool(params.get("use_regime_filter", True))
    trend_window = int(params.get("trend_window", 100))
    use_trend_filter = bool(params.get("use_trend_filter", True))
    trade_regime_symbol = bool(params.get("trade_regime_symbol", False))
    exit_on_regime_fail = bool(params.get("exit_on_regime_fail", True))

    if momentum_window <= 0:
        raise ValueError("momentum_window must be positive")
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if rebalance not in {"monthly", "weekly"}:
        raise ValueError("rebalance must be 'monthly' or 'weekly'")
    if use_regime_filter and regime_symbol not in data:
        raise ValueError(f"regime_symbol '{regime_symbol}' must be included in config symbols/universe")

    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    tradable_symbols = [symbol for symbol in close.columns if trade_regime_symbol or symbol != regime_symbol]
    if not tradable_symbols:
        raise ValueError("rebalance_momentum requires at least one tradable symbol besides regime_symbol")

    tradable_close = close[tradable_symbols]
    momentum = tradable_close.pct_change(momentum_window, fill_method=None)
    eligible = momentum.notna()

    if use_trend_filter:
        trend_ma = symbol_columns(vbt.MA.run(tradable_close, window=trend_window).ma)
        eligible = eligible & (tradable_close > trend_ma)

    healthy_regime = pd.Series(True, index=close.index)
    if use_regime_filter:
        regime_close = close[regime_symbol]
        regime_ma = vbt.MA.run(regime_close, window=regime_window).ma
        healthy_regime = (regime_close > regime_ma).reindex(close.index).fillna(False)

    rebalance_dates = _rebalance_dates(close.index, rebalance)
    desired = _top_n_holdings(momentum, eligible, healthy_regime, rebalance_dates, top_n)
    entries, exits = _signals_from_holdings(desired, rebalance_dates, healthy_regime, exit_on_regime_fail)

    full_entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    full_exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    full_entries.loc[:, tradable_symbols] = entries
    full_exits.loc[:, tradable_symbols] = exits

    return {
        "entries": full_entries,
        "exits": full_exits,
        "metadata": {
            "momentum_window": momentum_window,
            "top_n": top_n,
            "rebalance": rebalance,
            "regime_symbol": regime_symbol,
            "regime_window": regime_window,
            "use_regime_filter": use_regime_filter,
            "trend_window": trend_window,
            "use_trend_filter": use_trend_filter,
            "trade_regime_symbol": trade_regime_symbol,
            "exit_on_regime_fail": exit_on_regime_fail,
        },
    }


def _rebalance_dates(index: pd.Index, rebalance: str) -> pd.Series:
    timestamp_index = pd.DatetimeIndex(index)
    periods = timestamp_index.to_period("M" if rebalance == "monthly" else "W")
    period_series = pd.Series(periods, index=index)
    return period_series.ne(period_series.shift())


def _top_n_holdings(
    momentum: pd.DataFrame,
    eligible: pd.DataFrame,
    healthy_regime: pd.Series,
    rebalance_dates: pd.Series,
    top_n: int,
) -> pd.DataFrame:
    desired = pd.DataFrame(False, index=momentum.index, columns=momentum.columns)
    current = pd.Series(False, index=momentum.columns)

    for timestamp in momentum.index:
        if bool(rebalance_dates.loc[timestamp]):
            current = pd.Series(False, index=momentum.columns)
            if bool(healthy_regime.loc[timestamp]):
                scores = momentum.loc[timestamp].where(eligible.loc[timestamp]).dropna()
                if not scores.empty:
                    selected = scores.nlargest(top_n).index
                    current.loc[selected] = True
        desired.loc[timestamp] = current

    return desired


def _signals_from_holdings(
    desired: pd.DataFrame,
    rebalance_dates: pd.Series,
    healthy_regime: pd.Series,
    exit_on_regime_fail: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    entries = pd.DataFrame(False, index=desired.index, columns=desired.columns)
    exits = pd.DataFrame(False, index=desired.index, columns=desired.columns)
    held = pd.Series(False, index=desired.columns)

    for timestamp in desired.index:
        target = desired.loc[timestamp].astype(bool)
        force_regime_exit = exit_on_regime_fail and not bool(healthy_regime.loc[timestamp])
        should_update = bool(rebalance_dates.loc[timestamp]) or force_regime_exit

        if should_update:
            if force_regime_exit:
                target = pd.Series(False, index=desired.columns)
            entries.loc[timestamp] = target & ~held
            exits.loc[timestamp] = held & ~target
            held = target

    return entries, exits
