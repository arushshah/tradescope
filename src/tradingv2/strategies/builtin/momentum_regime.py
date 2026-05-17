from __future__ import annotations

from typing import Any

import pandas as pd
import vectorbt as vbt

from tradingv2.strategies.base import SignalOutput
from tradingv2.strategies.builtin._utils import symbol_columns


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    momentum_window = int(params.get("momentum_window", 126))
    trend_window = int(params.get("trend_window", 100))
    regime_symbol = str(params.get("regime_symbol", "SPY")).upper()
    regime_window = int(params.get("regime_window", 200))
    entry_quantile = float(params.get("entry_quantile", 0.8))
    exit_quantile = float(params.get("exit_quantile", 0.6))
    trade_regime_symbol = bool(params.get("trade_regime_symbol", False))

    if not 0 <= exit_quantile <= entry_quantile <= 1:
        raise ValueError("quantiles must satisfy 0 <= exit_quantile <= entry_quantile <= 1")
    if regime_symbol not in data:
        raise ValueError(f"regime_symbol '{regime_symbol}' must be included in config symbols/universe")

    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    tradable_symbols = [symbol for symbol in close.columns if trade_regime_symbol or symbol != regime_symbol]
    if not tradable_symbols:
        raise ValueError("momentum_regime requires at least one tradable symbol besides regime_symbol")

    tradable_close = close[tradable_symbols]
    momentum = tradable_close.pct_change(momentum_window, fill_method=None)
    momentum_rank = momentum.rank(axis=1, pct=True, ascending=True)

    trend_ma = symbol_columns(vbt.MA.run(tradable_close, window=trend_window).ma)
    in_symbol_trend = tradable_close > trend_ma

    regime_close = close[regime_symbol]
    regime_ma = vbt.MA.run(regime_close, window=regime_window).ma
    healthy_regime = (regime_close > regime_ma).reindex(close.index).fillna(False)

    desired_entries = momentum_rank >= entry_quantile
    desired_entries = desired_entries & in_symbol_trend
    desired_entries = desired_entries & healthy_regime.to_numpy()[:, None]

    keep_positions = momentum_rank >= exit_quantile
    keep_positions = keep_positions & in_symbol_trend
    keep_positions = keep_positions & healthy_regime.to_numpy()[:, None]

    entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    entries.loc[:, tradable_symbols] = desired_entries.fillna(False)
    exits.loc[:, tradable_symbols] = (~keep_positions.fillna(False)).astype(bool)

    return {
        "entries": entries,
        "exits": exits,
        "metadata": {
            "momentum_window": momentum_window,
            "trend_window": trend_window,
            "regime_symbol": regime_symbol,
            "regime_window": regime_window,
            "entry_quantile": entry_quantile,
            "exit_quantile": exit_quantile,
            "trade_regime_symbol": trade_regime_symbol,
        },
    }
