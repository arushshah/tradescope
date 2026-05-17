from tradescope.strategies.builtin.bbands import generate_signals as bbands
from tradescope.strategies.builtin.buy_hold import generate_signals as buy_hold
from tradescope.strategies.builtin.donchian import generate_signals as donchian
from tradescope.strategies.builtin.ma_cross import generate_signals as ma_cross
from tradescope.strategies.builtin.macd import generate_signals as macd
from tradescope.strategies.builtin.momentum_regime import generate_signals as momentum_regime
from tradescope.strategies.builtin.rebalance_momentum import generate_signals as rebalance_momentum
from tradescope.strategies.builtin.rsi import generate_signals as rsi

BUILTIN_STRATEGIES = {
    "bbands": bbands,
    "buy_hold": buy_hold,
    "donchian": donchian,
    "ma_cross": ma_cross,
    "macd": macd,
    "momentum_regime": momentum_regime,
    "rebalance_momentum": rebalance_momentum,
    "rsi": rsi,
}

__all__ = ["BUILTIN_STRATEGIES"]
