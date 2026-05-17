from __future__ import annotations

import pandas as pd


def generate_signals(data, params):
    window = int(params.get("window", 50))
    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
    moving_average = close.rolling(window).mean()
    entries = close > moving_average
    exits = close < moving_average
    return {"entries": entries, "exits": exits}

