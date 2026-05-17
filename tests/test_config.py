from pathlib import Path

import pytest
from pydantic import ValidationError

from tradescope.config.models import BacktestConfig
from tradescope.config import load_config
from tradescope.universe import load_universe_presets


def test_load_example_config() -> None:
    config = load_config(Path("configs/examples/ma_cross.yaml"))

    assert config.name == "ma_cross_spy"
    assert config.symbols == ["SPY"]
    assert config.data.provider == "yfinance"
    assert config.strategy.name == "ma_cross"
    assert config.portfolio.benchmark == "SPY"


def test_load_universe_preset_config(tmp_path) -> None:
    config_path = tmp_path / "universe_config.yaml"
    config_path.write_text(
        """
name: universe_test
universe:
  preset_file: configs/universes.yaml
  presets:
    - index_etfs
    - mega_cap_tech
  symbols:
    - COST
  exclude:
    - TSLA
start: "2023-01-01"
strategy:
  name: buy_hold
""",
        encoding="utf-8",
    )
    config = load_config(config_path)

    assert config.symbols == [
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "META",
        "GOOGL",
        "COST",
    ]
    assert "TSLA" not in config.symbols


def test_sp500_universe_preset_contains_current_large_members() -> None:
    presets = load_universe_presets(Path("configs/universes.yaml"))
    symbols = presets["sp500"].symbols

    assert len(symbols) == 503
    assert "AAPL" in symbols
    assert "MSFT" in symbols
    assert "BRK-B" in symbols


def test_exchange_universe_presets_contain_current_members() -> None:
    presets = load_universe_presets(Path("configs/universes.yaml"))
    nasdaq_symbols = presets["all_nasdaq"].symbols
    nyse_symbols = presets["all_nyse"].symbols

    assert len(nasdaq_symbols) > 5000
    assert len(nyse_symbols) > 2500
    assert "AAPL" in nasdaq_symbols
    assert "MSFT" in nasdaq_symbols
    assert "IBM" in nyse_symbols
    assert "JPM" in nyse_symbols


def test_load_config_supports_symbols_shorthand() -> None:
    config = load_config(Path("configs/examples/multi_symbol.yaml"))

    assert config.symbols == ["SPY", "QQQ", "DIA"]


def test_load_report_config() -> None:
    config = load_config(Path("configs/examples/ma_cross_report_smoke.yaml"))

    assert config.results.save_report


def test_trailing_stop_requires_stop_loss() -> None:
    raw = {
        "name": "invalid",
        "symbols": ["SPY"],
        "start": "2024-01-01",
        "strategy": {"name": "buy_hold"},
        "portfolio": {"risk": {"trailing_stop": True}},
    }

    with pytest.raises(ValidationError):
        BacktestConfig.model_validate(raw)
