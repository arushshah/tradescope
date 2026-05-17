"""S&P 500 historical constituent ingestion.

Primary source: fja05680/sp500 on GitHub.
Each CSV row is a full snapshot of all S&P 500 members on a composition-change date.
Tickers may carry a '-YYYYMM' suffix indicating when they were removed from the index;
this suffix is stripped before storing.

Usage:
    changes = fetch_sp500_changes()          # download from GitHub (or load cache)
    memberships = build_sp500_memberships(changes, as_of_date="2026-01-01")
    store.upsert(memberships)
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from tradescope.data.universe_memberships import UniverseMembership

SP500_CHANGES_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes.csv"
)


def fetch_sp500_changes(cache_path: Path | None = None) -> pd.DataFrame:
    """Download the S&P 500 changes CSV, optionally caching it locally.

    Returns a DataFrame indexed by date with a 'tickers' column.
    Each row is the full constituent list as of that change date.
    If cache_path exists it is loaded instead of downloading.
    """
    if cache_path is not None and cache_path.exists():
        return pd.read_csv(cache_path, index_col=0, parse_dates=True)
    df = pd.read_csv(SP500_CHANGES_URL, index_col=0, parse_dates=True)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_path)
    return df


def build_sp500_memberships(
    changes_df: pd.DataFrame,
    source_as_of_date: str,
) -> list[UniverseMembership]:
    """Convert the fja05680/sp500 changes DataFrame to UniverseMembership records.

    Each row in changes_df must have a DatetimeIndex and a 'tickers' column
    containing a comma-separated list of S&P 500 members as of that date.

    Symbols that entered and left the index multiple times receive one record per
    tenure, keyed by (universe, symbol, source, start_date).

    end_date is set to one day before the removal change row (inclusive last trading
    day in the index). Symbols still present in the most recent row get end_date=None.
    """
    df = changes_df.sort_index()
    rows: list[tuple[date, str]] = [
        (ts.date(), str(row["tickers"])) for ts, row in df.iterrows()
    ]

    current: dict[str, date] = {}  # symbol -> add_date
    closed: list[dict] = []

    prev_symbols: set[str] = set()

    for row_date, tickers_str in rows:
        cur_symbols = {
            _clean_ticker(t)
            for t in tickers_str.split(",")
            if t.strip()
        }
        cur_symbols.discard("")

        if not prev_symbols:
            for symbol in cur_symbols:
                current[symbol] = row_date
        else:
            for symbol in cur_symbols - prev_symbols:
                current[symbol] = row_date
            for symbol in prev_symbols - cur_symbols:
                if symbol in current:
                    closed.append(
                        {
                            "symbol": symbol,
                            "start_date": current.pop(symbol).isoformat(),
                            "end_date": (row_date - timedelta(days=1)).isoformat(),
                        }
                    )

        prev_symbols = cur_symbols

    for symbol, add_date in current.items():
        closed.append(
            {
                "symbol": symbol,
                "start_date": add_date.isoformat(),
                "end_date": None,
            }
        )

    return [
        UniverseMembership(
            universe="sp500",
            symbol=m["symbol"],
            start_date=m["start_date"],
            end_date=m["end_date"],
            source="fja05680/sp500",
            source_as_of_date=source_as_of_date,
        )
        for m in closed
    ]


def _clean_ticker(ticker: str) -> str:
    """Strip the -YYYYMM removal-date suffix from tickers like 'AAL-199702'.

    Tickers with legitimate hyphens (e.g. BRK-B) are preserved because their
    suffix is a single letter, not six digits.
    """
    ticker = ticker.strip()
    parts = ticker.split("-")
    if len(parts) > 1 and parts[-1].isdigit() and len(parts[-1]) == 6:
        return "-".join(parts[:-1])
    return ticker
