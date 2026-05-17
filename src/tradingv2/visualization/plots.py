from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd
import vectorbt as vbt  # noqa: F401

matplotlib.use("Agg")


def write_equity_plot(equity_curve: pd.Series | pd.DataFrame, path: Path) -> Path:
    series = portfolio_value_series(equity_curve)
    axis = series.plot(title="Equity Curve", linewidth=1.8)
    axis.set_xlabel("Date")
    axis.set_ylabel("Portfolio Value")
    figure = axis.get_figure()
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    figure.clear()
    return path


def write_drawdown_plot(equity_curve: pd.Series | pd.DataFrame, path: Path) -> Path:
    series = portfolio_value_series(equity_curve)
    drawdown = series.vbt.drawdown() * 100
    axis = drawdown.plot(title="Drawdown", linewidth=1.8)
    axis.set_xlabel("Date")
    axis.set_ylabel("Drawdown [%]")
    figure = axis.get_figure()
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    figure.clear()
    return path


def portfolio_value_series(equity_curve: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(equity_curve, pd.Series):
        return equity_curve.rename("portfolio_value")
    if equity_curve.shape[1] == 1:
        return equity_curve.iloc[:, 0].rename("portfolio_value")
    return equity_curve.sum(axis=1).rename("portfolio_value")
