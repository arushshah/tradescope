from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from tradescope.data.alpha_vantage import ListingStatusRecord


@dataclass(frozen=True)
class SecurityRecord:
    provider: str
    symbol: str
    status: str
    first_seen: str
    last_seen: str
    history_start: str | None
    history_end: str | None
    name: str | None = None
    exchange: str | None = None
    asset_type: str | None = None
    ipo_date: str | None = None
    delisting_date: str | None = None
    listing_source: str | None = None
    listing_as_of_date: str | None = None
    reason: str | None = None


class SecurityMaster:
    def __init__(self, path: Path) -> None:
        self.path = path

    def upsert_available(
        self,
        provider: str,
        symbol: str,
        data: pd.DataFrame,
        requested_end: date | None,
    ) -> None:
        now = utc_now()
        records = self._read_records()
        key = security_key(provider, symbol)
        existing = records.get(key, {})
        history_start = timestamp_to_date_string(data.index.min()) if len(data) else None
        history_end = timestamp_to_date_string(data.index.max()) if len(data) else None
        status = infer_status(history_end, requested_end)
        records[key] = {
            "provider": provider,
            "symbol": symbol.upper(),
            "status": status,
            "first_seen": existing.get("first_seen", now),
            "last_seen": now,
            "history_start": history_start,
            "history_end": history_end,
            "name": existing.get("name"),
            "exchange": existing.get("exchange"),
            "asset_type": existing.get("asset_type"),
            "ipo_date": existing.get("ipo_date"),
            "delisting_date": existing.get("delisting_date"),
            "listing_source": existing.get("listing_source"),
            "listing_as_of_date": existing.get("listing_as_of_date"),
            "reason": None,
        }
        self._write_records(records)

    def mark_unavailable(self, provider: str, symbol: str, reason: str) -> None:
        now = utc_now()
        records = self._read_records()
        key = security_key(provider, symbol)
        existing = records.get(key, {})
        records[key] = {
            "provider": provider,
            "symbol": symbol.upper(),
            "status": "unavailable",
            "first_seen": existing.get("first_seen", now),
            "last_seen": now,
            "history_start": existing.get("history_start"),
            "history_end": existing.get("history_end"),
            "name": existing.get("name"),
            "exchange": existing.get("exchange"),
            "asset_type": existing.get("asset_type"),
            "ipo_date": existing.get("ipo_date"),
            "delisting_date": existing.get("delisting_date"),
            "listing_source": existing.get("listing_source"),
            "listing_as_of_date": existing.get("listing_as_of_date"),
            "reason": reason,
        }
        self._write_records(records)

    def upsert_listing_status(self, listings: list[ListingStatusRecord]) -> int:
        now = utc_now()
        records = self._read_records()
        for listing in listings:
            key = security_key("security_master", listing.symbol)
            existing = records.get(key, {})
            status = "delisted" if listing.status.lower() == "delisted" else "active"
            records[key] = {
                "provider": existing.get("provider", "security_master"),
                "symbol": listing.symbol.upper(),
                "status": status,
                "first_seen": existing.get("first_seen", now),
                "last_seen": now,
                "history_start": existing.get("history_start"),
                "history_end": existing.get("history_end"),
                "name": listing.name or existing.get("name"),
                "exchange": listing.exchange or existing.get("exchange"),
                "asset_type": listing.asset_type or existing.get("asset_type"),
                "ipo_date": listing.ipo_date or existing.get("ipo_date"),
                "delisting_date": listing.delisting_date or existing.get("delisting_date"),
                "listing_source": listing.source,
                "listing_as_of_date": listing.as_of_date,
                "reason": existing.get("reason"),
            }
        self._write_records(records)
        return len(listings)

    def read(self) -> pd.DataFrame:
        records = self._read_records()
        columns = [
            "provider",
            "symbol",
            "status",
            "first_seen",
            "last_seen",
            "history_start",
            "history_end",
            "name",
            "exchange",
            "asset_type",
            "ipo_date",
            "delisting_date",
            "listing_source",
            "listing_as_of_date",
            "reason",
        ]
        if not records:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(records.values()).sort_values(["provider", "symbol"]).reset_index(drop=True)

    def _read_records(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        frame = pd.read_parquet(self.path)
        return {
            security_key(str(row["provider"]), str(row["symbol"])): row.dropna().to_dict()
            for _, row in frame.iterrows()
        }

    def _write_records(self, records: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(records.values()).sort_values(["provider", "symbol"]).reset_index(drop=True)
        frame.to_parquet(self.path, index=False)


def default_security_master_path(processed_dir: Path) -> Path:
    return processed_dir.parent / "security_master.parquet"


def security_key(provider: str, symbol: str) -> str:
    return f"{provider}:{symbol.upper()}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_to_date_string(value) -> str | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def infer_status(history_end: str | None, requested_end: date | None) -> str:
    if history_end is None:
        return "unknown"
    if requested_end is None:
        return "available"
    expected_last = requested_end - timedelta(days=1)
    if pd.Timestamp(history_end).date() < expected_last:
        return "historical"
    return "available"
