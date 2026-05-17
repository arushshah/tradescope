import pandas as pd

from tradescope.analytics.reports import equity_to_returns


def test_equity_to_returns() -> None:
    equity = pd.Series(
        [100.0, 110.0, 99.0],
        index=pd.date_range("2024-01-01", periods=3),
    )

    returns = equity_to_returns(equity)

    assert len(returns) == 2
    assert round(returns.iloc[0], 4) == 0.1

