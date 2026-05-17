from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from tradescope.data.security_master import SecurityMaster


@dataclass(frozen=True)
class UniverseMembership:
    universe: str
    symbol: str
    start_date: str
    end_date: str | None
    source: str
    source_as_of_date: str
    notes: str | None = None


class UniverseMembershipStore:
    COLUMNS = ["universe", "symbol", "start_date", "end_date", "source", "source_as_of_date", "notes"]

    def __init__(self, path: Path) -> None:
        self.path = path

    def upsert(self, memberships: list[UniverseMembership]) -> int:
        records = self._read_records()
        for membership in memberships:
            key = _membership_key(membership.universe, membership.symbol, membership.source, membership.start_date)
            records[key] = {
                "universe": membership.universe,
                "symbol": membership.symbol.upper(),
                "start_date": membership.start_date,
                "end_date": membership.end_date,
                "source": membership.source,
                "source_as_of_date": membership.source_as_of_date,
                "notes": membership.notes,
            }
        self._write_records(records)
        return len(memberships)

    def all_symbols(self, universe: str) -> list[str]:
        """Return all symbols that have ever been in `universe`."""
        frame = self.read(universe=universe)
        if frame.empty:
            return []
        return sorted(frame["symbol"].unique().tolist())

    def members_on(self, universe: str, as_of_date: date) -> list[str]:
        frame = self.read(universe=universe)
        if frame.empty:
            return []
        as_of = pd.Timestamp(as_of_date)
        start_ok = pd.to_datetime(frame["start_date"]) <= as_of
        end_ok = frame["end_date"].isna() | (pd.to_datetime(frame["end_date"]) >= as_of)
        return sorted(frame[start_ok & end_ok]["symbol"].tolist())

    def read(self, universe: str | None = None) -> pd.DataFrame:
        records = self._read_records()
        if not records:
            return pd.DataFrame(columns=self.COLUMNS)
        frame = (
            pd.DataFrame(records.values())
            .reindex(columns=self.COLUMNS)
            .sort_values(["universe", "symbol"])
            .reset_index(drop=True)
        )
        if universe is not None:
            frame = frame[frame["universe"] == universe].reset_index(drop=True)
        return frame

    def _read_records(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        frame = pd.read_parquet(self.path)
        return {
            _membership_key(
                str(row["universe"]),
                str(row["symbol"]),
                str(row["source"]),
                str(row.get("start_date", "")),
            ): row.dropna().to_dict()
            for _, row in frame.iterrows()
        }

    def _write_records(self, records: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        (
            pd.DataFrame(records.values())
            .reindex(columns=self.COLUMNS)
            .sort_values(["universe", "symbol"])
            .to_parquet(self.path, index=False)
        )


def build_us_listed_from_security_master(
    master: SecurityMaster,
    as_of_date: str,
) -> list[UniverseMembership]:
    frame = master.read()
    canonical = frame[frame["provider"] == "security_master"]
    memberships = []
    for _, row in canonical.iterrows():
        symbol = str(row["symbol"])
        ipo_date = row.get("ipo_date") if "ipo_date" in row.index else None
        first_seen = row.get("first_seen") if "first_seen" in row.index else None

        raw_start = ipo_date if _has_value(ipo_date) else first_seen
        start_date = pd.Timestamp(raw_start).date().isoformat() if _has_value(raw_start) else as_of_date

        status = str(row.get("status", "active")).lower() if "status" in row.index else "active"
        end_date: str | None = None
        if status == "delisted":
            delisting_date = row.get("delisting_date") if "delisting_date" in row.index else None
            if _has_value(delisting_date):
                end_date = pd.Timestamp(delisting_date).date().isoformat()

        memberships.append(
            UniverseMembership(
                universe="us_listed",
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                source="security_master",
                source_as_of_date=as_of_date,
            )
        )
    return memberships


def default_universe_memberships_path(processed_dir: Path) -> Path:
    return processed_dir.parent / "universe_memberships.parquet"


def _membership_key(universe: str, symbol: str, source: str, start_date: str = "") -> str:
    return f"{universe}:{symbol.upper()}:{source}:{start_date}"


def _has_value(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except (TypeError, ValueError):
        return True
