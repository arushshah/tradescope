from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class UniversePreset:
    name: str
    description: str
    symbols: list[str]


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def normalize_symbols(symbols: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for symbol in symbols:
        cleaned = normalize_symbol(symbol)
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return normalized


def load_universe_presets(path: Path) -> dict[str, UniversePreset]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    presets: dict[str, UniversePreset] = {}
    for name, value in raw.items():
        if isinstance(value, list):
            description = ""
            symbols = value
        elif isinstance(value, dict):
            description = str(value.get("description", ""))
            symbols = value.get("symbols", [])
        else:
            raise ValueError(f"universe preset '{name}' must be a mapping or list")

        if not isinstance(symbols, list):
            raise ValueError(f"universe preset '{name}' symbols must be a list")

        presets[name] = UniversePreset(
            name=name,
            description=description,
            symbols=normalize_symbols([str(symbol) for symbol in symbols]),
        )
    return presets


def resolve_preset_file(path: Path, base_dir: Path | None = None) -> Path:
    if path.is_absolute():
        return path

    candidates = []
    if base_dir is not None:
        candidates.append(base_dir / path)
    candidates.append(path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_universe_symbols(
    explicit_symbols: list[str],
    universe: Any,
    base_dir: Path | None = None,
) -> list[str]:
    symbols = normalize_symbols(explicit_symbols)
    universe_symbols = normalize_symbols(list(getattr(universe, "symbols", [])))
    exclude = set(normalize_symbols(list(getattr(universe, "exclude", []))))
    preset_names = list(getattr(universe, "presets", []))
    preset_file = resolve_preset_file(Path(getattr(universe, "preset_file")), base_dir)

    if preset_names:
        presets = load_universe_presets(preset_file)
        for preset_name in preset_names:
            if preset_name not in presets:
                raise ValueError(f"unknown universe preset '{preset_name}' in {preset_file}")
            symbols.extend(presets[preset_name].symbols)

    symbols.extend(universe_symbols)
    resolved = [symbol for symbol in normalize_symbols(symbols) if symbol not in exclude]
    if not resolved:
        raise ValueError("at least one symbol is required through symbols or universe")
    return resolved
