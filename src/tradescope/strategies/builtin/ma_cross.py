from __future__ import annotations

from typing import Any

import pandas as pd
import vectorbt as vbt

from tradescope.strategies.base import SignalOutput
from tradescope.strategies.builtin._utils import symbol_columns


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    fast_window = int(params.get("fast_window", 20))
    slow_window = int(params.get("slow_window", 100))
    if fast_window >= slow_window:
        raise ValueError("fast_window must be less than slow_window")

    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    fast_ma = vbt.MA.run(close, window=fast_window)
    slow_ma = vbt.MA.run(close, window=slow_window)
    above = fast_ma.ma_above(slow_ma.ma)
    above = symbol_columns(above)
    previous_above = above.shift(1, fill_value=False).astype(bool)
    entries = above & ~previous_above
    exits = ~above & previous_above

    return {
        "entries": entries,
        "exits": exits,
        "metadata": {"fast_window": fast_window, "slow_window": slow_window},
    }
