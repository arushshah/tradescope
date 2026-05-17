from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DataQualityReport:
    symbol: str
    rows: int
    start: str | None
    end: str | None
    duplicate_timestamps: int
    missing_values: int
    missing_close: int
    non_monotonic: bool

    @property
    def status(self) -> str:
        if self.rows == 0:
            return "empty"
        if self.duplicate_timestamps or self.missing_close or self.non_monotonic:
            return "warning"
        return "ok"


def build_quality_report(symbol: str, data: pd.DataFrame) -> DataQualityReport:
    if data.empty:
        return DataQualityReport(symbol, 0, None, None, 0, 0, 0, False)

    index = pd.to_datetime(data.index)
    duplicate_timestamps = int(index.duplicated().sum())
    missing_values = int(data.isna().sum().sum())
    missing_close = int(data["close"].isna().sum()) if "close" in data.columns else len(data)
    return DataQualityReport(
        symbol=symbol,
        rows=len(data),
        start=index.min().isoformat(),
        end=index.max().isoformat(),
        duplicate_timestamps=duplicate_timestamps,
        missing_values=missing_values,
        missing_close=missing_close,
        non_monotonic=not index.is_monotonic_increasing,
    )


def reports_to_frame(reports: list[DataQualityReport]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": report.symbol,
                "status": report.status,
                "rows": report.rows,
                "start": report.start,
                "end": report.end,
                "duplicate_timestamps": report.duplicate_timestamps,
                "missing_values": report.missing_values,
                "missing_close": report.missing_close,
                "non_monotonic": report.non_monotonic,
            }
            for report in reports
        ]
    )

