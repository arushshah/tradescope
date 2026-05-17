from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class MarketDataProvider(ABC):
    """Common interface for market data providers."""

    @abstractmethod
    def fetch(
        self,
        symbols: list[str],
        start: date,
        end: date | None,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch normalized OHLCV data keyed by symbol."""

