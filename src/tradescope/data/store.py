from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Literal

import pandas as pd

from tradescope.data.security_master import SecurityMaster, default_security_master_path
from tradescope.data.symbol_mapping import SymbolMap, default_symbol_map_path

DataLayer = Literal["raw", "processed"]


@dataclass(frozen=True)
class MarketDataEntry:
    path: Path
    layer: DataLayer
    provider: str
    symbol: str
    start: str
    end: str
    interval: str
    rows: int
    first_timestamp: str | None
    last_timestamp: str | None


@dataclass(frozen=True)
class UnavailableSymbol:
    provider: str
    symbol: str
    interval: str
    start: str
    end: str
    reason: str


class MarketDataStore:
    def __init__(self, raw_dir: Path, processed_dir: Path, component_dir: Path | None = None) -> None:
        self.raw_dir = raw_dir
        self.processed_dir = processed_dir
        self.component_dir = component_dir or processed_dir.parent / "components"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.component_dir.mkdir(parents=True, exist_ok=True)
        self.security_master = SecurityMaster(default_security_master_path(self.processed_dir))
        self.symbol_map = SymbolMap(default_symbol_map_path(self.processed_dir))

    def read_processed(
        self,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
    ) -> pd.DataFrame | None:
        entry = self.find_covering_entry("processed", provider, symbol, start, end, interval)
        if entry is None:
            return None
        return trim_frame(pd.read_parquet(entry.path), start, end)

    def read_processed_parts(
        self,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
    ) -> list[pd.DataFrame]:
        return [
            trim_frame(pd.read_parquet(entry.path), start, end)
            for entry in self.find_overlapping_entries("processed", provider, symbol, start, end, interval)
        ]

    def write_raw(
        self,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
        data: pd.DataFrame,
    ) -> Path:
        return self._write("raw", provider, symbol, start, end, interval, data)

    def write_processed(
        self,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
        data: pd.DataFrame,
    ) -> Path:
        path = self._write("processed", provider, symbol, start, end, interval, data)
        self.security_master.upsert_available(provider, symbol, data, end)
        return path

    def list_entries(
        self,
        layer: DataLayer | None = None,
        symbol: str | None = None,
        provider: str | None = None,
        interval: str | None = None,
    ) -> list[MarketDataEntry]:
        layers: list[DataLayer] = [layer] if layer else ["raw", "processed"]
        entries: list[MarketDataEntry] = []
        for current_layer in layers:
            for path in sorted(self.root_for(current_layer).glob("*/*.parquet")):
                parsed = parse_market_data_filename(path)
                if parsed is None:
                    continue
                if provider and path.parent.name != provider:
                    continue
                if symbol and parsed["symbol"] != symbol.upper():
                    continue
                if interval and parsed["interval"] != interval:
                    continue
                frame = pd.read_parquet(path)
                entries.append(
                    MarketDataEntry(
                        path=path,
                        layer=current_layer,
                        provider=path.parent.name,
                        symbol=parsed["symbol"],
                        start=parsed["start"],
                        end=parsed["end"],
                        interval=parsed["interval"],
                        rows=len(frame),
                        first_timestamp=timestamp_or_none(frame.index.min()) if len(frame) else None,
                        last_timestamp=timestamp_or_none(frame.index.max()) if len(frame) else None,
                    )
                )
        return entries

    def find_covering_entry(
        self,
        layer: DataLayer,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
    ) -> MarketDataEntry | None:
        candidates = [
            entry
            for entry in self.list_entries(
                layer=layer,
                symbol=symbol,
                provider=provider,
                interval=interval,
            )
            if entry_covers(entry, start, end)
        ]
        if not candidates:
            return None
        return max(candidates, key=entry_span_days)

    def find_overlapping_entries(
        self,
        layer: DataLayer,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
    ) -> list[MarketDataEntry]:
        entries = [
            entry
            for entry in self.list_entries(
                layer=layer,
                symbol=symbol,
                provider=provider,
                interval=interval,
            )
            if entries_overlap(entry, start, end)
        ]
        return sorted(entries, key=lambda entry: entry_start_date(entry))

    def read_entry(self, entry: MarketDataEntry) -> pd.DataFrame:
        return pd.read_parquet(entry.path)

    def write_component(
        self,
        provider: str,
        symbol: str,
        component: str,
        data: pd.DataFrame,
    ) -> Path:
        path = self.component_path(provider, symbol, component)
        path.parent.mkdir(parents=True, exist_ok=True)
        data.columns = data.columns.astype(str)
        data.to_parquet(path, index=True)
        return path

    def has_component(self, provider: str, symbol: str, component: str) -> bool:
        return self.component_path(provider, symbol, component).exists()

    def read_component(self, provider: str, symbol: str, component: str) -> pd.DataFrame | None:
        path = self.component_path(provider, symbol, component)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def component_path(self, provider: str, symbol: str, component: str) -> Path:
        return self.component_dir / provider / component.lower() / f"{symbol.upper()}.parquet"

    def clear(
        self,
        layer: DataLayer | None = None,
        symbol: str | None = None,
    ) -> list[Path]:
        removed = []
        for entry in self.list_entries(layer=layer, symbol=symbol):
            entry.path.unlink()
            removed.append(entry.path)
        return removed

    def mark_unavailable(
        self,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
        reason: str,
    ) -> None:
        records = self._read_unavailable_records()
        key = unavailable_key(provider, symbol, start, end, interval)
        records[key] = {
            "provider": provider,
            "symbol": symbol.upper(),
            "interval": interval,
            "start": start.isoformat(),
            "end": end.isoformat() if end else "latest",
            "reason": reason,
        }
        self._write_unavailable_records(records)
        self.security_master.mark_unavailable(provider, symbol, reason)

    def unavailable_entry(
        self,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
    ) -> UnavailableSymbol | None:
        record = self._read_unavailable_records().get(
            unavailable_key(provider, symbol, start, end, interval)
        )
        if not record:
            return None
        return UnavailableSymbol(**record)

    def list_unavailable(self) -> list[UnavailableSymbol]:
        return [
            UnavailableSymbol(**record)
            for record in sorted(
                self._read_unavailable_records().values(),
                key=lambda item: (item["provider"], item["symbol"], item["interval"]),
            )
        ]

    def path_for(
        self,
        layer: DataLayer,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
    ) -> Path:
        end_part = end.isoformat() if end else "latest"
        name = f"{symbol.upper()}_{start.isoformat()}_{end_part}_{interval}.parquet"
        return self.root_for(layer) / provider / name

    def root_for(self, layer: DataLayer) -> Path:
        if layer == "raw":
            return self.raw_dir
        return self.processed_dir

    def _write(
        self,
        layer: DataLayer,
        provider: str,
        symbol: str,
        start: date,
        end: date | None,
        interval: str,
        data: pd.DataFrame,
    ) -> Path:
        path = self.path_for(layer, provider, symbol, start, end, interval)
        path.parent.mkdir(parents=True, exist_ok=True)
        data.to_parquet(path, index=True)
        return path

    @property
    def unavailable_path(self) -> Path:
        return self.processed_dir / "_unavailable_symbols.json"

    def _read_unavailable_records(self) -> dict[str, dict[str, str]]:
        if not self.unavailable_path.exists():
            return {}
        with self.unavailable_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_unavailable_records(self, records: dict[str, dict[str, str]]) -> None:
        self.unavailable_path.parent.mkdir(parents=True, exist_ok=True)
        with self.unavailable_path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, indent=2, sort_keys=True)


def parse_market_data_filename(path: Path) -> dict[str, str] | None:
    parts = path.stem.split("_")
    if len(parts) < 4:
        return None
    symbol = parts[0].upper()
    start = parts[1]
    interval = parts[-1]
    end = "_".join(parts[2:-1])
    return {"symbol": symbol, "start": start, "end": end, "interval": interval}


def combine_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames).sort_index()
    return combined[~combined.index.duplicated(keep="last")]


def trim_frame(frame: pd.DataFrame, start: date, end: date | None) -> pd.DataFrame:
    trimmed = frame.loc[pd.Timestamp(start) :]
    if end is not None:
        trimmed = trimmed.loc[: pd.Timestamp(end) - pd.Timedelta(nanoseconds=1)]
    return trimmed


def entry_start_date(entry: MarketDataEntry) -> date:
    return date.fromisoformat(entry.start)


def entry_end_date(entry: MarketDataEntry) -> date | None:
    if entry.end == "latest":
        return None
    return date.fromisoformat(entry.end)


def effective_end(end: date | None) -> date:
    return end or date.max


def unavailable_key(
    provider: str,
    symbol: str,
    start: date,
    end: date | None,
    interval: str,
) -> str:
    end_part = end.isoformat() if end else "latest"
    return f"{provider}:{symbol.upper()}:{start.isoformat()}:{end_part}:{interval}"


def entry_covers(entry: MarketDataEntry, start: date, end: date | None) -> bool:
    return entry_start_date(entry) <= start and effective_end(entry_end_date(entry)) >= effective_end(end)


def entries_overlap(entry: MarketDataEntry, start: date, end: date | None) -> bool:
    entry_start = entry_start_date(entry)
    entry_end = effective_end(entry_end_date(entry))
    requested_end = effective_end(end)
    return entry_start < requested_end and start < entry_end


def entry_span_days(entry: MarketDataEntry) -> int:
    return (effective_end(entry_end_date(entry)) - entry_start_date(entry)).days


def timestamp_or_none(value) -> str | None:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
