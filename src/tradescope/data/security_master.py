from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class SecurityRecord:
    provider: str
    symbol: str
    status: str
    first_seen: str
    last_seen: str
    history_start: str | None
    history_end: str | None
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
            "reason": reason,
        }
        self._write_records(records)

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
