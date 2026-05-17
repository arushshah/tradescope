from __future__ import annotations

from typing import Any

import pandas as pd
import vectorbt as vbt

from tradescope.strategies.base import SignalOutput
from tradescope.strategies.builtin._utils import symbol_columns


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    window = int(params.get("window", 14))
    entry_threshold = float(params.get("entry_threshold", 30))
    exit_threshold = float(params.get("exit_threshold", 60))

    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    rsi = vbt.RSI.run(close, window=window)
    entries = symbol_columns(rsi.rsi_below(entry_threshold))
    exits = symbol_columns(rsi.rsi_above(exit_threshold))
    return {"entries": entries, "exits": exits, "metadata": {"window": window}}
