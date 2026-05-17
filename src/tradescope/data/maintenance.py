from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby
from operator import attrgetter

import pandas as pd

from tradescope.backtesting.runner import BacktestRunner
from tradescope.config import BacktestConfig, DataConfig, PortfolioConfig, ResultsConfig, StrategyConfig
from tradescope.data.quality import DataQualityReport, build_quality_report
from tradescope.data.store import MarketDataStore
from tradescope.data.store import combine_frames, entry_end_date, entry_start_date
from tradescope.data.yfinance_provider import YFinanceProvider, expand_yfinance_components
from tradescope.exceptions import DataError, NoDataError


@dataclass(frozen=True)
class DataAuditRow:
    symbol: str
    status: str
    coverage: str
    rows: int
    start: str | None
    end: str | None
    missing_close: int
    duplicate_timestamps: int
    non_monotonic: bool
    large_calendar_gaps: int


@dataclass(frozen=True)
class StoredDataAuditRow:
    provider: str
    symbol: str
    interval: str
    status: str
    coverage: str
    rows: int
    start: str | None
    end: str | None
    missing_close: int
    duplicate_timestamps: int
    non_monotonic: bool
    large_calendar_gaps: int
    source_files: int


def canonical_config(config: BacktestConfig, end: date | None = None) -> BacktestConfig:
    updated = deepcopy(config)
    updated.start = updated.data.coverage_start or updated.start
    updated.end = end or updated.data.coverage_end or updated.end
    return updated


def update_dataset(config: BacktestConfig, end: date | None = None) -> dict[str, int]:
    updated = canonical_config(config, end=end)
    updated.data.refresh = False
    loaded = BacktestRunner(updated)._load_data()
    component_count = fetch_configured_components(updated)
    return {"ohlcv_symbols": len(loaded), "component_files": component_count}


def update_symbols_dataset(
    symbols: list[str],
    start: date,
    end: date | None,
    interval: str,
    raw_dir,
    processed_dir,
    component_dir,
    provider: str = "yfinance",
    components: list[str] | None = None,
    refresh: bool = False,
    name: str = "security_master_collection",
) -> tuple[BacktestConfig, dict[str, int]]:
    config = BacktestConfig(
        name=name,
        symbols=symbols,
        start=start,
        end=end,
        interval=interval,
        data=DataConfig(
            provider=provider,
            raw_dir=raw_dir,
            processed_dir=processed_dir,
            component_dir=component_dir,
            refresh=refresh,
            use_canonical_coverage=True,
            coverage_start=start,
            coverage_end=end,
            components=components or ["ohlcv"],
        ),
        strategy=StrategyConfig(name="buy_hold"),
        portfolio=PortfolioConfig(benchmark=None),
        results=ResultsConfig(save_trades=False, save_equity_curve=False, save_plots=False),
    )
    return config, update_dataset(config, end=end)


def update_stored_dataset(
    raw_dir,
    processed_dir,
    provider_name: str | None = None,
    interval: str | None = None,
    end: date | None = None,
) -> dict[str, int]:
    store = MarketDataStore(raw_dir, processed_dir)
    target_end = end or default_update_end()
    effective_provider = provider_name_or_default(provider_name)
    updated = 0
    skipped = 0

    for provider, symbol, current_interval, entries in stored_ohlcv_groups(
        store,
        provider=effective_provider,
        interval=interval,
    ):
        existing_end = latest_entry_end(entries)
        if existing_end is None or existing_end >= target_end:
            skipped += 1
            continue
        if store.unavailable_entry(provider, symbol, existing_end, target_end, current_interval):
            skipped += 1
            continue
        try:
            refresh_stored_group(store, provider, symbol, current_interval, entries, existing_end, target_end)
        except NoDataError as exc:
            store.mark_unavailable(provider, symbol, existing_end, target_end, current_interval, str(exc))
            skipped += 1
            continue
        updated += 1
    return {"ohlcv_symbols": updated, "skipped_symbols": skipped}


def refresh_symbols(config: BacktestConfig, symbols: list[str], end: date | None = None) -> None:
    if not symbols:
        return
    updated = canonical_config(config, end=end)
    updated.symbols = symbols
    updated.data.refresh = True
    BacktestRunner(updated)._load_data()


def repair_stored_dataset(
    raw_dir,
    processed_dir,
    provider_name: str | None = None,
    interval: str | None = None,
) -> int:
    store = MarketDataStore(raw_dir, processed_dir)
    repaired = 0
    for provider, symbol, current_interval, entries in stored_ohlcv_groups(
        store,
        provider=provider_name,
        interval=interval,
    ):
        row = audit_stored_group(provider, symbol, current_interval, entries, store)
        if not row_needs_repair(row):
            continue
        start = min(entry_start_date(entry) for entry in entries)
        end = latest_entry_end(entries)
        if end is None:
            continue
        if store.unavailable_entry(provider, symbol, start, end, current_interval):
            continue
        fetch_and_write_group(store, provider, symbol, current_interval, start, end)
        repaired += 1
    return repaired


def audit_dataset(config: BacktestConfig) -> list[DataAuditRow]:
    updated = canonical_config(config)
    store = MarketDataStore(updated.data.raw_dir, updated.data.processed_dir, updated.data.component_dir)
    rows = []
    for symbol in updated.symbols:
        frame = store.read_processed(
            updated.data.provider,
            symbol,
            updated.start,
            updated.end,
            updated.interval,
        )
        if frame is None:
            rows.append(
                DataAuditRow(
                    symbol=symbol,
                    status="missing",
                    coverage="missing",
                    rows=0,
                    start=None,
                    end=None,
                    missing_close=0,
                    duplicate_timestamps=0,
                    non_monotonic=False,
                    large_calendar_gaps=0,
                )
            )
            continue
        report = build_quality_report(symbol, frame)
        rows.append(row_from_report(report, frame, updated.start, updated.end))
    return rows


def audit_stored_dataset(
    raw_dir,
    processed_dir,
    provider_name: str | None = None,
    interval: str | None = None,
) -> list[StoredDataAuditRow]:
    store = MarketDataStore(raw_dir, processed_dir)
    return [
        audit_stored_group(provider, symbol, current_interval, entries, store)
        for provider, symbol, current_interval, entries in stored_ohlcv_groups(
            store,
            provider=provider_name,
            interval=interval,
        )
    ]


def rows_to_frame(rows: list[DataAuditRow]) -> pd.DataFrame:
    return pd.DataFrame([row.__dict__ for row in rows])


def symbols_needing_repair(rows: list[DataAuditRow]) -> list[str]:
    return [
        row.symbol
        for row in rows
        if row.coverage != "ok"
        or row.status != "ok"
        or row.duplicate_timestamps
        or row.missing_close
        or row.non_monotonic
        or row.large_calendar_gaps
    ]


def stored_rows_needing_repair(rows: list[StoredDataAuditRow]) -> list[StoredDataAuditRow]:
    return [row for row in rows if row_needs_repair(row)]


def fetch_configured_components(config: BacktestConfig) -> int:
    components = [component for component in expand_yfinance_components(config.data.components) if component != "ohlcv"]
    if not components:
        return 0
    if config.data.provider != "yfinance":
        raise DataError(f"unsupported component provider: {config.data.provider}")

    provider = YFinanceProvider()
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir, config.data.component_dir)
    written = 0
    for symbol in config.symbols:
        for component in components:
            if not config.data.refresh and store.has_component(provider.name, symbol, component):
                continue
            try:
                data = provider.fetch_component(symbol, component)
            except NoDataError:
                continue
            store.write_component(provider.name, symbol, component, data)
            written += 1
    return written


def default_update_end() -> date:
    return date.today() + timedelta(days=1)


def row_from_report(
    report: DataQualityReport,
    frame: pd.DataFrame,
    start: date,
    end: date | None,
) -> DataAuditRow:
    actual_start = pd.Timestamp(report.start).date() if report.start else None
    actual_end = pd.Timestamp(report.end).date() if report.end else None
    expected_last = None if end is None else pd.Timestamp(end).date() - timedelta(days=1)
    coverage_ok = actual_start is not None and actual_start <= start
    if expected_last is not None:
        coverage_ok = coverage_ok and actual_end is not None and actual_end >= expected_last
    coverage = "ok" if coverage_ok else "partial"
    return DataAuditRow(
        symbol=report.symbol,
        status=report.status,
        coverage=coverage,
        rows=report.rows,
        start=report.start,
        end=report.end,
        missing_close=report.missing_close,
        duplicate_timestamps=report.duplicate_timestamps,
        non_monotonic=report.non_monotonic,
        large_calendar_gaps=large_calendar_gap_count(frame),
    )


def large_calendar_gap_count(frame: pd.DataFrame, max_days: int = 7) -> int:
    if frame.empty:
        return 0
    index = pd.DatetimeIndex(frame.index).sort_values()
    return int((index.to_series().diff().dt.days > max_days).sum())


def stored_ohlcv_groups(
    store: MarketDataStore,
    provider: str | None = None,
    interval: str | None = None,
):
    entries = sorted(
        store.list_entries(layer="processed", provider=provider, interval=interval),
        key=attrgetter("provider", "symbol", "interval"),
    )
    for (provider_name, symbol, current_interval), grouped in groupby(
        entries,
        key=attrgetter("provider", "symbol", "interval"),
    ):
        yield provider_name, symbol, current_interval, list(grouped)


def audit_stored_group(
    provider: str,
    symbol: str,
    interval: str,
    entries,
    store: MarketDataStore,
) -> StoredDataAuditRow:
    frame = combine_frames([store.read_entry(entry) for entry in entries])
    report = build_quality_report(symbol, frame)
    start = min(entry_start_date(entry) for entry in entries)
    end = latest_entry_end(entries)
    row = row_from_report(report, frame, start, end)
    return StoredDataAuditRow(
        provider=provider,
        symbol=symbol,
        interval=interval,
        status=row.status,
        coverage=row.coverage,
        rows=row.rows,
        start=row.start,
        end=row.end,
        missing_close=row.missing_close,
        duplicate_timestamps=row.duplicate_timestamps,
        non_monotonic=row.non_monotonic,
        large_calendar_gaps=row.large_calendar_gaps,
        source_files=len(entries),
    )


def latest_entry_end(entries) -> date | None:
    ends = [entry_end_date(entry) for entry in entries]
    if any(end is None for end in ends):
        return None
    return max(end for end in ends if end is not None)


def row_needs_repair(row) -> bool:
    return (
        row.coverage != "ok"
        or row.status != "ok"
        or row.duplicate_timestamps
        or row.missing_close
        or row.non_monotonic
        or row.large_calendar_gaps
    )


def provider_name_or_default(provider_name: str | None) -> str:
    return provider_name or "yfinance"


def provider_for(provider_name: str):
    if provider_name != "yfinance":
        raise DataError(f"unsupported data provider: {provider_name}")
    return YFinanceProvider()


def refresh_stored_group(
    store: MarketDataStore,
    provider: str,
    symbol: str,
    interval: str,
    entries,
    fetch_start: date,
    fetch_end: date,
) -> None:
    raw = fetch_and_write_group(store, provider, symbol, interval, fetch_start, fetch_end)
    existing = combine_frames([store.read_entry(entry) for entry in entries])
    merged = combine_frames([existing, raw])
    merged_start = min(entry_start_date(entry) for entry in entries)
    store.write_processed(provider, symbol, merged_start, fetch_end, interval, merged)


def fetch_and_write_group(
    store: MarketDataStore,
    provider_name: str,
    symbol: str,
    interval: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    provider = provider_for(provider_name)
    raw = provider.fetch_raw([symbol], start, end, interval)[symbol]
    store.write_raw(provider.name, symbol, start, end, interval, raw)
    processed = validate_provider_frame(provider, symbol, raw)
    store.write_processed(provider.name, symbol, start, end, interval, processed)
    return processed


def validate_provider_frame(provider: YFinanceProvider, symbol: str, raw: pd.DataFrame) -> pd.DataFrame:
    from tradescope.data.validation import validate_ohlcv

    return validate_ohlcv(symbol, provider.normalize(symbol, raw))
