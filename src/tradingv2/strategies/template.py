from __future__ import annotations

from pathlib import Path


STRATEGY_TEMPLATE = '''from __future__ import annotations

import pandas as pd
import vectorbt as vbt


def generate_signals(data, params):
    """Return entries and exits aligned to close prices.

    data is a dict[str, pandas.DataFrame] keyed by symbol. Each dataframe has
    normalized OHLCV columns such as open, high, low, close, adj_close, volume.
    """
    window = int(params.get("window", 50))
    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)

    moving_average = vbt.MA.run(close, window=window).ma
    if isinstance(moving_average.columns, pd.MultiIndex):
        moving_average = moving_average.copy()
        moving_average.columns = moving_average.columns.get_level_values(-1)

    entries = close > moving_average
    exits = close < moving_average
    return {"entries": entries, "exits": exits}
'''


def write_strategy_template(path: Path, overwrite: bool = False) -> Path:
    strategy_path = path.expanduser()
    if strategy_path.suffix != ".py":
        strategy_path = strategy_path.with_suffix(".py")
    if strategy_path.exists() and not overwrite:
        raise FileExistsError(f"strategy already exists: {strategy_path}")
    strategy_path.parent.mkdir(parents=True, exist_ok=True)
    strategy_path.write_text(STRATEGY_TEMPLATE, encoding="utf-8")
    return strategy_path

