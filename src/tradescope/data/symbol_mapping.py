from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class SymbolMappingRecord:
    source: str
    source_symbol: str
    provider: str
    provider_symbol: str
    status: str
    reason: str | None
    first_seen: str
    last_seen: str


class SymbolMap:
    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve(self, provider: str, symbol: str) -> str | None:
        records = self._read_records()
        record = records.get(symbol_mapping_key("security_master", symbol, provider))
        if record and record.get("status") == "active":
            return str(record["provider_symbol"])
        return None

    def upsert_active(
        self,
        source_symbol: str,
        provider: str,
        provider_symbol: str,
        reason: str | None = None,
        source: str = "security_master",
    ) -> None:
        now = utc_now()
        records = self._read_records()
        key = symbol_mapping_key(source, source_symbol, provider)
        existing = records.get(key, {})
        records[key] = {
            "source": source,
            "source_symbol": source_symbol.upper(),
            "provider": provider,
            "provider_symbol": provider_symbol.upper(),
            "status": "active",
            "reason": reason,
            "first_seen": existing.get("first_seen", now),
            "last_seen": now,
        }
        self._write_records(records)

    def read(self) -> pd.DataFrame:
        records = self._read_records()
        columns = [
            "source",
            "source_symbol",
            "provider",
            "provider_symbol",
            "status",
            "reason",
            "first_seen",
            "last_seen",
        ]
        if not records:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(records.values()).sort_values(["provider", "source_symbol"]).reset_index(drop=True)

    def _read_records(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        frame = pd.read_parquet(self.path)
        return {
            symbol_mapping_key(str(row["source"]), str(row["source_symbol"]), str(row["provider"])): row.dropna().to_dict()
            for _, row in frame.iterrows()
        }

    def _write_records(self, records: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records.values()).sort_values(["provider", "source_symbol"]).to_parquet(self.path, index=False)


def default_symbol_map_path(processed_dir: Path) -> Path:
    return processed_dir.parent / "symbol_mappings.parquet"


def yfinance_symbol_candidates(symbol: str, mapped_symbol: str | None = None) -> list[str]:
    upper = symbol.upper()
    candidates = []
    if mapped_symbol:
        candidates.append(mapped_symbol.upper())
    candidates.append(upper)
    candidates.append(upper.replace(".", "-"))

    suffix_map = {
        "-W": "-WT",
        "-WS": "-WT",
        "-U": "-UN",
        "-R": "-RT",
    }
    for suffix, replacement in suffix_map.items():
        if upper.endswith(suffix):
            candidates.append(f"{upper.removesuffix(suffix)}{replacement}")

    return unique_preserving_order(candidates)


def symbol_mapping_key(source: str, source_symbol: str, provider: str) -> str:
    return f"{source}:{provider}:{source_symbol.upper()}"


def unique_preserving_order(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
