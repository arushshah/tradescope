import pandas as pd

from tradingv2.visualization import write_drawdown_plot, write_equity_plot


def test_write_basic_plots(tmp_path) -> None:
    equity = pd.Series(
        [100.0, 110.0, 105.0],
        index=pd.date_range("2024-01-01", periods=3),
    )

    equity_path = write_equity_plot(equity, tmp_path / "equity.png")
    drawdown_path = write_drawdown_plot(equity, tmp_path / "drawdown.png")

    assert equity_path.exists()
    assert drawdown_path.exists()
