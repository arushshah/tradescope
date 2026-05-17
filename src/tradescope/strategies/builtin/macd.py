from __future__ import annotations

from typing import Any

import pandas as pd
import vectorbt as vbt

from tradescope.strategies.base import SignalOutput
from tradescope.strategies.builtin._utils import symbol_columns


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    fast_window = int(params.get("fast_window", 12))
    slow_window = int(params.get("slow_window", 26))
    signal_window = int(params.get("signal_window", 9))
    if fast_window >= slow_window:
        raise ValueError("fast_window must be less than slow_window")

    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    macd = vbt.MACD.run(
        close,
        fast_window=fast_window,
        slow_window=slow_window,
        signal_window=signal_window,
    )
    entries = symbol_columns(macd.macd_crossed_above(macd.signal))
    exits = symbol_columns(macd.macd_crossed_below(macd.signal))
    return {
        "entries": entries,
        "exits": exits,
        "metadata": {
            "fast_window": fast_window,
            "slow_window": slow_window,
            "signal_window": signal_window,
        },
    }

