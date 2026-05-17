from tradescope.backtesting.optimization import expand_param_grid
from tradescope.config import load_config


def test_expand_param_grid() -> None:
    config = load_config("configs/examples/ma_cross.yaml")
    config.strategy.params = {"fast_window": [10, 20], "slow_window": [50, 100]}

    expanded = expand_param_grid(config)

    assert len(expanded) == 4
    assert expanded[0].strategy.params == {"fast_window": 10, "slow_window": 50}

