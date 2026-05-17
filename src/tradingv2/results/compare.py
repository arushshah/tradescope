from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import pandas as pd
import yaml


DEFAULT_COLUMNS = [
    "run_id",
    "name",
    "Total Return [%]",
    "Benchmark Total Return [%]",
    "Max Drawdown [%]",
    "Sharpe Ratio",
    "Sortino Ratio",
    "Calmar Ratio",
    "Total Trades",
    "Win Rate [%]",
]


def build_run_row(run_dir: Path, params: dict[str, Any] | None = None) -> dict[str, Any]:
    stats_path = run_dir / "stats.csv"
    config_path = run_dir / "config.yaml"
    if not stats_path.exists():
        raise FileNotFoundError(f"missing stats.csv in {run_dir}")

    stats = {
        metric: coerce_stat_value(value)
        for metric, value in pd.read_csv(stats_path, index_col=0)["value"].to_dict().items()
    }
    config = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}

    row = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "name": config.get("name", run_dir.name),
    }
    if params:
        row.update({f"param.{key}": value for key, value in params.items()})
    row.update(stats)
    return row


def rank_results(rows: list[dict[str, Any]], rank_by: str, ascending: bool = False) -> pd.DataFrame:
    summary = pd.DataFrame(rows)
    if rank_by in summary.columns:
        summary = summary.sort_values(rank_by, ascending=ascending)
    return summary


def read_sweep(path: Path, rank_by: str | None = None, ascending: bool = False) -> pd.DataFrame:
    if path.suffix == ".json":
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        summary = pd.DataFrame(payload.get("runs", []))
        rank_by = rank_by or payload.get("rank_by")
        ascending = bool(payload.get("ascending", ascending))
    else:
        summary = pd.read_csv(path)

    for column in summary.columns:
        summary[column] = summary[column].map(coerce_stat_value)
    if rank_by and rank_by in summary.columns:
        summary = summary.sort_values(rank_by, ascending=ascending)
    return summary


def best_run_from_sweep(
    path: Path,
    rank_by: str | None = None,
    ascending: bool = False,
    filters: tuple[str, ...] = (),
) -> dict[str, Any]:
    summary = read_sweep(path, rank_by=rank_by, ascending=ascending)
    summary = apply_filters(summary, filters)
    if summary.empty:
        raise ValueError(f"sweep has no rows: {path}")
    return summary.iloc[0].to_dict()


def apply_filters(summary: pd.DataFrame, filters: tuple[str, ...]) -> pd.DataFrame:
    filtered = summary
    for expression in filters:
        if "=" not in expression:
            raise ValueError(f"invalid filter '{expression}', expected column=value")
        column, expected = expression.split("=", 1)
        if column not in filtered.columns:
            raise ValueError(f"unknown filter column: {column}")
        expected_value = coerce_stat_value(expected)
        filtered = filtered[filtered[column] == expected_value]
    return filtered


def display_columns(summary: pd.DataFrame) -> list[str]:
    param_columns = [column for column in summary.columns if column.startswith("param.")]
    preferred = [column for column in DEFAULT_COLUMNS if column in summary.columns]
    remaining = [
        column
        for column in summary.columns
        if column not in set(preferred + param_columns + ["run_dir"])
    ]
    return preferred + param_columns + remaining[:5]


def coerce_stat_value(value: Any) -> Any:
    numeric = pd.to_numeric(value, errors="coerce")
    if not pd.isna(numeric):
        return numeric.item() if hasattr(numeric, "item") else numeric
    return value
