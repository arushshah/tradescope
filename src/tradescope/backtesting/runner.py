from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import date

import pandas as pd

from tradescope.config import BacktestConfig
from tradescope.data.store import (
    MarketDataEntry,
    MarketDataStore,
    combine_frames,
    entry_end_date,
    entry_start_date,
    trim_frame,
)
from tradescope.data.symbol_mapping import yfinance_symbol_candidates
from tradescope.data.universe_memberships import UniverseMembershipStore, default_universe_memberships_path
from tradescope.data.yfinance_provider import YFinanceProvider
from tradescope.data.validation import validate_ohlcv
from tradescope.exceptions import DataError, NoDataError, StrategyError, TradeScopeError
from tradescope.results.store import ResultStore
from tradescope.strategies.base import BacktestContext
from tradescope.strategies.loader import load_strategy


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    run_dir: str
    stats: pd.Series


class BacktestRunner:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def run(self) -> BacktestResult:
        data = self._load_data()
        close = make_close_matrix(data)
        strategy = load_strategy(
            self.config.strategy.name,
            self.config.strategy.path,
            self.config.strategy.module,
        )
        if _strategy_accepts_context(strategy):
            membership_store = UniverseMembershipStore(
                default_universe_memberships_path(self.config.data.processed_dir)
            )
            signals = strategy(data, self.config.strategy.params, BacktestContext(membership_store))
        else:
            signals = strategy(data, self.config.strategy.params)
        validate_signals(signals)

        portfolio = self._build_portfolio(data, close, signals)
        store = ResultStore(self.config.results.output_dir)
        run_dir, run_id = store.create_run_dir(self.config.name)
        stats = portfolio.stats(silence_warnings=True)
        stats = self._add_benchmark_stats(stats, data)
        benchmark_equity = self._benchmark_equity(data)

        store.write_config(run_dir, self.config)
        store.write_stats(run_dir, stats)
        equity_curve = portfolio.value()
        if self.config.results.save_equity_curve:
            store.write_equity_curve(run_dir, equity_curve)
        store.write_signals(
            run_dir,
            {
                "entries": align_like(signals["entries"], close),
                "exits": align_like(signals["exits"], close),
                "short_entries": align_like(signals.get("short_entries"), close)
                if signals.get("short_entries") is not None
                else None,
                "short_exits": align_like(signals.get("short_exits"), close)
                if signals.get("short_exits") is not None
                else None,
            },
        )
        if benchmark_equity is not None:
            store.write_benchmark_equity(run_dir, benchmark_equity)
            store.write_benchmark_returns(run_dir, benchmark_equity)
        if self.config.results.save_plots:
            store.write_plots(run_dir, equity_curve)
        if self.config.results.save_report:
            store.write_report(run_dir, equity_curve, benchmark_equity, self.config.name)
        if self.config.results.save_trades:
            store.write_trades(run_dir, portfolio)
        return BacktestResult(run_id=run_id, run_dir=str(run_dir), stats=stats)

    def _load_data(self, symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
        if self.config.data.provider != "yfinance":
            raise DataError(f"unsupported data provider: {self.config.data.provider}")

        requested_symbols = symbols or self.config.symbols
        provider = YFinanceProvider()
        store = MarketDataStore(self.config.data.raw_dir, self.config.data.processed_dir)
        load_start, load_end = self._data_load_range()
        data: dict[str, pd.DataFrame] = {}
        skipped_symbols: list[str] = []

        for symbol in requested_symbols:
            unavailable = store.unavailable_entry(
                provider.name,
                symbol,
                load_start,
                load_end,
                self.config.interval,
            )
            if unavailable is not None:
                skipped_symbols.append(symbol)
                continue
            if not self.config.data.refresh:
                processed = store.read_processed(
                    provider.name,
                    symbol,
                    self.config.start,
                    self.config.end,
                    self.config.interval,
                )
                if processed is not None:
                    data[symbol] = processed
                    continue
            try:
                loaded = self._load_symbol_data(symbol, provider, store, load_start, load_end)
                data[symbol] = trim_frame(loaded, self.config.start, self.config.end)
            except NoDataError as exc:
                store.mark_unavailable(
                    provider.name,
                    symbol,
                    load_start,
                    load_end,
                    self.config.interval,
                    str(exc),
                )
                skipped_symbols.append(symbol)

        if skipped_symbols:
            preview = ", ".join(skipped_symbols[:20])
            suffix = "" if len(skipped_symbols) <= 20 else f", ... +{len(skipped_symbols) - 20} more"
            print(f"Skipped unavailable symbol(s): {len(skipped_symbols)} ({preview}{suffix})")
        if not data:
            raise DataError("no market data loaded; all requested symbols were unavailable")

        return {symbol: data[symbol] for symbol in requested_symbols if symbol in data}

    def _data_load_range(self) -> tuple[date, date | None]:
        if not self.config.data.use_canonical_coverage:
            return self.config.start, self.config.end

        start = self.config.data.coverage_start or self.config.start
        if start > self.config.start:
            start = self.config.start
        return start, latest_end(self.config.data.coverage_end, self.config.end)

    def _load_symbol_data(
        self,
        symbol: str,
        provider: YFinanceProvider,
        store: MarketDataStore,
        load_start: date,
        load_end: date | None,
    ) -> pd.DataFrame:
        if self.config.data.refresh or load_end is None:
            return self._fetch_symbol_span(symbol, provider, store, load_start, load_end)

        entries = store.find_overlapping_entries(
            "processed",
            provider.name,
            symbol,
            load_start,
            load_end,
            self.config.interval,
        )
        if not entries:
            return self._fetch_symbol_span(symbol, provider, store, load_start, load_end)

        existing_frames = [store.read_entry(entry) for entry in entries]
        fetched_frames = [
            self._fetch_symbol_span(symbol, provider, store, fetch_start, fetch_end)
            for fetch_start, fetch_end in missing_ranges(entries, load_start, load_end)
        ]
        merged = combine_frames([*existing_frames, *fetched_frames])
        merged_start = min([load_start, *[entry_start_date(entry) for entry in entries]])
        merged_end = latest_end(load_end, *[entry_end_date(entry) for entry in entries])
        store.write_processed(provider.name, symbol, merged_start, merged_end, self.config.interval, merged)
        return trim_frame(merged, load_start, load_end)

    def _fetch_symbol_span(
        self,
        symbol: str,
        provider: YFinanceProvider,
        store: MarketDataStore,
        start: date,
        end: date | None,
    ) -> pd.DataFrame:
        last_error: NoDataError | None = None
        mapped_symbol = store.symbol_map.resolve(provider.name, symbol)
        for provider_symbol in yfinance_symbol_candidates(symbol, mapped_symbol):
            try:
                raw = provider.fetch_raw([provider_symbol], start, end, self.config.interval)[provider_symbol]
                break
            except NoDataError as exc:
                last_error = exc
        else:
            raise last_error or NoDataError(f"{symbol}: yfinance returned no rows")

        store.write_raw(provider.name, provider_symbol, start, end, self.config.interval, raw)
        processed = validate_ohlcv(symbol, provider.normalize(symbol, raw))
        store.write_processed(provider.name, symbol, start, end, self.config.interval, processed)
        if provider_symbol != symbol.upper():
            store.symbol_map.upsert_active(
                symbol,
                provider.name,
                provider_symbol,
                reason="resolved during OHLCV fetch",
            )
        return processed

    def _build_portfolio(self, data: dict[str, pd.DataFrame], close: pd.DataFrame, signals: dict):
        try:
            import vectorbt as vbt
        except ImportError as exc:
            raise TradeScopeError(
                "vectorbt is required to run backtests. Install with a Python version supported "
                "by vectorbt, usually Python 3.10-3.12."
            ) from exc

        direction = self.config.portfolio.direction
        entries = align_like(signals["entries"], close)
        exits = align_like(signals["exits"], close)

        kwargs = {
            "close": close,
            "entries": entries,
            "exits": exits,
            "price": self._execution_price(data, close),
            "open": make_price_matrix(data, "open").reindex(index=close.index, columns=close.columns),
            "high": make_price_matrix(data, "high").reindex(index=close.index, columns=close.columns),
            "low": make_price_matrix(data, "low").reindex(index=close.index, columns=close.columns),
            "init_cash": self.config.portfolio.init_cash,
            "fees": self.config.portfolio.fees,
            "slippage": self.config.portfolio.slippage,
            "freq": self.config.interval,
            "cash_sharing": self.config.portfolio.cash_sharing,
        }
        kwargs.update(self._sizing_kwargs(close, entries, signals))
        kwargs.update(self._risk_kwargs())

        if direction == "longonly":
            kwargs["direction"] = "longonly"
        elif direction == "shortonly":
            kwargs["direction"] = "shortonly"
        else:
            kwargs["short_entries"] = align_like(signals.get("short_entries"), close)
            kwargs["short_exits"] = align_like(signals.get("short_exits"), close)

        return vbt.Portfolio.from_signals(**kwargs)

    def _execution_price(
        self,
        data: dict[str, pd.DataFrame],
        close: pd.DataFrame,
    ) -> pd.DataFrame:
        price_mode = self.config.portfolio.execution.price
        if price_mode == "close":
            return close

        open_price = make_price_matrix(data, "open").reindex(index=close.index, columns=close.columns)
        if price_mode == "open":
            return open_price
        if price_mode == "next_open":
            return open_price.shift(-1)
        raise TradeScopeError(f"unsupported execution price: {price_mode}")

    def _risk_kwargs(self) -> dict:
        risk = self.config.portfolio.risk
        kwargs = {}
        if risk.stop_loss is not None:
            kwargs["sl_stop"] = risk.stop_loss
        if risk.take_profit is not None:
            kwargs["tp_stop"] = risk.take_profit
        if risk.trailing_stop:
            kwargs["sl_trail"] = True
        return kwargs

    def _sizing_kwargs(self, close: pd.DataFrame, entries: pd.DataFrame, signals: dict) -> dict:
        sizing = self.config.portfolio.sizing
        if sizing.method == "all_in":
            return {"size": 1.0, "size_type": "percent"}
        if sizing.method == "equal_weight":
            active_counts = entries.sum(axis=1).replace(0, float("nan"))
            size = entries.astype(float).div(active_counts, axis=0).fillna(0.0)
            return {"size": size, "size_type": "percent"}
        if sizing.method == "percent":
            return {"size": float(sizing.value), "size_type": "percent"}
        if sizing.method == "fixed_cash":
            return {"size": float(sizing.value), "size_type": "value"}
        if sizing.method == "fixed_shares":
            return {"size": float(sizing.value), "size_type": "amount"}
        raise TradeScopeError(f"unsupported sizing method: {sizing.method}")

    def _add_benchmark_stats(self, stats: pd.Series, data: dict[str, pd.DataFrame]) -> pd.Series:
        benchmark = self.config.portfolio.benchmark
        if not benchmark:
            return stats

        benchmark_equity = self._benchmark_equity(data)
        if benchmark_equity is None:
            return stats
        close = benchmark_equity.dropna()
        if close.empty:
            return stats

        benchmark_return = ((close.iloc[-1] / close.iloc[0]) - 1) * 100
        enriched = stats.copy()
        enriched.loc["Benchmark Symbol"] = benchmark
        enriched.loc["Benchmark Total Return [%]"] = benchmark_return
        return enriched

    def _benchmark_equity(self, data: dict[str, pd.DataFrame]) -> pd.Series | None:
        benchmark = self.config.portfolio.benchmark
        if not benchmark:
            return None
        if benchmark in data:
            benchmark_data = data[benchmark]
        else:
            benchmark_data = self._load_data([benchmark])[benchmark]
        close = benchmark_data["close"].dropna()
        if close.empty:
            return None
        return (close / close.iloc[0] * self.config.portfolio.init_cash).rename(benchmark)


def make_close_matrix(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return make_price_matrix(data, "close").dropna(how="all")


def make_price_matrix(data: dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    return pd.concat({symbol: frame[column] for symbol, frame in data.items()}, axis=1)


def validate_signals(signals: dict) -> None:
    if not isinstance(signals, dict):
        raise StrategyError("strategy must return a dict")
    if "entries" not in signals or "exits" not in signals:
        raise StrategyError("strategy output must include entries and exits")
    if signals["entries"] is None or signals["exits"] is None:
        raise StrategyError("strategy entries and exits cannot be None")


def missing_ranges(
    entries: list[MarketDataEntry],
    start: date,
    end: date,
) -> list[tuple[date, date]]:
    ranges = []
    cursor = start
    for entry in sorted(entries, key=entry_start_date):
        entry_start = max(entry_start_date(entry), start)
        entry_end = entry_end_date(entry)
        if entry_end is None:
            return ranges
        entry_end = min(entry_end, end)
        if entry_end <= start or entry_start >= end:
            continue
        if entry_start > cursor:
            ranges.append((cursor, entry_start))
        if entry_end > cursor:
            cursor = entry_end
    if cursor < end:
        ranges.append((cursor, end))
    return ranges


def latest_end(*ends: date | None) -> date | None:
    concrete = [end for end in ends if end is not None]
    if not concrete:
        return None
    return max(concrete)


def align_like(value, close: pd.DataFrame) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame(False, index=close.index, columns=close.columns)
    frame = value.to_frame() if isinstance(value, pd.Series) else pd.DataFrame(value)
    return frame.reindex(index=close.index, columns=close.columns).astype("boolean").fillna(False).astype(bool)


def align_numeric_like(value, close: pd.DataFrame) -> pd.DataFrame:
    frame = value.to_frame() if isinstance(value, pd.Series) else pd.DataFrame(value)
    return frame.reindex(index=close.index, columns=close.columns).astype(float)


def _strategy_accepts_context(strategy) -> bool:
    """Return True if the strategy function declares a third (context) parameter."""
    try:
        sig = inspect.signature(strategy)
        return len(sig.parameters) >= 3
    except (ValueError, TypeError):
        return False
