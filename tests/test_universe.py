from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tradescope.data.universe_memberships import (
    UniverseMembership,
    UniverseMembershipStore,
    default_universe_memberships_path,
)
from tradescope.universe import (
    load_universe_presets,
    resolve_managed_universe,
    resolve_universe_symbols,
)


# ---------------------------------------------------------------------------
# resolve_managed_universe tests
# ---------------------------------------------------------------------------


def test_resolve_managed_universe_raises_without_processed_dir():
    with pytest.raises(ValueError, match="requires a data directory"):
        resolve_managed_universe("sp500", None)


def test_resolve_managed_universe_raises_when_store_missing(tmp_path: Path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    # No membership store file present
    with pytest.raises(ValueError, match="requires the membership store"):
        resolve_managed_universe("sp500", processed_dir)


def test_resolve_managed_universe_raises_when_universe_empty(tmp_path: Path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    store_path = default_universe_memberships_path(processed_dir)
    # Create an empty store by upserting nothing — just instantiate and write an
    # empty parquet via a zero-record upsert (store file won't exist until first upsert,
    # so we seed with a different universe to create the file).
    store = UniverseMembershipStore(store_path)
    store.upsert(
        [
            UniverseMembership(
                universe="other_universe",
                symbol="AAPL",
                start_date="2020-01-01",
                end_date=None,
                source="test",
                source_as_of_date="2026-01-01",
            )
        ]
    )
    # sp500 universe has no entries
    with pytest.raises(ValueError, match="has no symbols in the membership store"):
        resolve_managed_universe("sp500", processed_dir)


def test_resolve_managed_universe_returns_all_symbols(tmp_path: Path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    store_path = default_universe_memberships_path(processed_dir)
    store = UniverseMembershipStore(store_path)
    memberships = [
        UniverseMembership(
            universe="sp500",
            symbol="AAPL",
            start_date="2010-01-01",
            end_date=None,
            source="test",
            source_as_of_date="2026-01-01",
        ),
        UniverseMembership(
            universe="sp500",
            symbol="MSFT",
            start_date="2010-01-01",
            end_date="2020-01-01",
            source="test",
            source_as_of_date="2026-01-01",
        ),
        UniverseMembership(
            universe="sp500",
            symbol="GOOG",
            start_date="2015-01-01",
            end_date=None,
            source="test",
            source_as_of_date="2026-01-01",
        ),
    ]
    store.upsert(memberships)

    result = resolve_managed_universe("sp500", processed_dir)
    assert result == ["AAPL", "GOOG", "MSFT"]


# ---------------------------------------------------------------------------
# load_universe_presets source field test
# ---------------------------------------------------------------------------


def test_load_universe_presets_reads_source_field(tmp_path: Path):
    preset_file = tmp_path / "universes.yaml"
    preset_file.write_text(
        "sp500:\n"
        "  description: S&P 500 from membership store\n"
        "  source: membership_store\n",
        encoding="utf-8",
    )
    presets = load_universe_presets(preset_file)
    assert "sp500" in presets
    preset = presets["sp500"]
    assert preset.source == "membership_store"
    assert preset.symbols == []


# ---------------------------------------------------------------------------
# resolve_universe_symbols routing test
# ---------------------------------------------------------------------------


def test_resolve_universe_symbols_routes_managed_preset(tmp_path: Path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    # Seed the membership store with sp500 data
    store_path = default_universe_memberships_path(processed_dir)
    store = UniverseMembershipStore(store_path)
    store.upsert(
        [
            UniverseMembership(
                universe="sp500",
                symbol="AAPL",
                start_date="2010-01-01",
                end_date=None,
                source="test",
                source_as_of_date="2026-01-01",
            ),
            UniverseMembership(
                universe="sp500",
                symbol="MSFT",
                start_date="2010-01-01",
                end_date=None,
                source="test",
                source_as_of_date="2026-01-01",
            ),
        ]
    )

    # Write a preset file with a membership_store source
    preset_file = tmp_path / "universes.yaml"
    preset_file.write_text(
        "sp500:\n"
        "  description: S&P 500\n"
        "  source: membership_store\n",
        encoding="utf-8",
    )

    # Build a mock universe object
    universe = MagicMock()
    universe.symbols = []
    universe.exclude = []
    universe.presets = ["sp500"]
    universe.preset_file = str(preset_file)

    result = resolve_universe_symbols(
        explicit_symbols=[],
        universe=universe,
        base_dir=None,
        processed_dir=processed_dir,
    )
    assert "AAPL" in result
    assert "MSFT" in result
    assert len(result) == 2
