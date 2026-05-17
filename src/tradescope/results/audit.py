from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class AuditReport:
    run_dir: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def audit_run(run_dir: Path) -> AuditReport:
    report = AuditReport(run_dir=run_dir)
    config = read_config(run_dir, report)
    stats = read_stats(run_dir, report)
    equity = read_equity(run_dir, report)
    entries = read_signal(run_dir, "entries", report)
    exits = read_signal(run_dir, "exits", report)
    trades = read_trades(run_dir, report)

    if config:
        audit_config(config, report)
    if stats is not None:
        audit_stats(stats, report)
    if equity is not None:
        audit_equity(equity, report)
    if equity is not None and entries is not None and exits is not None:
        audit_signals(equity, entries, exits, report)
    if trades is not None:
        audit_trades(trades, config or {}, stats, report)

    return report


def read_config(run_dir: Path, report: AuditReport) -> dict:
    path = run_dir / "config.yaml"
    if not path.exists():
        report.add_error("missing config.yaml")
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def read_stats(run_dir: Path, report: AuditReport) -> pd.Series | None:
    path = run_dir / "stats.csv"
    if not path.exists():
        report.add_error("missing stats.csv")
        return None
    try:
        return pd.read_csv(path, index_col=0)["value"]
    except Exception as exc:
        report.add_error(f"could not read stats.csv: {exc}")
        return None


def read_equity(run_dir: Path, report: AuditReport) -> pd.DataFrame | None:
    path = run_dir / "equity_curve.csv"
    if not path.exists():
        report.add_error("missing equity_curve.csv")
        return None
    try:
        return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    except Exception as exc:
        report.add_error(f"could not read equity_curve.csv: {exc}")
        return None


def read_signal(run_dir: Path, name: str, report: AuditReport) -> pd.DataFrame | None:
    path = run_dir / "signals" / f"{name}.csv"
    if not path.exists():
        report.add_warning(f"missing signals/{name}.csv")
        return None
    try:
        return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    except Exception as exc:
        report.add_error(f"could not read signals/{name}.csv: {exc}")
        return None


def read_trades(run_dir: Path, report: AuditReport) -> pd.DataFrame | None:
    path = run_dir / "trades.csv"
    if not path.exists():
        report.add_warning("missing trades.csv")
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:
        report.add_error(f"could not read trades.csv: {exc}")
        return None


def audit_config(config: dict, report: AuditReport) -> None:
    if not config.get("symbols"):
        report.add_error("config has no resolved symbols")
    if config.get("portfolio", {}).get("execution", {}).get("price") == "close":
        report.add_warning("execution.price is close; same-bar close execution can be optimistic")


def audit_stats(stats: pd.Series, report: AuditReport) -> None:
    required = ["Total Return [%]", "Max Drawdown [%]", "Total Trades"]
    for metric in required:
        if metric not in stats.index:
            report.add_error(f"stats missing {metric}")
    numeric = pd.to_numeric(stats, errors="coerce")
    bad = numeric[numeric.index.isin(required) & numeric.isna()]
    for metric in bad.index:
        report.add_error(f"stats metric is not numeric: {metric}")


def audit_equity(equity: pd.DataFrame, report: AuditReport) -> None:
    if equity.empty:
        report.add_error("equity_curve.csv is empty")
        return
    if not equity.index.is_monotonic_increasing:
        report.add_error("equity curve timestamps are not monotonic")
    numeric = equity.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        report.add_error("equity curve contains non-numeric or missing values")
    if (numeric < 0).any().any():
        report.add_error("equity curve contains negative values")


def audit_signals(
    equity: pd.DataFrame,
    entries: pd.DataFrame,
    exits: pd.DataFrame,
    report: AuditReport,
) -> None:
    if not entries.index.equals(equity.index):
        report.add_error("entries index does not align with equity curve index")
    if not exits.index.equals(equity.index):
        report.add_error("exits index does not align with equity curve index")
    if list(entries.columns) != list(exits.columns):
        report.add_error("entries/exits columns do not match")
    if entries.empty or exits.empty:
        report.add_warning("signals are empty")
    for name, frame in {"entries": entries, "exits": exits}.items():
        values = frame.stack(future_stack=True).map(normalize_bool)
        if values.isna().any():
            report.add_error(f"{name} contains non-boolean values")


def audit_trades(
    trades: pd.DataFrame,
    config: dict,
    stats: pd.Series | None,
    report: AuditReport,
) -> None:
    if trades.empty:
        if stats is not None and "Total Trades" in stats.index:
            total_trades = pd.to_numeric(pd.Series([stats["Total Trades"]]), errors="coerce").iloc[0]
            if pd.notna(total_trades) and int(total_trades) > 0:
                report.add_error("stats Total Trades is positive but trades.csv has no rows")
                return
        report.add_warning("trades.csv has no rows")
        return

    required = ["Size", "Avg Entry Price", "Entry Fees", "PnL", "Direction", "Status"]
    missing_required = False
    for column in required:
        if column not in trades.columns:
            report.add_error(f"trades.csv missing {column}")
            missing_required = True
    if missing_required:
        return

    if stats is not None and "Total Trades" in stats.index:
        total_trades = pd.to_numeric(pd.Series([stats["Total Trades"]]), errors="coerce").iloc[0]
        if pd.notna(total_trades) and int(total_trades) != len(trades):
            report.add_error("stats Total Trades does not match trades.csv row count")

    numeric_columns = ["Size", "Avg Entry Price", "Avg Exit Price", "Entry Fees", "Exit Fees", "PnL"]
    numeric = {
        column: pd.to_numeric(trades[column], errors="coerce")
        for column in numeric_columns
        if column in trades.columns
    }
    if numeric["Size"].isna().any() or (numeric["Size"] <= 0).any():
        report.add_error("trades contain non-positive or invalid sizes")
    if numeric["Avg Entry Price"].isna().any() or (numeric["Avg Entry Price"] <= 0).any():
        report.add_error("trades contain non-positive or invalid entry prices")
    for fee_column in ["Entry Fees", "Exit Fees"]:
        if fee_column in numeric and (numeric[fee_column].fillna(0) < 0).any():
            report.add_error(f"trades contain negative {fee_column}")

    entry_col = find_column(trades, ["Entry Timestamp", "Entry Index"])
    exit_col = find_column(trades, ["Exit Timestamp", "Exit Index"])
    if entry_col and exit_col:
        entries = pd.to_datetime(trades[entry_col], errors="coerce")
        exits = pd.to_datetime(trades[exit_col], errors="coerce")
        closed_mask = trades["Status"].astype(str).str.lower().eq("closed")
        if entries.isna().any() or exits[closed_mask].isna().any():
            report.add_warning("some trade timestamps could not be parsed")
        elif (entries[closed_mask] > exits[closed_mask]).any():
            report.add_error("at least one trade exits before it enters")
        audit_trade_date_bounds(entries, exits, closed_mask, config, report)

    direction = config.get("portfolio", {}).get("direction")
    direction_col = find_column(trades, ["Direction"])
    if direction == "longonly" and direction_col and trades[direction_col].astype(str).str.lower().str.contains("short").any():
        report.add_error("longonly config produced short trades")

    audit_trade_pnl(trades, numeric, report)


def audit_trade_pnl(trades: pd.DataFrame, numeric: dict[str, pd.Series], report: AuditReport) -> None:
    if "Avg Exit Price" not in numeric:
        return
    closed_mask = trades["Status"].astype(str).str.lower().eq("closed")
    if not closed_mask.any():
        return
    exits = numeric["Avg Exit Price"]
    if exits[closed_mask].isna().any() or (exits[closed_mask] <= 0).any():
        report.add_error("closed trades contain non-positive or invalid exit prices")
        return

    size = numeric["Size"]
    entry = numeric["Avg Entry Price"]
    entry_fees = numeric["Entry Fees"].fillna(0)
    exit_fees = numeric.get("Exit Fees", pd.Series(0.0, index=trades.index)).fillna(0)
    pnl = numeric["PnL"]
    direction = trades["Direction"].astype(str).str.lower()
    expected = (exits - entry) * size - entry_fees - exit_fees
    short_mask = direction.str.contains("short")
    expected.loc[short_mask] = (
        (entry.loc[short_mask] - exits.loc[short_mask]) * size.loc[short_mask]
        - entry_fees.loc[short_mask]
        - exit_fees.loc[short_mask]
    )
    diff = (expected[closed_mask] - pnl[closed_mask]).abs()
    tolerance = 1e-6 + expected[closed_mask].abs() * 1e-8
    if (diff > tolerance).any():
        report.add_error("trade PnL does not match prices, size, and fees")


def audit_trade_date_bounds(
    entries: pd.Series,
    exits: pd.Series,
    closed_mask: pd.Series,
    config: dict,
    report: AuditReport,
) -> None:
    start = pd.to_datetime(config.get("start"), errors="coerce")
    end = pd.to_datetime(config.get("end"), errors="coerce")
    if pd.notna(start) and (entries < start).any():
        report.add_error("at least one trade enters before config start")
    if pd.notna(end) and exits[closed_mask].notna().any() and (exits[closed_mask] > end).any():
        report.add_error("at least one trade exits after config end")


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return pd.NA
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    return pd.NA


def find_column(frame: pd.DataFrame, names: list[str]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None
