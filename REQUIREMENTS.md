# TradeScope Backtesting Tool Requirements

## Product Goal

Build a fast, extensible backtesting and research tool for equities using `vectorbt`, optimized first for personal research speed and structured so it can later support production-grade workflows, dashboards, additional markets, and more robust execution assumptions.

## Initial Scope

TradeScope starts as a CLI-driven Python research tool. It should make it easy to fetch equity data, plug in custom strategy logic, run repeatable vectorbt backtests, compare results, and save artifacts for later analysis.

The first implementation should prioritize a clean core architecture over a polished UI. Dashboards and production concerns should be anticipated in the design, but not allowed to slow the MVP.

## Market Scope

### MVP Market

- US equities.
- Daily OHLCV data.
- Long-only and long/flat strategies.
- Single-symbol and multi-symbol backtests.

### Future Markets

The system should be designed so the following can be added without rewriting the backtesting core:

- Crypto.
- Forex.
- Futures.
- Options-derived signals or option strategy simulation.
- Intraday equities.

Market-specific concerns should live behind data source, calendar, instrument metadata, and execution configuration interfaces.

## Interface Scope

### MVP Interface

The first interface is a CLI.

Expected command families:

```bash
tradescope data fetch
tradescope backtest run
tradescope backtest sweep
tradescope results show
tradescope results compare
```

The CLI should accept config files so experiments are reproducible.

Example:

```bash
tradescope backtest run --config configs/examples/ma_cross.yaml
```

### Future Interface

- Streamlit or web dashboard for interactive research.
- Dashboard should consume the same experiment outputs and core APIs used by the CLI.
- No dashboard-only business logic.

## Data Requirements

### MVP Data Source

Use `yfinance` for equities data.

Capabilities:

- Fetch one or more tickers.
- Support configurable date ranges.
- Support daily interval first.
- Save data locally.
- Reuse processed data unless refresh is requested.
- Store raw provider data and processed normalized data as Parquet by default.
- Normalize into a consistent internal OHLCV schema.

Internal schema:

```text
symbol
timestamp
open
high
low
close
adj_close
volume
source
interval
```

### Data Extensibility

Data providers should implement a common interface so future providers can be added:

- Polygon.
- Alpaca.
- Interactive Brokers.
- Binance or other crypto exchanges.
- Local CSV / Parquet.
- Vendor data dumps.

Provider responsibilities:

- Fetch raw data.
- Normalize fields.
- Handle source-specific quirks.
- Return data in the internal schema.

### Data Quality

The system should detect or handle:

- Missing values.
- Duplicate timestamps.
- Non-monotonic timestamps.
- Timezone consistency.
- Empty provider responses.
- Symbols with partial data.
- Adjusted versus unadjusted prices.

## Strategy Requirements

Custom strategies are a core requirement, not an afterthought.

### Strategy Model

A strategy should be a Python object or module that receives market data and parameters, then returns entries and exits compatible with vectorbt.

At minimum, a strategy should be able to return:

```python
entries
exits
```

Future advanced strategies may return:

```python
short_entries
short_exits
size
price
fees
slippage
metadata
```

### Built-In MVP Strategies

Include a few simple built-ins for smoke testing and examples:

- Moving average crossover.
- RSI threshold.
- Buy and hold benchmark.

### Custom Strategy Loading

The CLI should support loading custom strategies from a Python path.

Example:

```bash
tradescope backtest run \
  --strategy-path strategies/my_strategy.py \
  --config configs/my_strategy.yaml
```

Custom strategies should follow a clear contract, for example:

```python
def generate_signals(data, params):
    return {
        "entries": entries,
        "exits": exits,
    }
```

The exact contract can evolve, but the MVP should keep it simple and documented.

## Backtesting Requirements

### Engine

Use `vectorbt` as the primary engine.

MVP implementation should use:

- `Portfolio.from_signals` for signal-based strategies.
- Equal-weight percent sizing by default across symbols that receive entry signals on the same bar.

Future implementation may support:

- `Portfolio.from_orders` for detailed order simulation.
- More advanced portfolio construction.
- Rebalancing.
- Multi-strategy portfolios.

### Backtest Config

Backtests should be driven by explicit configuration.

Config fields should include:

```yaml
name: ma_cross_spy
symbols:
  - SPY
start: "2015-01-01"
end: "2025-01-01"
interval: "1d"
data:
  provider: yfinance
  raw_dir: data/raw
  processed_dir: data/processed
  refresh: false
strategy:
  name: ma_cross
  params:
    fast_window: 20
    slow_window: 100
portfolio:
  init_cash: 100000
  fees: 0.001
  slippage: 0.0005
  direction: longonly
  benchmark: SPY
  cash_sharing: true
  sizing:
    method: equal_weight
results:
  output_dir: results
```

### Execution Assumptions

MVP:

- Initial cash.
- Fees.
- Slippage.
- Long-only mode.
- Configurable execution price: close, open, or next open.
- Optional stop loss, take profit, and trailing stop using vectorbt stops.

Future:

- Market-on-close versus market-on-open assumptions.
- Position sizing.
- Leverage.
- Shorting.
- Borrow costs.
- Cash sharing.
- Rebalancing.
- Corporate action handling.

## Optimization Requirements

### MVP

Support basic parameter sweeps for built-in and custom strategies.

Example:

```yaml
strategy:
  name: ma_cross
  params:
    fast_window: [10, 20, 50]
    slow_window: [100, 150, 200]
```

The system should:

- Generate parameter combinations.
- Run backtests.
- Rank results by a selected metric.
- Save a table of results.

### Future

- Walk-forward testing.
- Train/test splits.
- Out-of-sample validation.
- Random search.
- Bayesian optimization.
- Robustness checks.
- Sensitivity analysis.

## Analytics Requirements

MVP metrics:

- Total return.
- Annualized return.
- Sharpe ratio.
- Sortino ratio, if available.
- Max drawdown.
- Calmar ratio, if available.
- Win rate.
- Number of trades.
- Exposure time.
- Benchmark return.

Future metrics:

- Rolling Sharpe.
- Rolling drawdown.
- Monthly returns.
- Yearly returns.
- Alpha/beta versus benchmark.
- Trade-level distribution.
- Per-symbol contribution.
- Regime-based performance.

## Results And Artifacts

Each backtest run should create a run directory containing:

```text
results/
  <run_id>/
    config.yaml
    summary.json
    stats.csv
    trades.csv
    equity_curve.csv
    plots/
```

MVP artifacts:

- Resolved config.
- Summary metrics.
- Portfolio stats.
- Trades, where available.
- Equity curve.
- Equity curve and drawdown plots.
- Sweep CSV and manifest for parameter sweeps.

Future artifacts:

- HTML report.
- Interactive charts.
- Tearsheet.
- Dashboard-ready dataset.
- Experiment comparison database.

## Architecture Requirements

Proposed package layout:

```text
src/
  tradescope/
    cli.py
    config/
    data/
      base.py
      yfinance_provider.py
      store.py
      validation.py
    strategies/
      base.py
      builtin/
        ma_cross.py
        rsi.py
        buy_hold.py
      loader.py
    backtesting/
      engine.py
      runner.py
      optimization.py
    analytics/
      metrics.py
      reports.py
    results/
      store.py
      compare.py
    visualization/
      plots.py
```

Design principles:

- Keep vectorbt-specific logic mostly inside `backtesting/`.
- Keep data provider quirks inside `data/`.
- Keep strategy loading separate from strategy execution.
- Make CLI commands thin wrappers around reusable Python APIs.
- Persist resolved configs for reproducibility.
- Prefer simple config-driven workflows over heavyweight abstractions.

## Testing Requirements

MVP tests:

- Config parsing.
- yfinance provider normalization using mocked data.
- Built-in strategy signal generation.
- Backtest runner smoke test.
- Result artifact writing.
- Parameter sweep expansion.

Future tests:

- Golden backtest fixtures.
- Regression tests for metrics.
- Integration tests with stored sample market data.
- CLI command tests.
- Strategy contract validation.

## Non-Goals For MVP

- Live trading.
- Broker integration.
- Full web dashboard.
- Intraday execution simulation.
- Options backtesting.
- Complex portfolio optimization.
- Production deployment.
- Distributed compute.

## Implementation Phases

### Phase 1: Foundation

- Create Python project structure.
- Add dependencies.
- Add config schema.
- Add CLI skeleton.
- Add yfinance data provider.
- Add local raw and processed data storage.

### Phase 2: First Backtest

- Add strategy contract.
- Add moving average crossover strategy.
- Add vectorbt runner.
- Add run artifact storage.
- Add example config.
- Add smoke tests.

### Phase 3: Custom Strategies

- Add custom strategy loader.
- Validate strategy outputs.
- Add custom strategy example.
- Add docs for strategy authoring.

### Phase 4: Research Workflow

- Add parameter sweeps.
- Add result ranking.
- Add comparison command.
- Add benchmark support.
- Add basic plots.

### Phase 5: Production Readiness Prep

- Strengthen data validation.
- Add richer test fixtures.
- Add experiment metadata.
- Improve error messages.
- Add logging.
- Prepare dashboard-compatible result format.

### Phase 6: Dashboard

- Add Streamlit dashboard.
- Browse previous runs.
- Visualize equity curves and drawdowns.
- Compare strategy results.
- Inspect trades.

## Open Questions

- Should MVP support only daily bars, or should hourly bars be included early?
- Should benchmark default to `SPY`, or should it be required per config?
- Should custom strategies be loaded by file path, Python module path, or both?
- Should local data storage use Parquet only, or introduce DuckDB later?
- Should result metadata live as files only at first, or should we introduce SQLite/DuckDB early?
- Should we use Pydantic models for config validation from the beginning?
