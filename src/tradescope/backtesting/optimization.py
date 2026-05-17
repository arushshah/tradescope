from __future__ import annotations

from copy import deepcopy

from sklearn.model_selection import ParameterGrid

from tradescope.config import BacktestConfig


def expand_param_grid(config: BacktestConfig) -> list[BacktestConfig]:
    params = config.strategy.params
    grid_keys = [key for key, value in params.items() if isinstance(value, list)]
    if not grid_keys:
        return [config]

    fixed_params = {key: value for key, value in params.items() if key not in grid_keys}
    grid_params = {key: params[key] for key in grid_keys}
    configs = []
    for combo in ParameterGrid(grid_params):
        combo_params = fixed_params | combo
        updated = deepcopy(config)
        updated.strategy.params = combo_params
        suffix = "_".join(f"{key}_{value}" for key, value in combo_params.items())
        updated.name = f"{config.name}_{suffix}"
        configs.append(updated)
    return configs
