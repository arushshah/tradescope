# TradeScope

TradeScope is a CLI-first equity backtesting and research toolkit built around [`vectorbt`](https://vectorbt.dev/). It is designed for fast personal research today, while keeping the architecture clean enough to grow into dashboards, richer experiment tracking, and production-grade workflows later.

For a full technical handbook, read [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md). That guide explains the architecture, libraries, concepts, and extension points in much more depth.

For the running strategy notebook, read [STRATEGY_RESEARCH_LOG.md](STRATEGY_RESEARCH_LOG.md).

## What It Does

TradeScope lets you:

- Fetch daily equity data with `yfinance`.
- Store raw provider data and processed OHLCV data locally as Parquet.
- Run signal-based backtests with `vectorbt`.
- Use built-in strategies or custom Python strategy files.
- Configure fees, slippage, sizing, execution price, stops, and benchmarks.
- Run parameter sweeps and rank results.
- Run train/test split backtests.
- Generate result artifacts, plots, trade records, benchmark series, and optional QuantStats HTML reports.
- Inspect and compare saved results from the command line.
- Validate stored or fetched data before running research.

## Project Status

This is an active research tool, not a production trading system.

Current focus:

- US equities.
- Daily OHLCV bars.
- CLI workflows.
- Long-only `entries` / `exits` strategy contract.
- Library-first implementation.

Not currently included:

- Live trading.
- Broker integration.
- Dashboard UI.
- Persistent experiment database.
- Full short-strategy contract.
- Intraday execution modeling.

## Library-First Principle

TradeScope should stay a research shell around proven libraries, not grow into a homemade backtesting framework.

Preferred responsibilities:

- `vectorbt`: indicators, portfolio simulation, stats, drawdown helpers.
- `yfinance`: initial market data provider.
- `pandas`: dataframe and time-series operations.
- `pyarrow`: Parquet storage support.
- `pydantic`: config validation.
- `click`: CLI.
- `scikit-learn`: parameter-grid expansion.
- `quantstats`: optional HTML reports.
- `pytest` and `ruff`: tests and linting.

Custom code should mainly handle orchestration, strategy loading, config glue, CLI commands, and artifact layout.

## Repository Layout

```text
tradescope/
  README.md
  DEVELOPMENT_GUIDE.md
  REQUIREMENTS.md
  pyproject.toml
  configs/examples/          Example backtest configs
  data/raw/                  Raw provider data
  data/processed/            Normalized OHLCV data used by backtests
  results/                   Backtest outputs
  strategies/                User custom strategies
  src/tradescope/
    cli.py                   CLI entrypoint
    config/                  Pydantic config models
    data/                    Data providers, storage, validation
    strategies/              Built-ins, registry, custom loading
    backtesting/             vectorbt runner and optimization
    results/                 Artifact writing and comparisons
    visualization/           Plot helpers
    analytics/               QuantStats report helpers
  tests/                     Pytest suite
```

## Requirements

Use Python 3.12 for now. `vectorbt` and its numeric stack are more reliable on Python 3.10-3.12 than on newer Python releases.

The local machine currently has Python 3.12.2 available through `pyenv`.

## Setup

Create a virtualenv:

```bash
PYENV_VERSION=3.12.2 python -m pip install virtualenv
PYENV_VERSION=3.12.2 python -m virtualenv .venv
source .venv/bin/activate
```

Install the project in editable mode with development tools:

```bash
python -m pip install -e ".[dev]"
```

Install optional HTML report support:

```bash
python -m pip install -e ".[dev,reports]"
```

You can also run commands without activating the environment:

```bash
.venv/bin/tradescope --help
```

All command examples in this README use `.venv/bin/tradescope` so they work even when the virtualenv is not activated. If your virtualenv is activated, `tradescope ...` is equivalent.

Values in angle brackets are placeholders. For example, replace `results/<run_id>` with a real run directory printed by `backtest run`, such as `results/ma_cross_spy_20260514_120000`.

## Quickstart

Run a small moving-average crossover backtest:

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross_smoke.yaml
```

Inspect the output folder printed by the command:

```bash
.venv/bin/tradescope results inspect results/<run_id>
```

Run a parameter sweep:

```bash
.venv/bin/tradescope backtest sweep --config configs/examples/ma_cross_sweep_smoke.yaml --top-n 5
```

Show the best run from the sweep:

```bash
.venv/bin/tradescope results best results/ma_cross_spy_sweep_smoke_sweep.csv
```

Validate data for a config:

```bash
.venv/bin/tradescope data validate --config configs/examples/ma_cross_smoke.yaml
```

## How To Use

### 1. Pick Or Create A Config

Example configs live in [configs/examples](configs/examples).

Useful starters:

```text
data_sp500_canonical.yaml S&P 500 canonical data collection config
data_all_us_canonical.yaml Combined Nasdaq + NYSE canonical data collection config
ma_cross_smoke.yaml        Small SPY smoke test
ma_cross.yaml              Longer MA crossover run
ma_cross_sweep_smoke.yaml  Parameter sweep example
ma_cross_risk_smoke.yaml   Execution/risk controls example
ma_cross_report_smoke.yaml QuantStats report example
rsi.yaml                   RSI strategy
rsi_sweep.yaml             RSI parameter sweep
bbands.yaml                Bollinger Bands strategy
macd.yaml                  MACD strategy
donchian.yaml              Donchian breakout strategy
momentum_regime_smoke.yaml Cross-sectional momentum with market regime
momentum_regime_next_open.yaml Realistic next-open momentum smoke test
momentum_regime_sp500_next_open.yaml S&P 500 momentum regime test
momentum_regime_sp500_strict.yaml Stricter S&P 500 momentum entry test
momentum_regime_sp500_12m.yaml 12-month S&P 500 momentum test
rebalance_momentum_sp500_top20_6m.yaml Monthly top-20 S&P 500 momentum test
rebalance_momentum_sp500_top50_6m.yaml Monthly top-50 S&P 500 momentum test
rebalance_momentum_sp500_top20_12m.yaml Monthly top-20 12-month momentum test
rebalance_momentum_sp500_top50_12m.yaml Monthly top-50 12-month momentum test
custom_strategy.yaml       Custom strategy file example
multi_symbol.yaml          Multi-symbol example
universe_preset.yaml       Universe preset include/exclude example
```

### 2. Run The Backtest

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross.yaml
```

Each run creates a directory under `results/`.

### 3. Inspect The Results

```bash
.venv/bin/tradescope results inspect results/<run_id>
```

Artifacts may include:

```text
config.yaml
stats.csv
summary.json
equity_curve.csv
benchmark_equity.csv
benchmark_returns.csv
trades.csv
signals/entries.csv
signals/exits.csv
report.html
plots/equity_curve.png
plots/drawdown.png
```

### 4. Compare Runs

```bash
.venv/bin/tradescope results compare results/<run_id_a> results/<run_id_b>
```

Compare from a sweep CSV:

```bash
.venv/bin/tradescope results compare \
  --from-sweep results/ma_cross_spy_sweep_smoke_sweep.csv \
  --where param.fast_window=5
```

### 5. Iterate

Change strategy params, execution assumptions, risk controls, or strategy logic, then rerun.

## CLI Reference

The top-level `--help` output exposes this command tree:

```text
tradescope
  backtest
    run
    split
    sweep
  data
    audit
    clear
    fetch
    inspect
    securities
      ingest-alpha-vantage
    update
    validate
  reference
  results
    audit
    best
    compare
    inspect
    show
  strategy
    describe
    init
    list
  universe
    list
    show
```

Run `--help` on any command or command group for the exact supported options:

```bash
.venv/bin/tradescope reference
.venv/bin/tradescope backtest run --help
.venv/bin/tradescope results compare --help
```

### Backtest Commands

Run one config:

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross.yaml
```

Run a parameter sweep:

```bash
.venv/bin/tradescope backtest sweep --config configs/examples/ma_cross_sweep_smoke.yaml --top-n 5
```

Run train/test split backtests:

```bash
.venv/bin/tradescope backtest split \
  --config configs/examples/ma_cross.yaml \
  --train-start 2015-01-01 \
  --train-end 2020-01-01 \
  --test-start 2020-01-01 \
  --test-end 2025-01-01
```

### Data Commands

Fetch raw data and write processed data:

```bash
.venv/bin/tradescope data fetch --config configs/examples/ma_cross.yaml
```

Update canonical data coverage for a universe:

```bash
.venv/bin/tradescope data update --config configs/examples/data_sp500_canonical.yaml
.venv/bin/tradescope data update --config configs/examples/data_sp500_canonical.yaml --to-today
.venv/bin/tradescope data update --config configs/examples/data_all_us_canonical.yaml --to-today
```

Update every processed OHLCV dataset already stored locally:

```bash
.venv/bin/tradescope data update --all
.venv/bin/tradescope data update --all --provider yfinance --interval 1d
```

Every fetch/update writes a JSON manifest under `data/manifests`, recording the config, coverage window, requested symbol count, component list, loaded/skipped counts, unavailable symbols, and security-status summary.

Audit canonical data coverage and repair symbols with missing coverage or quality warnings:

```bash
.venv/bin/tradescope data audit --config configs/examples/data_sp500_canonical.yaml
.venv/bin/tradescope data audit --config configs/examples/data_sp500_canonical.yaml --fix
```

Audit and repair every processed OHLCV dataset already stored locally:

```bash
.venv/bin/tradescope data audit --all
.venv/bin/tradescope data audit --all --fix
```

Inspect local data:

```bash
.venv/bin/tradescope data inspect
.venv/bin/tradescope data inspect --layer processed
.venv/bin/tradescope data inspect --symbol SPY
```

Inspect the local security master:

```bash
.venv/bin/tradescope data securities
.venv/bin/tradescope data securities --status historical
.venv/bin/tradescope data securities --status unavailable
.venv/bin/tradescope data securities ingest-alpha-vantage --api-key "$ALPHAVANTAGE_API_KEY"
.venv/bin/tradescope data securities ingest-alpha-vantage --api-key "$ALPHAVANTAGE_API_KEY" --state delisted --date 2020-01-01
```

Clear local data:

```bash
.venv/bin/tradescope data clear --symbol SPY --yes
.venv/bin/tradescope data clear --layer processed --symbol SPY --yes
```

Validate data for a config:

```bash
.venv/bin/tradescope data validate --config configs/examples/ma_cross.yaml
```

### Universe Commands

List configured universe presets:

```bash
.venv/bin/tradescope universe list
```

Show one preset's symbols:

```bash
.venv/bin/tradescope universe show mega_cap_tech
```

### Results Commands

Show raw stats:

```bash
.venv/bin/tradescope results show results/<run_id>
```

Inspect one run:

```bash
.venv/bin/tradescope results inspect results/<run_id>
```

Compare saved runs:

```bash
.venv/bin/tradescope results compare results/<run_id_a> results/<run_id_b>
```

Compare from a sweep:

```bash
.venv/bin/tradescope results compare \
  --from-sweep results/ma_cross_spy_sweep_smoke_sweep.csv \
  --where param.fast_window=5
```

Show the best run from a sweep:

```bash
.venv/bin/tradescope results best results/ma_cross_spy_sweep_smoke_sweep.csv
.venv/bin/tradescope results best results/ma_cross_spy_sweep_smoke_sweep.csv --where param.slow_window=40
```

Audit saved artifacts:

```bash
.venv/bin/tradescope results audit results/<run_id>
```

The audit includes signal/equity alignment, trade count consistency, positive sizes/prices, non-negative fees, closed-trade PnL math, trade date bounds, and long-only direction checks.

### Strategy Commands

List built-in strategies:

```bash
.venv/bin/tradescope strategy list
```

Describe a built-in strategy:

```bash
.venv/bin/tradescope strategy describe ma_cross
```

Create a custom strategy template:

```bash
.venv/bin/tradescope strategy init strategies/my_strategy.py
```

## Config Reference

Minimal shape:

```yaml
name: example_run
symbols:
  - SPY
start: "2020-01-01"
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
  fees: 0.0
  slippage: 0.0005
  direction: longonly
  benchmark: SPY
  cash_sharing: true
  sizing:
    method: equal_weight
  execution:
    price: close
  risk:
    stop_loss:
    take_profit:
    trailing_stop: false
results:
  output_dir: results
  save_trades: true
  save_equity_curve: true
  save_plots: true
  save_report: false
```

### Data

```yaml
data:
  provider: yfinance
  raw_dir: data/raw
  processed_dir: data/processed
  component_dir: data/components
  refresh: false
  use_canonical_coverage: true
  coverage_start: "2010-01-01"
  coverage_end: "2026-01-01"
  components:
    - ohlcv
```

`refresh: true` ignores existing processed data and fetches again.

By default, backtests use canonical coverage. That means the runner tries to maintain a broad local dataset, such as `2010-01-01` through `2026-01-01`, and each backtest receives only its requested `start` / `end` slice from that larger local file. This avoids redownloading smaller windows as research branches multiply.

Processed data lookup is range-aware. If a stored file already covers the requested window, TradeScope reuses it and slices to the requested dates. If only part of the canonical range exists, TradeScope fetches only the missing date span, merges it with the existing processed data, and writes the broader processed file.

Supported `components` currently include:

```text
ohlcv
research_bundle
all
actions
dividends
splits
capital_gains
income_stmt
quarterly_income_stmt
ttm_income_stmt
balance_sheet
quarterly_balance_sheet
cash_flow
quarterly_cash_flow
ttm_cash_flow
earnings
quarterly_earnings
earnings_dates
earnings_history
```

`research_bundle` expands to dividends, splits, capital gains, all income statements, all balance sheets, all cash flows, and reported earnings data. Backtests currently require `ohlcv`; other components are collected under `data/components` for future strategy research.

Additional yfinance components can be requested explicitly when needed:

```text
fast_info
info
history_metadata
calendar
earnings_estimate
growth_estimates
recommendations
recommendations_summary
major_holders
institutional_holders
mutualfund_holders
insider_transactions
insider_roster_holders
sustainability
news
options
option_chains
```

`all` includes every supported component, including the expensive option-chain collection.

When processed price history is written, TradeScope also updates `data/security_master.parquet` with the provider, symbol, observed history start/end, and status. A symbol whose fetched history ends before the requested coverage end is marked `historical`, which is the local inventory hook we need for partial histories from delistings or stale symbols. If a provider returns no rows for a symbol, TradeScope records that symbol in `data/processed/_unavailable_symbols.json`, marks it `unavailable` in the security master, skips it for future matching requests, and continues loading the rest of the universe.

The security master can also ingest Alpha Vantage listing-status data for active and delisted securities. Those rows add listing metadata such as `name`, `exchange`, `asset_type`, `ipo_date`, `delisting_date`, `listing_source`, and `listing_as_of_date`.

### Universe

For a small research run, use top-level `symbols`:

```yaml
symbols:
  - SPY
  - QQQ
```

For reusable groups, use `universe`:

```yaml
universe:
  presets:
    - sp500
    - index_etfs
    - mega_cap_tech
  symbols:
    - COST
  exclude:
    - TSLA
```

Presets live in [configs/universes.yaml](configs/universes.yaml). The resolved symbol list is:

```text
preset symbols + explicit symbols - excluded symbols
```

Strategies do not need to hardcode tickers. They receive data for the resolved symbols.

Built-in presets include:

```text
all_nasdaq          Current Nasdaq-listed securities from Nasdaq Trader
all_nyse            Current NYSE-listed securities from Nasdaq Trader
sp500                Current S&P 500 constituents
index_etfs           Major US index ETFs
sector_etfs          SPDR sector ETFs
mega_cap_tech        Large US technology names
liquid_single_names  Liquid large-cap single names for smoke tests
```

The `all_nasdaq` and `all_nyse` presets are broad exchange symbol directories, not curated common-stock-only lists.

### Strategy

Built-in:

```yaml
strategy:
  name: ma_cross
  params:
    fast_window: 20
    slow_window: 100
```

Custom file:

```yaml
strategy:
  path: strategies/example_custom.py
  params:
    window: 50
```

Custom module:

```yaml
strategy:
  module: strategies.example_custom
  params:
    window: 50
```

### Portfolio Sizing

Default:

```yaml
portfolio:
  sizing:
    method: equal_weight
```

Other supported methods:

```yaml
sizing:
  method: all_in

sizing:
  method: percent
  value: 0.25

sizing:
  method: fixed_cash
  value: 10000

sizing:
  method: fixed_shares
  value: 10
```

### Execution And Risk

Execution price:

```yaml
portfolio:
  execution:
    price: close      # close, open, or next_open
```

Risk controls:

```yaml
portfolio:
  risk:
    stop_loss: 0.05
    take_profit: 0.15
    trailing_stop: false
```

`next_open` uses the next bar's open as order price, making signal timing more conservative than same-bar close execution.

### Reports

Enable QuantStats HTML reports:

```yaml
results:
  save_report: true
```

Install report dependencies first:

```bash
.venv/bin/python -m pip install -e ".[dev,reports]"
```

## Custom Strategy Contract

Custom strategies expose a `generate_signals(data, params)` function:

```python
def generate_signals(data, params):
    return {
        "entries": entries,
        "exits": exits,
    }
```

`data` is a mapping of symbol to OHLCV dataframe. `entries` and `exits` should be pandas Series/DataFrame objects aligned with close prices.

For now, `entries` and `exits` are the only required public strategy outputs. Sizing, execution, risk controls, fees, and slippage are controlled by config rather than custom strategy code.

Create a new strategy file:

```bash
.venv/bin/tradescope strategy init strategies/my_strategy.py
```

## Built-In Strategies

Current built-ins:

```text
buy_hold   Buy first bar and hold
ma_cross   Moving-average crossover
rsi        RSI mean reversion
bbands     Bollinger Band mean reversion
macd       MACD trend following
donchian   Donchian breakout
```

Explore from the CLI:

```bash
.venv/bin/tradescope strategy list
.venv/bin/tradescope strategy describe macd
```

## Development

Run tests:

```bash
.venv/bin/python -m pytest
```

Run lint:

```bash
.venv/bin/python -m ruff check src tests strategies
```

Run a smoke backtest:

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross_smoke.yaml
```

Run a risk/execution smoke backtest:

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross_risk_smoke.yaml
```

Run a report smoke backtest:

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross_report_smoke.yaml
```

## Troubleshooting

### `tradescope` command not found

Use the venv binary directly:

```bash
.venv/bin/tradescope --help
```

or reinstall editable:

```bash
.venv/bin/python -m pip install -e ".[dev,reports]"
```

### Python version issues

Use Python 3.12:

```bash
PYENV_VERSION=3.12.2 python --version
```

### Empty yfinance data

Try:

```bash
.venv/bin/tradescope data clear --symbol SPY --yes
.venv/bin/tradescope data fetch --config configs/examples/ma_cross.yaml
```

Also check symbol spelling and date range.

### Zero trades

Common causes:

- Strategy produced no entries.
- Signal columns do not match symbols.
- Date range is too short for indicator windows.
- `next_open` execution cannot execute final-bar signals.

### QuantStats report missing

Install report extras:

```bash
.venv/bin/python -m pip install -e ".[dev,reports]"
```

Then set:

```yaml
results:
  save_report: true
```

## Documentation

- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md): full technical handbook.
- [REQUIREMENTS.md](REQUIREMENTS.md): original product requirements and phased plan.

## TODO / Future Improvements

- Add a persistent experiment index, preferably DuckDB, for searchable run history.
- Add `results list` with filters for strategy, symbol, date range, tags, and metrics.
- Add run metadata fields such as tags, notes, author, and research hypothesis.
- Add safe run cleanup commands like `results delete`, `results archive`, and `results prune`.
- Add a Streamlit dashboard for browsing runs, comparing curves, viewing trades, and opening reports.
- Add more data providers: Polygon, Alpaca, Interactive Brokers, local CSV/Parquet imports.
- Add market-calendar-aware data validation using a library such as `exchange_calendars`.
- Add richer data quality checks for missing trading days, split/dividend handling, and symbol coverage.
- Add historical/delisted ticker source ingestion into the security master.
- Add a bulk collection progress view for manifests and partially completed jobs.
- Add true rebalance-to-target portfolio construction beyond entry-signal equal-weight sizing.
- Add multi-strategy portfolio support.
- Add short-side strategy contract support intentionally, with tests and config validation.
- Add walk-forward optimization beyond simple train/test split.
- Add rolling out-of-sample validation and robustness checks.
- Add ranking by multiple metrics and constraints, such as max drawdown under a threshold.
- Add richer result filtering expressions for sweep CSVs and manifests.
- Add more built-in strategies and keep them library-backed where possible.
- Add strategy parameter schemas so invalid params are caught before execution.
- Add local CSV/Parquet data provider for offline research.
- Add import/export tooling for result bundles.
- Add benchmark-relative analytics such as alpha, beta, information ratio, and tracking error.
- Add optional notification or automation hooks for long sweeps.
- Add CI configuration once the repo is under version control.
- Add package docs generated from this README and `DEVELOPMENT_GUIDE.md`.
