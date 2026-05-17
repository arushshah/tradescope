from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from tradescope.config import BacktestConfig
from tradescope.data.security_master import SecurityMaster, default_security_master_path
from tradescope.data.store import MarketDataStore


def write_config_collection_manifest(
    config: BacktestConfig,
    counts: dict[str, int],
    config_path: Path | None = None,
    manifest_dir: Path | None = None,
) -> Path:
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir, config.data.component_dir)
    unavailable = [
        entry.__dict__
        for entry in store.list_unavailable()
        if entry.provider == config.data.provider
        and entry.interval == config.interval
        and entry.symbol in set(config.symbols)
    ]
    payload = {
        "kind": "config",
        "generated_at": utc_now(),
        "config_path": str(config_path) if config_path else None,
        "name": config.name,
        "provider": config.data.provider,
        "interval": config.interval,
        "start": config.start.isoformat(),
        "end": config.end.isoformat() if config.end else None,
        "coverage_start": config.data.coverage_start.isoformat() if config.data.coverage_start else None,
        "coverage_end": config.data.coverage_end.isoformat() if config.data.coverage_end else None,
        "symbols_requested": len(config.symbols),
        "components": config.data.components,
        "counts": counts,
        "unavailable_symbols": unavailable,
        "security_status_counts": security_status_counts(config.data.processed_dir),
    }
    directory = manifest_dir or default_manifest_dir(config.data.processed_dir)
    return write_manifest(directory, config.name, payload)


def write_store_update_manifest(
    raw_dir: Path,
    processed_dir: Path,
    counts: dict[str, int],
    provider: str | None,
    interval: str | None,
    end: date,
    manifest_dir: Path | None = None,
) -> Path:
    payload = {
        "kind": "store_update",
        "generated_at": utc_now(),
        "provider": provider or "yfinance",
        "interval": interval,
        "end": end.isoformat(),
        "raw_dir": str(raw_dir),
        "processed_dir": str(processed_dir),
        "counts": counts,
        "security_status_counts": security_status_counts(processed_dir),
    }
    directory = manifest_dir or default_manifest_dir(processed_dir)
    return write_manifest(directory, "store_update", payload)


def default_manifest_dir(processed_dir: Path) -> Path:
    return processed_dir.parent / "manifests"


def write_manifest(directory: Path, name: str, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slugify(name)}_{timestamp_for_filename()}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path


def security_status_counts(processed_dir: Path) -> dict[str, int]:
    frame = SecurityMaster(default_security_master_path(processed_dir)).read()
    if frame.empty:
        return {}
    return {str(status): int(count) for status, count in frame["status"].value_counts().items()}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def slugify(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return "_".join(part for part in cleaned.split("_") if part)
