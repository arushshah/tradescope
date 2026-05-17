from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradescope.universe import normalize_symbols, resolve_universe_symbols


class DataConfig(BaseModel):
    provider: str = "yfinance"
    raw_dir: Path = Path("data/raw")
    processed_dir: Path = Path("data/processed")
    component_dir: Path = Path("data/components")
    refresh: bool = False
    use_canonical_coverage: bool = True
    coverage_start: date | None = date(2010, 1, 1)
    coverage_end: date | None = date(2026, 1, 1)
    components: list[str] = Field(default_factory=lambda: ["ohlcv"])

    @field_validator("components")
    @classmethod
    def normalize_components(cls, components: list[str]) -> list[str]:
        cleaned = []
        for component in components:
            name = component.strip().lower()
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned or ["ohlcv"]


class UniverseConfig(BaseModel):
    preset_file: Path = Path("configs/universes.yaml")
    presets: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)

    @field_validator("symbols", "exclude")
    @classmethod
    def normalize_symbol_list(cls, symbols: list[str]) -> list[str]:
        return normalize_symbols(symbols)


class StrategyConfig(BaseModel):
    name: str | None = None
    path: Path | None = None
    module: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def has_name_or_path(self) -> "StrategyConfig":
        if not self.name and not self.path and not self.module:
            raise ValueError("strategy requires name, path, or module")
        return self


class SizingConfig(BaseModel):
    method: Literal["equal_weight", "all_in", "percent", "fixed_cash", "fixed_shares"] = (
        "equal_weight"
    )
    value: float | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "SizingConfig":
        if self.method in {"percent", "fixed_cash", "fixed_shares"} and self.value is None:
            raise ValueError(f"sizing.value is required for method '{self.method}'")
        return self


class ExecutionConfig(BaseModel):
    price: Literal["close", "open", "next_open"] = "close"


class RiskConfig(BaseModel):
    stop_loss: float | None = None
    take_profit: float | None = None
    trailing_stop: bool = False

    @field_validator("stop_loss", "take_profit")
    @classmethod
    def validate_positive_percent(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("risk percentages must be positive decimal values")
        return value

    @model_validator(mode="after")
    def validate_trailing_stop(self) -> "RiskConfig":
        if self.trailing_stop and self.stop_loss is None:
            raise ValueError("trailing_stop requires stop_loss")
        return self


class PortfolioConfig(BaseModel):
    init_cash: float = 100_000
    fees: float = 0.0
    slippage: float = 0.0
    direction: Literal["longonly", "shortonly", "both"] = "longonly"
    benchmark: str | None = "SPY"
    cash_sharing: bool = True
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)

    @field_validator("benchmark")
    @classmethod
    def normalize_benchmark(cls, benchmark: str | None) -> str | None:
        if benchmark is None:
            return None
        cleaned = benchmark.strip().upper()
        return cleaned or None


class ResultsConfig(BaseModel):
    output_dir: Path = Path("results")
    save_trades: bool = True
    save_equity_curve: bool = True
    save_plots: bool = True
    save_report: bool = False


class BacktestConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    symbols: list[str] = Field(default_factory=list)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    start: date
    end: date | None = None
    interval: str = "1d"
    data: DataConfig = Field(default_factory=DataConfig)
    strategy: StrategyConfig
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    results: ResultsConfig = Field(default_factory=ResultsConfig)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, symbols: list[str]) -> list[str]:
        return normalize_symbols(symbols)

    @model_validator(mode="after")
    def validate_dates(self) -> "BacktestConfig":
        if self.end and self.end <= self.start:
            raise ValueError("end must be after start")
        return self

    @model_validator(mode="after")
    def has_symbols_or_universe(self) -> "BacktestConfig":
        if not self.symbols and not self.universe.symbols and not self.universe.presets:
            raise ValueError("at least one symbol is required through symbols or universe")
        return self


def load_config(path: str | Path) -> BacktestConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    config = BacktestConfig.model_validate(raw)
    config.symbols = resolve_universe_symbols(
        config.symbols, config.universe, config_path.parent, config.data.processed_dir
    )
    return config
