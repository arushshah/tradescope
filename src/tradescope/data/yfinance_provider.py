from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from typing import Any

import pandas as pd

from tradescope.data.base import MarketDataProvider
from tradescope.data.validation import validate_ohlcv
from tradescope.exceptions import DataError, NoDataError

YFINANCE_RESEARCH_COMPONENTS = [
    "dividends",
    "splits",
    "capital_gains",
    "income_stmt",
    "quarterly_income_stmt",
    "ttm_income_stmt",
    "balance_sheet",
    "quarterly_balance_sheet",
    "cash_flow",
    "quarterly_cash_flow",
    "ttm_cash_flow",
    "earnings",
    "quarterly_earnings",
    "earnings_dates",
    "earnings_history",
]

YFINANCE_EXPENSIVE_COMPONENTS = ["option_chains"]
YFINANCE_COMPONENT_PRESETS = {
    "research": YFINANCE_RESEARCH_COMPONENTS,
    "research_bundle": YFINANCE_RESEARCH_COMPONENTS,
    "all": [*YFINANCE_RESEARCH_COMPONENTS, *YFINANCE_EXPENSIVE_COMPONENTS],
}
YFINANCE_SUPPORTED_COMPONENTS = set(YFINANCE_COMPONENT_PRESETS["all"]) | {
    "incomestmt",
    "quarterly_incomestmt",
    "ttm_incomestmt",
    "balancesheet",
    "quarterly_balancesheet",
    "cashflow",
    "quarterly_cashflow",
    "ttm_cashflow",
}


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def fetch(
        self,
        symbols: list[str],
        start: date,
        end: date | None,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        return {
            symbol: validate_ohlcv(symbol, normalize_yfinance_frame(symbol, raw))
            for symbol, raw in self.fetch_raw(symbols, start, end, interval).items()
        }

    def fetch_raw(
        self,
        symbols: list[str],
        start: date,
        end: date | None,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise DataError("yfinance is required for provider 'yfinance'") from exc

        data_by_symbol: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                raw = yf.download(
                    symbol,
                    start=start.isoformat(),
                    end=end.isoformat() if end else None,
                    interval=interval,
                    auto_adjust=False,
                    progress=False,
                    group_by="column",
                )
            if raw.empty:
                raise NoDataError(f"{symbol}: yfinance returned no rows")
            raw.index = pd.to_datetime(raw.index)
            raw.index.name = "timestamp"
            data_by_symbol[symbol] = raw
        return data_by_symbol

    def normalize(self, symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
        return normalize_yfinance_frame(symbol, raw)

    def fetch_component(self, symbol: str, component: str) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise DataError("yfinance is required for provider 'yfinance'") from exc

        component = component.lower()
        if component not in YFINANCE_SUPPORTED_COMPONENTS:
            raise DataError(f"unsupported yfinance component: {component}")

        ticker = yf.Ticker(symbol)
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                data = fetch_component_payload(ticker, component)
        except Exception as exc:
            raise NoDataError(f"{symbol}: yfinance component '{component}' unavailable: {exc}") from exc
        return normalize_component_frame(symbol, component, data)


def normalize_yfinance_frame(symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        raise NoDataError(f"{symbol}: yfinance returned no rows")

    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    frame = frame.rename(columns=rename_map)
    if "adj_close" not in frame.columns and "close" in frame.columns:
        frame["adj_close"] = frame["close"]

    frame.index = pd.to_datetime(frame.index)
    frame.index.name = "timestamp"
    frame["symbol"] = symbol
    frame["source"] = "yfinance"
    return frame[["open", "high", "low", "close", "adj_close", "volume", "symbol", "source"]]


def normalize_component_frame(symbol: str, component: str, data: Any) -> pd.DataFrame:
    if isinstance(data, pd.Series):
        frame = data.to_frame(name=component)
    elif isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, list):
        frame = pd.DataFrame([flatten_mapping(item) for item in data])
    elif isinstance(data, dict):
        frame = pd.DataFrame([flatten_mapping(data)])
    else:
        frame = pd.DataFrame([{"value": data}])

    if frame.empty:
        frame = pd.DataFrame(columns=["symbol", "source", "component"])
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.RangeIndex(len(frame))
    else:
        frame.index = pd.to_datetime(frame.index)
        frame.index.name = "timestamp"
    frame["symbol"] = symbol.upper()
    frame["source"] = "yfinance"
    frame["component"] = component
    return frame


def flatten_mapping(data: dict[str, Any]) -> dict[str, Any]:
    flattened = {}
    if not isinstance(data, dict):
        return {"value": data}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            flattened[key] = value
        else:
            flattened[key] = str(value)
    return flattened


def expand_yfinance_components(components: list[str]) -> list[str]:
    expanded = []
    for component in components:
        for name in YFINANCE_COMPONENT_PRESETS.get(component, [component]):
            if name not in expanded:
                expanded.append(name)
    return expanded


def fetch_component_payload(ticker, component: str):
    if component == "actions":
        return ticker.actions
    if component == "dividends":
        return ticker.dividends
    if component == "splits":
        return ticker.splits
    if component == "capital_gains":
        return ticker.capital_gains
    if component == "history_metadata":
        return ticker.get_history_metadata()
    if component == "calendar":
        return ticker.get_calendar()
    if component in {"income_stmt", "incomestmt"}:
        return ticker.get_income_stmt()
    if component in {"quarterly_income_stmt", "quarterly_incomestmt"}:
        return ticker.get_income_stmt(freq="quarterly")
    if component in {"ttm_income_stmt", "ttm_incomestmt"}:
        return ticker.ttm_income_stmt
    if component in {"balance_sheet", "balancesheet"}:
        return ticker.get_balance_sheet()
    if component in {"quarterly_balance_sheet", "quarterly_balancesheet"}:
        return ticker.get_balance_sheet(freq="quarterly")
    if component in {"cash_flow", "cashflow"}:
        return ticker.get_cash_flow()
    if component in {"quarterly_cash_flow", "quarterly_cashflow"}:
        return ticker.get_cash_flow(freq="quarterly")
    if component in {"ttm_cash_flow", "ttm_cashflow"}:
        return ticker.ttm_cash_flow
    if component == "earnings":
        return ticker.get_earnings()
    if component == "quarterly_earnings":
        return ticker.quarterly_earnings
    if component == "earnings_dates":
        return ticker.get_earnings_dates(limit=24)
    if component == "earnings_history":
        return ticker.get_earnings_history()
    if component == "earnings_estimate":
        return ticker.get_earnings_estimate()
    if component == "growth_estimates":
        return ticker.get_growth_estimates()
    if component == "recommendations":
        return ticker.get_recommendations()
    if component == "recommendations_summary":
        return ticker.get_recommendations_summary()
    if component == "major_holders":
        return ticker.get_major_holders()
    if component == "institutional_holders":
        return ticker.get_institutional_holders()
    if component == "mutualfund_holders":
        return ticker.get_mutualfund_holders()
    if component == "insider_transactions":
        return ticker.get_insider_transactions()
    if component == "insider_roster_holders":
        return ticker.get_insider_roster_holders()
    if component == "sustainability":
        return ticker.get_sustainability()
    if component == "news":
        return ticker.news
    if component == "options":
        return [{"expiration": expiration} for expiration in ticker.options]
    if component == "option_chains":
        return fetch_option_chains(ticker)
    if component == "fast_info":
        return dict(ticker.fast_info)
    if component == "info":
        return ticker.get_info()
    raise DataError(f"unsupported yfinance component: {component}")


def fetch_option_chains(ticker) -> pd.DataFrame:
    frames = []
    for expiration in ticker.options:
        chain = ticker.option_chain(expiration)
        for side, frame in [("calls", chain.calls), ("puts", chain.puts)]:
            current = frame.copy()
            current["expiration"] = expiration
            current["option_side"] = side
            frames.append(current)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
