from __future__ import annotations

from typing import Any

import pandas as pd
import vectorbt as vbt

from tradingv2.strategies.base import SignalOutput
from tradingv2.strategies.builtin._utils import symbol_columns


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    window = int(params.get("window", 20))
    alpha = float(params.get("alpha", 2.0))
    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    bands = vbt.BBANDS.run(close, window=window, alpha=alpha)
    entries = symbol_columns(bands.close_below(bands.lower))
    exits = symbol_columns(bands.close_above(bands.middle))
    return {"entries": entries, "exits": exits, "metadata": {"window": window, "alpha": alpha}}

