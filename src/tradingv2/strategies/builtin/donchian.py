from __future__ import annotations

from typing import Any

import pandas as pd

from tradingv2.strategies.base import SignalOutput


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    entry_window = int(params.get("entry_window", 55))
    exit_window = int(params.get("exit_window", 20))
    high = pd.concat({symbol: frame["high"] for symbol, frame in data.items()}, axis=1)
    low = pd.concat({symbol: frame["low"] for symbol, frame in data.items()}, axis=1)
    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)

    upper = high.rolling(entry_window).max().shift(1)
    lower = low.rolling(exit_window).min().shift(1)
    entries = close > upper
    exits = close < lower
    return {
        "entries": entries,
        "exits": exits,
        "metadata": {"entry_window": entry_window, "exit_window": exit_window},
    }

