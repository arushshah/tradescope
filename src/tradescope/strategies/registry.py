from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyMetadata:
    name: str
    description: str
    params: dict[str, Any]


STRATEGY_METADATA = {
    "bbands": StrategyMetadata(
        name="bbands",
        description="Bollinger Band mean reversion: enter below lower band, exit above middle band.",
        params={"window": 20, "alpha": 2.0},
    ),
    "buy_hold": StrategyMetadata(
        name="buy_hold",
        description="Buy on the first bar and hold until the end.",
        params={},
    ),
    "donchian": StrategyMetadata(
        name="donchian",
        description="Donchian breakout: enter on upper-channel breakout, exit on lower-channel break.",
        params={"entry_window": 55, "exit_window": 20},
    ),
    "ma_cross": StrategyMetadata(
        name="ma_cross",
        description="Moving-average crossover: enter when fast MA rises above slow MA.",
        params={"fast_window": 20, "slow_window": 100},
    ),
    "macd": StrategyMetadata(
        name="macd",
        description="MACD trend following: enter when MACD crosses above signal, exit below signal.",
        params={"fast_window": 12, "slow_window": 26, "signal_window": 9},
    ),
    "momentum_regime": StrategyMetadata(
        name="momentum_regime",
        description=(
            "Cross-sectional momentum: buy high-momentum symbols only when the regime symbol "
            "is above its long-term moving average."
        ),
        params={
            "momentum_window": 126,
            "trend_window": 100,
            "regime_symbol": "SPY",
            "regime_window": 200,
            "entry_quantile": 0.8,
            "exit_quantile": 0.6,
            "trade_regime_symbol": False,
        },
    ),
    "rebalance_momentum": StrategyMetadata(
        name="rebalance_momentum",
        description=(
            "Rebalanced cross-sectional momentum: on a fixed schedule, hold the top-N symbols by "
            "momentum while the regime filter is healthy."
        ),
        params={
            "momentum_window": 126,
            "top_n": 20,
            "rebalance": "monthly",
            "regime_symbol": "SPY",
            "regime_window": 200,
            "use_regime_filter": True,
            "trend_window": 100,
            "use_trend_filter": True,
            "trade_regime_symbol": False,
            "exit_on_regime_fail": True,
        },
    ),
    "rsi": StrategyMetadata(
        name="rsi",
        description="RSI mean reversion: enter below threshold, exit above threshold.",
        params={"window": 14, "entry_threshold": 30, "exit_threshold": 60},
    ),
}


def list_strategy_metadata() -> list[StrategyMetadata]:
    return [STRATEGY_METADATA[name] for name in sorted(STRATEGY_METADATA)]


def describe_strategy(name: str) -> StrategyMetadata | None:
    return STRATEGY_METADATA.get(name)
