from __future__ import annotations

from typing import Any

import pandas as pd

from tradescope.strategies.base import SignalOutput


def generate_signals(data: dict[str, pd.DataFrame], params: dict[str, Any]) -> SignalOutput:
    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    if len(entries.index) > 0:
        entries.iloc[0] = True
    return {"entries": entries, "exits": exits}

