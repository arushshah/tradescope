from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import StringIO
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from tradescope.exceptions import DataError

ALPHA_VANTAGE_LISTING_STATUS_URL = "https://www.alphavantage.co/query"


@dataclass(frozen=True)
class ListingStatusRecord:
    symbol: str
    name: str | None
    exchange: str | None
    asset_type: str | None
    ipo_date: str | None
    delisting_date: str | None
    status: str
    source: str
    as_of_date: str | None


def fetch_listing_status(
    api_key: str,
    state: str,
    as_of_date: date | None = None,
) -> list[ListingStatusRecord]:
    if state not in {"active", "delisted"}:
        raise DataError("Alpha Vantage listing status state must be active or delisted")

    params = {
        "function": "LISTING_STATUS",
        "state": state,
        "apikey": api_key,
    }
    if as_of_date is not None:
        params["date"] = as_of_date.isoformat()

    url = f"{ALPHA_VANTAGE_LISTING_STATUS_URL}?{urlencode(params)}"
    with urlopen(url, timeout=60) as response:
        payload = response.read().decode("utf-8")
    return parse_listing_status_csv(payload, state, as_of_date)


def parse_listing_status_csv(
    payload: str,
    state: str,
    as_of_date: date | None = None,
) -> list[ListingStatusRecord]:
    frame = pd.read_csv(StringIO(payload))
    if frame.empty:
        return []
    if "symbol" not in frame.columns:
        message = payload.strip().replace("\n", " ")[:300]
        raise DataError(f"Alpha Vantage did not return listing status CSV: {message}")

    records = []
    for row in frame.to_dict(orient="records"):
        symbol = clean_string(row.get("symbol"))
        if not symbol:
            continue
        records.append(
            ListingStatusRecord(
                symbol=symbol,
                name=clean_string(row.get("name")),
                exchange=clean_string(row.get("exchange")),
                asset_type=clean_string(row.get("assetType")),
                ipo_date=clean_string(row.get("ipoDate")),
                delisting_date=clean_string(row.get("delistingDate")),
                status=clean_string(row.get("status")) or state,
                source="alpha_vantage_listing_status",
                as_of_date=as_of_date.isoformat() if as_of_date else None,
            )
        )
    return records


def clean_string(value) -> str | None:
    if pd.isna(value):
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"none", "null"}:
        return None
    return cleaned
