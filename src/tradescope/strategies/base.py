from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, TypedDict

import pandas as pd


class SignalOutput(TypedDict, total=False):
    entries: pd.Series | pd.DataFrame
    exits: pd.Series | pd.DataFrame
    short_entries: pd.Series | pd.DataFrame
    short_exits: pd.Series | pd.DataFrame
    metadata: dict[str, Any]


class BacktestContext:
    """Optional runtime context passed to strategies that declare a third parameter.

    Strategies that want dynamic, survivorship-bias-free universe access can
    declare `def generate_signals(data, params, context)` and call
    `context.members_on("sp500", as_of_date)` to get the index constituents
    on any historical date.

    Strategies with only two parameters continue to work unchanged.
    """

    def __init__(self, membership_store: Any) -> None:
        self._store = membership_store

    def members_on(self, universe: str, as_of_date: date) -> list[str]:
        """Return symbols in `universe` that were listed on `as_of_date`."""
        return self._store.members_on(universe, as_of_date)


StrategyFunction = Callable[[dict[str, pd.DataFrame], dict[str, Any]], SignalOutput]

