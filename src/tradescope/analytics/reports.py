from __future__ import annotations

from pathlib import Path

import pandas as pd

from tradescope.exceptions import TradeScopeError


def write_quantstats_report(
    equity_curve: pd.Series | pd.DataFrame,
    path: Path,
    benchmark_equity: pd.Series | pd.DataFrame | None = None,
    title: str = "TradeScope Backtest Report",
) -> Path:
    try:
        import quantstats as qs
    except ImportError as exc:
        raise TradeScopeError(
            "quantstats is required for HTML reports. Install with `.[reports]`."
        ) from exc

    returns = equity_to_returns(equity_curve)
    benchmark_returns = equity_to_returns(benchmark_equity) if benchmark_equity is not None else None
    path.parent.mkdir(parents=True, exist_ok=True)
    qs.reports.html(
        returns,
        benchmark=benchmark_returns,
        title=title,
        output=str(path),
    )
    return path


def equity_to_returns(equity_curve: pd.Series | pd.DataFrame) -> pd.Series:
    series = portfolio_value_series(equity_curve).sort_index()
    returns = series.pct_change().dropna()
    returns.index = pd.to_datetime(returns.index).tz_localize(None)
    return returns


def portfolio_value_series(equity_curve: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(equity_curve, pd.Series):
        return equity_curve.rename("portfolio_value")
    if equity_curve.shape[1] == 1:
        return equity_curve.iloc[:, 0].rename("portfolio_value")
    return equity_curve.sum(axis=1).rename("portfolio_value")

