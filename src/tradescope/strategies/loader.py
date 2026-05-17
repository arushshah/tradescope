from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

from tradescope.exceptions import StrategyError
from tradescope.strategies.base import StrategyFunction
from tradescope.strategies.builtin import BUILTIN_STRATEGIES


def load_strategy(
    name: str | None = None,
    path: Path | None = None,
    module: str | None = None,
) -> StrategyFunction:
    try:
        if path:
            return load_strategy_from_path(path)
        if module:
            return load_strategy_from_module(module)
        if name and name in BUILTIN_STRATEGIES:
            return BUILTIN_STRATEGIES[name]
    except ValueError as exc:
        raise StrategyError(str(exc)) from exc
    available = ", ".join(sorted(BUILTIN_STRATEGIES))
    raise StrategyError(f"unknown strategy '{name}'. Built-ins: {available}")


def load_strategy_from_path(path: Path) -> StrategyFunction:
    strategy_path = path.expanduser().resolve()
    if not strategy_path.exists():
        raise StrategyError(f"strategy file does not exist: {strategy_path}")

    spec = importlib.util.spec_from_file_location(strategy_path.stem, strategy_path)
    if not spec or not spec.loader:
        raise StrategyError(f"could not load strategy file: {strategy_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generate_signals = getattr(module, "generate_signals", None)
    if not callable(generate_signals):
        raise StrategyError("custom strategy must define callable generate_signals(data, params)")
    return generate_signals


def load_strategy_from_module(module_path: str) -> StrategyFunction:
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise StrategyError(f"could not import strategy module: {module_path}") from exc

    generate_signals = getattr(module, "generate_signals", None)
    if not callable(generate_signals):
        raise StrategyError("custom strategy module must define callable generate_signals(data, params)")
    return generate_signals
