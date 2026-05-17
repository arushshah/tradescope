from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from tradescope.analytics import write_quantstats_report
from tradescope.config import BacktestConfig
from tradescope.visualization import write_drawdown_plot, write_equity_plot


class ResultStore:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_run_dir(self, name: str) -> tuple[Path, str]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}_{slugify(name)}"
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir, run_id

    def write_config(self, run_dir: Path, config: BacktestConfig) -> Path:
        path = run_dir / "config.yaml"
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(json_safe(config.model_dump(mode="json")), handle, sort_keys=False)
        return path

    def write_stats(self, run_dir: Path, stats: pd.Series) -> Path:
        csv_path = run_dir / "stats.csv"
        stats.rename("value").to_csv(csv_path, header=True)

        json_path = run_dir / "summary.json"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(json_safe(stats.to_dict()), handle, indent=2)
        return csv_path

    def write_equity_curve(self, run_dir: Path, equity_curve: pd.Series | pd.DataFrame) -> Path:
        path = run_dir / "equity_curve.csv"
        equity_curve.to_csv(path, index_label="timestamp")
        return path

    def write_signals(self, run_dir: Path, signals: dict[str, Any]) -> list[Path]:
        signals_dir = run_dir / "signals"
        signals_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for name in ["entries", "exits", "short_entries", "short_exits"]:
            value = signals.get(name)
            if value is None:
                continue
            frame = value.to_frame() if isinstance(value, pd.Series) else pd.DataFrame(value)
            path = signals_dir / f"{name}.csv"
            frame.astype(bool).to_csv(path, index_label="timestamp")
            written.append(path)
        return written

    def write_benchmark_equity(self, run_dir: Path, benchmark_equity: pd.Series) -> Path:
        path = run_dir / "benchmark_equity.csv"
        benchmark_equity.rename("benchmark_value").to_csv(path, index_label="timestamp")
        return path

    def write_benchmark_returns(self, run_dir: Path, benchmark_equity: pd.Series) -> Path:
        path = run_dir / "benchmark_returns.csv"
        benchmark_equity.pct_change().dropna().rename("benchmark_return").to_csv(
            path,
            index_label="timestamp",
        )
        return path

    def write_plots(self, run_dir: Path, equity_curve: pd.Series | pd.DataFrame) -> list[Path]:
        plots_dir = run_dir / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        return [
            write_equity_plot(equity_curve, plots_dir / "equity_curve.png"),
            write_drawdown_plot(equity_curve, plots_dir / "drawdown.png"),
        ]

    def write_trades(self, run_dir: Path, portfolio: Any) -> Path | None:
        path = run_dir / "trades.csv"
        try:
            records = portfolio.trades.records_readable
        except Exception:
            return None
        records.to_csv(path, index=False)
        return path

    def write_report(
        self,
        run_dir: Path,
        equity_curve: pd.Series | pd.DataFrame,
        benchmark_equity: pd.Series | None,
        title: str,
    ) -> Path:
        return write_quantstats_report(
            equity_curve,
            run_dir / "report.html",
            benchmark_equity=benchmark_equity,
            title=title,
        )

    def write_sweep_manifest(
        self,
        name: str,
        summary_path: Path,
        rows: list[dict[str, Any]],
        rank_by: str,
        ascending: bool,
    ) -> Path:
        path = self.output_dir / f"{slugify(name)}_sweep_manifest.json"
        payload = {
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "rank_by": rank_by,
            "ascending": ascending,
            "summary_path": summary_path,
            "run_count": len(rows),
            "runs": rows,
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(json_safe(payload), handle, indent=2)
        return path


def slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, pd.Timestamp | pd.Timedelta):
        return value.isoformat()
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    return value
