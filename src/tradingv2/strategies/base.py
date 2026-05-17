from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

import pandas as pd


class SignalOutput(TypedDict, total=False):
    entries: pd.Series | pd.DataFrame
    exits: pd.Series | pd.DataFrame
    short_entries: pd.Series | pd.DataFrame
    short_exits: pd.Series | pd.DataFrame
    metadata: dict[str, Any]


StrategyFunction = Callable[[dict[str, pd.DataFrame], dict[str, Any]], SignalOutput]

