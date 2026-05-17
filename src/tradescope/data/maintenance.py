from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from tradescope.backtesting.runner import BacktestRunner
from tradescope.config import BacktestConfig
from tradescope.data.quality import DataQualityReport, build_quality_report
from tradescope.data.store import MarketDataStore
from tradescope.data.yfinance_provider import YFinanceProvider
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


def refresh_symbols(config: BacktestConfig, symbols: list[str], end: date | None = None) -> None:
    if not symbols:
        return
    updated = canonical_config(config, end=end)
    updated.symbols = symbols
    updated.data.refresh = True
    BacktestRunner(updated)._load_data()


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


def fetch_configured_components(config: BacktestConfig) -> int:
    components = [component for component in config.data.components if component != "ohlcv"]
    if not components:
        return 0
    if config.data.provider != "yfinance":
        raise DataError(f"unsupported component provider: {config.data.provider}")

    provider = YFinanceProvider()
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir, config.data.component_dir)
    written = 0
    for symbol in config.symbols:
        for component in components:
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
