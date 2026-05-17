# TradeScope Development Guide

This guide is the technical handbook for TradeScope. It assumes you are a programmer with no prior context on this repository, no prior experience with the libraries used here, and only a general interest in building a backtesting/research tool.

TradeScope is a CLI-first equity backtesting research tool built around `vectorbt`. It fetches market data, stores raw and processed Parquet data locally, loads strategy logic, runs portfolio simulations, saves artifacts, ranks parameter sweeps, validates data, and generates reports.

The project is deliberately library-first. The goal is not to write our own backtesting engine, indicator library, reporting engine, or dataframe system. The goal is to build a clean research shell around proven Python libraries.

## Table Of Contents

1. Project Summary
2. Backtesting Concepts
3. System Architecture
4. Repository Layout
5. Environment Setup
6. Core Libraries
7. Configuration System
8. Data Flow
9. Strategy System
10. Backtest Runner
11. Portfolio Configuration
12. Results And Artifacts
13. CLI Reference
14. Example Workflows
15. Writing Custom Strategies
16. Built-In Strategies
17. Parameter Sweeps
18. Train/Test Splits
19. Data Validation And Cache Management
20. Reports And Plots
21. Testing
22. Debugging
23. Extension Guide
24. Current Limitations
25. Development Roadmap

---

## 1. Project Summary

TradeScope is a Python package and command-line tool for researching equity trading strategies.

At a high level, a user writes a YAML config like this:

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
  execution:
    price: close
results:
  output_dir: results
```

Then runs:

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross.yaml
```

TradeScope then:

1. Parses and validates the YAML config with Pydantic.
2. Loads processed market data, or fetches raw data with `yfinance` and normalizes it.
3. Normalizes the market data into OHLCV dataframes.
4. Loads a strategy.
5. Generates `entries` and `exits` signals.
6. Runs a portfolio simulation with `vectorbt`.
7. Saves run artifacts under `results/<run_id>/`.
8. Optionally creates plots and a QuantStats HTML report.

TradeScope currently focuses on daily equity data. The architecture is intentionally extensible so future markets, data providers, dashboards, and production workflows can be added later.

---

## 2. Backtesting Concepts

This section explains the domain language used throughout the codebase.

### What Is A Backtest?

A backtest simulates how a trading strategy would have performed on historical data.

For example:

1. Download daily prices for SPY from 2015 to 2025.
2. Define a strategy: buy when the 20-day moving average crosses above the 100-day moving average.
3. Simulate trades whenever the strategy emits buy/sell signals.
4. Measure returns, drawdowns, trade count, and risk metrics.

A backtest is not a guarantee of future performance. It is a research tool.

### OHLCV Data

Most backtesting systems use OHLCV bars:

```text
open   price at the beginning of the bar
high   highest price during the bar
low    lowest price during the bar
close  price at the end of the bar
volume number of shares/contracts traded
```

For daily bars, one row represents one trading day.

TradeScope normalizes market data into this schema:

```text
open
high
low
close
adj_close
volume
symbol
source
```

### Signals

TradeScope strategies produce signals.

The public strategy contract is:

```python
def generate_signals(data, params):
    return {
        "entries": entries,
        "exits": exits,
    }
```

`entries` means “enter a position here.”

`exits` means “exit a position here.”

Both are pandas Series or DataFrames of boolean values. A `True` means the signal is active at that timestamp.

Example:

```text
date        close  entry  exit
2024-01-01  100    False  False
2024-01-02  105    True   False
2024-01-03  103    False  False
2024-01-04  110    False  True
```

### Portfolio Simulation

A strategy only says when to enter and exit. A portfolio simulation decides:

- how much cash to start with
- what price to execute at
- how much to buy
- fees and slippage
- stop loss and take profit behavior
- how to handle multiple symbols

TradeScope delegates this work to `vectorbt.Portfolio.from_signals`.

### Fees And Slippage

Fees are transaction costs.

Slippage is the gap between the price you expect and the price you actually get.

In configs:

```yaml
portfolio:
  fees: 0.001
  slippage: 0.0005
```

Those are decimal percentages. `0.001` means 0.1%.

### Execution Price

Execution price determines which bar price is used for simulated orders.

TradeScope supports:

```yaml
portfolio:
  execution:
    price: close
```

Options:

```text
close      execute on same-bar close
open       execute on same-bar open
next_open  execute on next-bar open
```

`next_open` is often more conservative because a signal generated from today’s close usually cannot be traded until the next open.

### Stops

TradeScope uses vectorbt stop support:

```yaml
portfolio:
  risk:
    stop_loss: 0.05
    take_profit: 0.15
    trailing_stop: false
```

`stop_loss: 0.05` means exit when the trade loses 5%.

`take_profit: 0.15` means exit when the trade gains 15%.

`trailing_stop: true` means the stop follows the price upward. In TradeScope, `trailing_stop` requires `stop_loss`.

---

## 3. System Architecture

TradeScope is organized into small layers:

```text
YAML config
   |
   v
Pydantic config model
   |
   v
Data provider/store
   |
   v
Strategy loader
   |
   v
Strategy generate_signals(data, params)
   |
   v
vectorbt Portfolio.from_signals
   |
   v
ResultStore artifacts
   |
   v
CLI output / reports / plots
```

The main design rule is:

> TradeScope owns orchestration. Libraries own domain-heavy work.

Examples:

- `vectorbt` owns portfolio simulation and many indicators.
- `yfinance` owns the initial market data provider.
- `pandas` owns tabular data manipulation.
- `pydantic` owns config validation.
- `click` owns CLI ergonomics.
- `quantstats` owns HTML reports.
- `scikit-learn` owns parameter-grid expansion.

TradeScope glue code connects those libraries.

---

## 4. Repository Layout

Current important files:

```text
tradescope/
  README.md
  REQUIREMENTS.md
  DEVELOPMENT_GUIDE.md
  pyproject.toml
  configs/
    examples/
      ma_cross.yaml
      ma_cross_smoke.yaml
      ma_cross_sweep_smoke.yaml
      ma_cross_risk_smoke.yaml
      ma_cross_report_smoke.yaml
      rsi.yaml
      rsi_sweep.yaml
      bbands.yaml
      macd.yaml
      donchian.yaml
      custom_strategy.yaml
      multi_symbol.yaml
  data/
    raw/
    processed/
  results/
  strategies/
    example_custom.py
  src/
    tradescope/
      cli.py
      config/
      data/
      strategies/
      backtesting/
      results/
      visualization/
      analytics/
      exceptions.py
  tests/
```

### `pyproject.toml`

Defines the Python package, dependencies, command-line entrypoint, and tool config.

Important sections:

```toml
[project]
name = "tradescope"
requires-python = ">=3.10,<3.13"

[project.scripts]
tradescope = "tradescope.cli:cli"
```

That script line means this command:

```bash
tradescope
```

runs:

```python
tradescope.cli:cli
```

### `src/tradescope/cli.py`

The CLI entrypoint. It defines commands like:

```bash
tradescope backtest run
tradescope backtest sweep
tradescope backtest split
tradescope data audit
tradescope data clear
tradescope data fetch
tradescope data inspect
tradescope data securities
tradescope data update
tradescope data validate
tradescope reference
tradescope results show
tradescope results compare
tradescope results inspect
tradescope results best
tradescope strategy list
tradescope strategy describe
tradescope strategy init
```

### `src/tradescope/config/models.py`

Pydantic models for YAML configs.

### `src/tradescope/data/`

Data provider, raw/processed storage, validation, and quality checks.

### `src/tradescope/strategies/`

Built-in strategies, custom strategy loader, strategy metadata registry, and strategy template generator.

### `src/tradescope/backtesting/runner.py`

The core orchestration class. It loads data, loads a strategy, runs vectorbt, and writes artifacts.

### `src/tradescope/results/`

Artifact writing, result comparison, sweep reading, and filtering.

### `tests/`

Pytest test suite.

---

## 5. Environment Setup

Use Python 3.12 for this project.

The global Python on your machine may be 3.13, but some numeric libraries used by vectorbt are more reliable on Python 3.10-3.12.

Create the environment:

```bash
PYENV_VERSION=3.12.2 python -m pip install virtualenv
PYENV_VERSION=3.12.2 python -m virtualenv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,reports]"
```

Or use the venv commands directly without activating:

```bash
.venv/bin/python -m pytest
.venv/bin/tradescope --help
```

### Why Editable Install?

This command:

```bash
python -m pip install -e ".[dev,reports]"
```

installs the package in editable mode.

Editable mode means changes under `src/tradescope/` are immediately reflected when you run the CLI or tests. You do not need to reinstall after every code edit.

### Dependency Groups

Base dependencies are always installed.

`dev` dependencies include testing/linting tools:

```text
pytest
pytest-cov
ruff
```

`reports` dependencies include:

```text
quantstats
```

---

## 6. Core Libraries

This section introduces every major package used by TradeScope.

### pandas

`pandas` is the dataframe library.

TradeScope uses pandas for:

- OHLCV dataframes
- signal matrices
- result tables
- CSV/Parquet IO
- date indexes
- joining symbols into price matrices

The two most important pandas objects are:

```python
pd.Series
pd.DataFrame
```

A Series is one column of data:

```python
close = pd.Series([100, 101, 99])
```

A DataFrame is a table:

```python
prices = pd.DataFrame({
    "SPY": [100, 101, 99],
    "QQQ": [200, 202, 198],
})
```

TradeScope generally uses:

```text
index   timestamp
columns symbols or OHLCV fields
values  prices/signals/metrics
```

Example strategy price matrix:

```python
close = pd.concat(
    {symbol: frame["close"] for symbol, frame in data.items()},
    axis=1,
)
```

Result:

```text
            SPY     QQQ
2024-01-01  100.0   200.0
2024-01-02  101.0   202.0
2024-01-03   99.0   198.0
```

### vectorbt

`vectorbt` is the backtesting engine.

TradeScope uses vectorbt for:

- indicators such as MA, RSI, Bollinger Bands, MACD
- portfolio simulation
- trade records
- performance stats
- drawdown helpers

The key call is:

```python
vbt.Portfolio.from_signals(
    close=close,
    entries=entries,
    exits=exits,
    price=price,
    init_cash=100000,
    fees=0.001,
    slippage=0.0005,
)
```

That returns a vectorbt Portfolio object.

Important methods/properties:

```python
portfolio.stats()
portfolio.value()
portfolio.trades.records_readable
```

Indicator examples:

```python
ma = vbt.MA.run(close, window=20)
rsi = vbt.RSI.run(close, window=14)
bb = vbt.BBANDS.run(close, window=20, alpha=2.0)
macd = vbt.MACD.run(close)
```

### yfinance

`yfinance` downloads market data from Yahoo Finance.

TradeScope uses it in:

```text
src/tradescope/data/yfinance_provider.py
```

The provider calls:

```python
yf.download(
    symbol,
    start=start.isoformat(),
    end=end.isoformat() if end else None,
    interval=interval,
    auto_adjust=False,
    progress=False,
)
```

Then it normalizes Yahoo’s columns:

```text
Open      -> open
High      -> high
Low       -> low
Close     -> close
Adj Close -> adj_close
Volume    -> volume
```

### pydantic

`pydantic` validates config files.

TradeScope config classes inherit from:

```python
BaseModel
```

Example:

```python
class PortfolioConfig(BaseModel):
    init_cash: float = 100_000
    fees: float = 0.0
```

If the YAML contains bad types or invalid values, Pydantic raises a validation error before a backtest runs.

### click

`click` builds command-line interfaces.

Example from `cli.py`:

```python
@backtest.command("run")
@click.option("--config", required=True)
def run_backtest(config_path):
    ...
```

That creates:

```bash
tradescope backtest run --config ...
```

### pyarrow

`pyarrow` enables pandas to read/write Parquet files.

TradeScope uses Parquet for raw and processed market data:

```python
data.to_parquet(path, index=True)
pd.read_parquet(path)
```

Parquet is faster and more compact than CSV for structured data.

### scikit-learn

TradeScope uses one scikit-learn utility:

```python
from sklearn.model_selection import ParameterGrid
```

This expands parameter grids for sweeps.

Example:

```python
ParameterGrid({
    "fast_window": [10, 20],
    "slow_window": [50, 100],
})
```

produces:

```text
fast=10 slow=50
fast=10 slow=100
fast=20 slow=50
fast=20 slow=100
```

### quantstats

`quantstats` generates HTML performance reports.

TradeScope calls:

```python
qs.reports.html(
    returns,
    benchmark=benchmark_returns,
    output="report.html",
)
```

Reports are optional:

```yaml
results:
  save_report: true
```

### pytest

`pytest` runs the test suite.

```bash
.venv/bin/python -m pytest
```

### ruff

`ruff` is the linter.

```bash
.venv/bin/python -m ruff check src tests strategies
```

---

## 7. Configuration System

Config files are YAML.

The loader is:

```python
def load_config(path: str | Path) -> BacktestConfig:
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    config = BacktestConfig.model_validate(raw)
    config.symbols = resolve_universe_symbols(...)
    return config
```

The root config model is:

```python
class BacktestConfig(BaseModel):
    name: str
    symbols: list[str]
    universe: UniverseConfig
    start: date
    end: date | None = None
    interval: str = "1d"
    data: DataConfig
    strategy: StrategyConfig
    portfolio: PortfolioConfig
    results: ResultsConfig
```

### Data Config

```yaml
data:
  provider: yfinance
  raw_dir: data/raw
  processed_dir: data/processed
  refresh: false
```

Fields:

```text
provider       currently yfinance
raw_dir        raw provider output folder
processed_dir  normalized OHLCV folder used by backtests
refresh        ignore processed data and fetch again
```

### Universe Config

Simple configs can still use top-level `symbols`:

```yaml
symbols:
  - SPY
  - QQQ
```

Larger configs can use reusable universe presets:

```yaml
universe:
  preset_file: configs/universes.yaml
  presets:
    - sp500
    - index_etfs
    - mega_cap_tech
  symbols:
    - COST
  exclude:
    - TSLA
```

Resolution order:

```text
top-level symbols
+ symbols from each preset
+ universe.symbols
- universe.exclude
```

The resolved list is written back to `config.symbols`, so the runner and strategies keep using the same symbol interface.

Built-in presets currently include:

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

### Strategy Config

Built-in strategy:

```yaml
strategy:
  name: ma_cross
  params:
    fast_window: 20
    slow_window: 100
```

Custom strategy by file:

```yaml
strategy:
  path: strategies/example_custom.py
  params:
    window: 50
```

Custom strategy by module:

```yaml
strategy:
  module: strategies.example_custom
  params:
    window: 50
```

### Portfolio Config

```yaml
portfolio:
  init_cash: 100000
  fees: 0.001
  slippage: 0.0005
  direction: longonly
  benchmark: SPY
  cash_sharing: true
  sizing:
    method: equal_weight
  execution:
    price: close
  risk:
    stop_loss: 0.05
    take_profit: 0.15
    trailing_stop: false
```

### Results Config

```yaml
results:
  output_dir: results
  save_trades: true
  save_equity_curve: true
  save_plots: true
  save_report: false
```

---

## 8. Data Flow

Data loading happens in `BacktestRunner._load_data`.

Simplified:

```python
store = MarketDataStore(config.data.raw_dir, config.data.processed_dir)

for symbol in symbols:
    processed = store.read_processed(provider, symbol, start, end, interval)
    if processed is found:
        use processed
    else:
        compare requested dates with overlapping processed files
        fetch only missing spans with YFinanceProvider
        write raw data for fetched spans
        normalize, merge, and write a broader processed file
```

The processed data layer is range-aware. A file stored as `SPY_2015-01-01_2025-01-01_1d.parquet` can satisfy a later request for `2020-01-01` through `2021-01-01` without a network fetch. If a later request extends beyond the stored range, only the missing head or tail span is fetched.

When a provider returns no rows for a symbol, the store writes an unavailable-symbol record to `data/processed/_unavailable_symbols.json`. Later requests for the same provider, symbol, interval, and covered date range skip that symbol instead of repeatedly calling the provider.

Each successful processed-price write also updates `data/security_master.parquet`. The security master stores provider, symbol, observed history start/end, first/last seen timestamps, and status:

```text
available     fetched history reaches the requested coverage end
historical    fetched history ends before the requested coverage end
unavailable   provider returned no rows for the requested range
```

This does not by itself solve survivorship bias, because current exchange lists still omit old delisted tickers, but it gives bulk collection runs a durable inventory for partial histories once a historical symbol source is added.

Alpha Vantage listing-status ingestion adds active/delisted security rows with listing metadata such as `name`, `exchange`, `asset_type`, `ipo_date`, `delisting_date`, `listing_source`, and `listing_as_of_date`. Use `tradescope data securities ingest-alpha-vantage` to seed the security master before large yfinance collection runs.

Fetch and update commands write JSON manifests under `data/manifests`. A manifest records the config, coverage window, requested symbol count, component list, loaded/skipped counts, unavailable symbols, and security-status summary. These files are the lightweight progress ledger for long collection jobs while the actual market data remains in Parquet.

### Market Data File Names

Raw and processed files use:

```text
<SYMBOL>_<START>_<END>_<INTERVAL>.parquet
```

Example:

```text
SPY_2023-01-01_2024-01-01_1d.parquet
```

### Data Inspection

```bash
.venv/bin/tradescope data inspect
```

Output includes:

```text
symbol
start
end
interval
rows
first_timestamp
last_timestamp
path
```

### Data Clearing

```bash
.venv/bin/tradescope data clear --symbol SPY --yes
```

### Data Validation

```bash
.venv/bin/tradescope data validate --config configs/examples/ma_cross.yaml
```

Checks:

- empty data
- duplicate timestamps
- missing values
- missing close values
- non-monotonic timestamps

---

## 9. Strategy System

Strategies are functions that transform market data into signals.

Public contract:

```python
def generate_signals(data, params):
    return {
        "entries": entries,
        "exits": exits,
    }
```

`data` is:

```python
dict[str, pd.DataFrame]
```

Example:

```python
{
    "SPY": spy_dataframe,
    "QQQ": qqq_dataframe,
}
```

Each dataframe has:

```text
open
high
low
close
adj_close
volume
symbol
source
```

`entries` and `exits` should align to the close price matrix:

```text
            SPY    QQQ
2024-01-01  False  False
2024-01-02  True   False
2024-01-03  False  True
```

### Why Only Entries And Exits?

We intentionally keep the public strategy contract simple.

Sizing, execution price, risk controls, fees, and slippage are portfolio-level concerns controlled by config.

That means strategy files are easy to write and compare.

---

## 10. Backtest Runner

The runner is in:

```text
src/tradescope/backtesting/runner.py
```

Primary class:

```python
class BacktestRunner:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def run(self) -> BacktestResult:
        ...
```

The `run` method:

1. Loads data.
2. Creates a close matrix.
3. Loads strategy.
4. Generates signals.
5. Validates signals.
6. Builds vectorbt portfolio.
7. Creates result directory.
8. Writes artifacts.

### Vectorbt Portfolio Construction

The important method is `_build_portfolio`.

It calls:

```python
vbt.Portfolio.from_signals(**kwargs)
```

The kwargs include:

```text
close
entries
exits
price
open
high
low
init_cash
fees
slippage
freq
cash_sharing
size
size_type
direction
sl_stop
tp_stop
sl_trail
```

Not every key is always present.

### Execution Price Translation

```python
portfolio.execution.price = close
```

uses close prices.

```python
portfolio.execution.price = open
```

uses open prices.

```python
portfolio.execution.price = next_open
```

uses:

```python
open_price.shift(-1)
```

---

## 11. Portfolio Configuration

### Sizing Modes

Default:

```yaml
sizing:
  method: equal_weight
```

Supported:

```text
equal_weight   split available entry allocation across active signals
all_in         use 100% percent sizing
percent        use fixed percent per signal
fixed_cash     buy fixed dollar value
fixed_shares   buy fixed share count
```

Examples:

```yaml
sizing:
  method: percent
  value: 0.25
```

```yaml
sizing:
  method: fixed_cash
  value: 10000
```

```yaml
sizing:
  method: fixed_shares
  value: 10
```

### Direction

Current default:

```yaml
direction: longonly
```

Short-side support is intentionally not fully exposed through the public strategy contract yet.

### Risk

```yaml
risk:
  stop_loss: 0.05
  take_profit: 0.15
  trailing_stop: false
```

These pass to vectorbt as:

```python
sl_stop
tp_stop
sl_trail
```

---

## 12. Results And Artifacts

Each run creates:

```text
results/<run_id>/
  config.yaml
  stats.csv
  summary.json
  equity_curve.csv
  benchmark_equity.csv
  benchmark_returns.csv
  trades.csv
  report.html
  plots/
    equity_curve.png
    drawdown.png
```

Not every artifact is always present.

For example:

- `report.html` only exists when `save_report: true`.
- benchmark files only exist when `portfolio.benchmark` is not null.
- plots only exist when `save_plots: true`.

### Run IDs

Run directories are named:

```text
<UTC_TIMESTAMP>_<CONFIG_NAME>
```

Example:

```text
20260514T144928Z_ma_cross_spy_risk_smoke
```

### Stats

Stats come from:

```python
portfolio.stats()
```

Then TradeScope adds:

```text
Benchmark Symbol
Benchmark Total Return [%]
```

### Trades

Trades come from:

```python
portfolio.trades.records_readable
```

---

## 13. CLI Reference

### Top Level

```bash
.venv/bin/tradescope --help
```

Command groups:

```text
tradescope
  backtest
    run
    split
    sweep
  data
    audit
    clear
    collect-securities
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

All examples in this guide use `.venv/bin/tradescope` so they execute even when the virtualenv is not activated. If the virtualenv is activated, `tradescope ...` is equivalent.

Values in angle brackets are placeholders. Replace `results/<run_id>` with a real run directory printed by `backtest run`.

### Backtest Commands

Run one config:

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross.yaml
```

Run parameter sweep:

```bash
.venv/bin/tradescope backtest sweep --config configs/examples/ma_cross_sweep_smoke.yaml --top-n 5
```

Run train/test split:

```bash
.venv/bin/tradescope backtest split \
  --config configs/examples/ma_cross_smoke.yaml \
  --train-start 2023-01-01 \
  --train-end 2023-07-01 \
  --test-start 2023-07-01 \
  --test-end 2024-01-01
```

### Data Commands

Fetch data:

```bash
.venv/bin/tradescope data fetch --config configs/examples/ma_cross.yaml
```

Update data:

```bash
.venv/bin/tradescope data update --config configs/examples/data_sp500_canonical.yaml
.venv/bin/tradescope data update --config configs/examples/data_all_us_canonical.yaml --to-today
.venv/bin/tradescope data update --all
.venv/bin/tradescope data collect-securities --status active --exchange NASDAQ
.venv/bin/tradescope data collect-securities --status delisted --offset 0 --limit 100
```

Audit data:

```bash
.venv/bin/tradescope data audit --config configs/examples/data_sp500_canonical.yaml
.venv/bin/tradescope data audit --all
.venv/bin/tradescope data audit --all --fix
```

Inspect data:

```bash
.venv/bin/tradescope data inspect
.venv/bin/tradescope data inspect --layer processed
.venv/bin/tradescope data securities
.venv/bin/tradescope data securities ingest-alpha-vantage --api-key "$ALPHAVANTAGE_API_KEY"
```

Clear data:

```bash
.venv/bin/tradescope data clear --symbol SPY --yes
.venv/bin/tradescope data clear --layer processed --symbol SPY --yes
```

Validate data:

```bash
.venv/bin/tradescope data validate --config configs/examples/ma_cross.yaml
```

### Universe Commands

List presets:

```bash
.venv/bin/tradescope universe list
```

Show one preset:

```bash
.venv/bin/tradescope universe show sector_etfs
```

### Results Commands

Show raw stats:

```bash
.venv/bin/tradescope results show results/<run_id>
```

Inspect run:

```bash
.venv/bin/tradescope results inspect results/<run_id>
```

Compare runs:

```bash
.venv/bin/tradescope results compare results/<run_id_a> results/<run_id_b>
```

Compare from sweep:

```bash
.venv/bin/tradescope results compare \
  --from-sweep results/ma_cross_spy_sweep_smoke_sweep.csv \
  --where param.fast_window=5
```

Best from sweep:

```bash
.venv/bin/tradescope results best \
  results/ma_cross_spy_sweep_smoke_sweep.csv \
  --where param.slow_window=40
```

Audit saved artifacts:

```bash
.venv/bin/tradescope results audit results/<run_id>
```

The audit checks for required files, readable stats, nonempty and monotonic equity curves, signal/equity alignment, trade count consistency, positive sizes/prices, non-negative fees, independent closed-trade PnL math, trade date bounds, basic trade timestamp sanity, and long-only direction violations.

### Strategy Commands

List built-ins:

```bash
.venv/bin/tradescope strategy list
```

Describe built-in:

```bash
.venv/bin/tradescope strategy describe macd
```

Create template:

```bash
.venv/bin/tradescope strategy init strategies/my_strategy.py
```

---

## 14. Example Workflows

### Workflow 1: Run A Smoke Backtest

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross_smoke.yaml
```

Then inspect:

```bash
.venv/bin/tradescope results inspect results/<run_id>
```

### Workflow 2: Run A Sweep

```bash
.venv/bin/tradescope backtest sweep --config configs/examples/ma_cross_sweep_smoke.yaml --top-n 5
```

Find best:

```bash
.venv/bin/tradescope results best results/ma_cross_spy_sweep_smoke_sweep.csv
```

Filter:

```bash
.venv/bin/tradescope results best results/ma_cross_spy_sweep_smoke_sweep.csv --where param.slow_window=40
```

### Workflow 3: Generate Report

```bash
.venv/bin/tradescope backtest run --config configs/examples/ma_cross_report_smoke.yaml
```

Open:

```text
results/<run_id>/report.html
```

### Workflow 4: Create A Custom Strategy

```bash
.venv/bin/tradescope strategy init strategies/my_strategy.py
```

Edit it.

Create a config:

```yaml
strategy:
  path: strategies/my_strategy.py
  params:
    window: 50
```

Run:

```bash
.venv/bin/tradescope backtest run --config configs/my_strategy.yaml
```

---

## 15. Writing Custom Strategies

Start with:

```bash
.venv/bin/tradescope strategy init strategies/my_strategy.py
```

Template:

```python
from __future__ import annotations

import pandas as pd
import vectorbt as vbt


def generate_signals(data, params):
    window = int(params.get("window", 50))
    close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)

    moving_average = vbt.MA.run(close, window=window).ma
    if isinstance(moving_average.columns, pd.MultiIndex):
        moving_average = moving_average.copy()
        moving_average.columns = moving_average.columns.get_level_values(-1)

    entries = close > moving_average
    exits = close < moving_average
    return {"entries": entries, "exits": exits}
```

### Important Rules

1. Return a dict.
2. Include `entries`.
3. Include `exits`.
4. Align indexes to price data.
5. Align columns to symbols.
6. Keep sizing and risk in config, not in the strategy.

### Common Strategy Pattern

```python
close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
indicator = ...
entries = ...
exits = ...
return {"entries": entries, "exits": exits}
```

### Multi-Symbol Strategy

Your strategy should naturally work with multiple columns:

```python
close = pd.concat({symbol: frame["close"] for symbol, frame in data.items()}, axis=1)
```

Then every operation should preserve columns:

```python
entries = close > moving_average
```

---

## 16. Built-In Strategies

### `buy_hold`

Buys on the first row and never exits.

### `ma_cross`

Uses vectorbt MA indicators.

Parameters:

```yaml
fast_window: 20
slow_window: 100
```

Entry:

```text
fast MA moves above slow MA
```

Exit:

```text
fast MA moves below slow MA
```

### `rsi`

Uses vectorbt RSI.

Parameters:

```yaml
window: 14
entry_threshold: 30
exit_threshold: 60
```

Entry:

```text
RSI below entry threshold
```

Exit:

```text
RSI above exit threshold
```

### `bbands`

Uses vectorbt Bollinger Bands.

Parameters:

```yaml
window: 20
alpha: 2.0
```

Entry:

```text
close below lower band
```

Exit:

```text
close above middle band
```

### `macd`

Uses vectorbt MACD.

Parameters:

```yaml
fast_window: 12
slow_window: 26
signal_window: 9
```

Entry:

```text
MACD crosses above signal
```

Exit:

```text
MACD crosses below signal
```

### `donchian`

Uses pandas rolling high/low because this vectorbt version does not expose a Donchian helper.

Parameters:

```yaml
entry_window: 55
exit_window: 20
```

Entry:

```text
close above previous upper channel
```

Exit:

```text
close below previous lower channel
```

---

## 17. Parameter Sweeps

A sweep uses list-valued strategy params.

Example:

```yaml
strategy:
  name: ma_cross
  params:
    fast_window:
      - 5
      - 10
    slow_window:
      - 20
      - 40
```

TradeScope uses:

```python
sklearn.model_selection.ParameterGrid
```

to expand all combinations.

Command:

```bash
.venv/bin/tradescope backtest sweep --config configs/examples/ma_cross_sweep_smoke.yaml
```

Outputs:

```text
results/<name>_sweep.csv
results/<name>_sweep_manifest.json
```

---

## 18. Train/Test Splits

Train/test split helps reduce overfitting.

Command:

```bash
.venv/bin/tradescope backtest split \
  --config configs/examples/ma_cross_smoke.yaml \
  --train-start 2023-01-01 \
  --train-end 2023-07-01 \
  --test-start 2023-07-01 \
  --test-end 2024-01-01
```

This creates two runs:

```text
<name>_train
<name>_test
```

and a summary:

```text
results/<name>_split.csv
```

---

## 19. Data Validation And Cache Management

### Inspect Data

```bash
.venv/bin/tradescope data inspect
```

### Clear Data

```bash
.venv/bin/tradescope data clear --symbol SPY --yes
```

### Validate Config Data

```bash
.venv/bin/tradescope data validate --config configs/examples/ma_cross.yaml
```

Quality reports are built in:

```text
src/tradescope/data/quality.py
```

---

## 20. Reports And Plots

### PNG Plots

TradeScope writes:

```text
plots/equity_curve.png
plots/drawdown.png
```

The drawdown calculation uses vectorbt:

```python
series.vbt.drawdown()
```

### QuantStats HTML

Enable:

```yaml
results:
  save_report: true
```

Install:

```bash
.venv/bin/python -m pip install -e ".[dev,reports]"
```

Output:

```text
report.html
```

---

## 21. Testing

Run all tests:

```bash
.venv/bin/python -m pytest
```

Run one file:

```bash
.venv/bin/python -m pytest tests/test_runner.py
```

Run lint:

```bash
.venv/bin/python -m ruff check src tests strategies
```

Current tests cover:

- config loading
- config validation
- data normalization
- raw/processed data storage
- data quality reports
- parameter grid expansion
- result filtering
- strategy loading
- built-in strategy signal shape
- strategy template generation
- vectorbt runner behavior
- execution price logic
- risk config translation
- deterministic golden backtest
- plot generation

---

## 22. Debugging

### Import Errors

If `tradescope` is not found:

```bash
.venv/bin/python -m pip install -e ".[dev,reports]"
```

### vectorbt Or numba Warnings

Some tests may emit warnings from vectorbt/numba internals when indicators compile. These are external deprecation warnings, not test failures.

### yfinance Fetch Problems

If yfinance returns empty data:

1. Check symbol spelling.
2. Check date range.
3. Try `data.refresh: true`.
4. Delete stale stored data.

```bash
.venv/bin/tradescope data clear --symbol SPY --yes
```

### Empty Backtest / Zero Trades

Possible causes:

- Strategy produced no entries.
- Signals do not align with symbol columns.
- Moving average windows are too long for the date range.
- Execution price is `next_open` and last-bar signals cannot execute.

### Bad Custom Strategy

Check:

```python
return {"entries": entries, "exits": exits}
```

Make sure `entries` and `exits` are not `None`.

Make sure columns match symbols.

---

## 23. Extension Guide

### Add A New Data Provider

Implement:

```python
class MyProvider(MarketDataProvider):
    def fetch(self, symbols, start, end, interval):
        ...
```

Return:

```python
dict[str, pd.DataFrame]
```

Each dataframe should have normalized OHLCV columns.

Then update `BacktestRunner._load_data` to route to the provider.

### Add A Built-In Strategy

1. Create:

```text
src/tradescope/strategies/builtin/my_strategy.py
```

2. Define:

```python
def generate_signals(data, params):
    ...
```

3. Register in:

```text
src/tradescope/strategies/builtin/__init__.py
```

4. Add metadata in:

```text
src/tradescope/strategies/registry.py
```

5. Add tests in:

```text
tests/test_strategies.py
```

6. Add example config if useful.

### Add A New CLI Command

Commands live in:

```text
src/tradescope/cli.py
```

Use Click decorators:

```python
@results.command("my-command")
def my_command():
    ...
```

Keep CLI commands thin. Put reusable logic in modules.

### Add A New Result Artifact

Add write method to:

```text
src/tradescope/results/store.py
```

Call it from:

```text
BacktestRunner.run
```

Update:

```text
results inspect
```

if users should see it.

---

## 24. Current Limitations

TradeScope is useful, but still early.

Known limitations:

- Equities first.
- Daily data first.
- yfinance first.
- No live trading.
- No broker integration.
- No dashboard yet.
- No persistent experiment database yet.
- Public strategy contract is long entries/exits only.
- Short strategy contract is not finalized.
- Equal-weight sizing is entry-signal-based, not full rebalance-to-target.
- Donchian strategy uses pandas rolling calculations because vectorbt lacks a built-in helper here.
- yfinance data quality depends on Yahoo Finance availability.

---

## 25. Development Roadmap

Likely next phases:

### Experiment Management

- DuckDB run index.
- `results list`.
- tags and notes.
- run deletion/archive.

### Dashboard

- Streamlit dashboard.
- Browse runs.
- Compare curves.
- Inspect trades.
- View reports.

### More Data Providers

- Polygon.
- Alpaca.
- Interactive Brokers.
- Local CSV/Parquet import.

### Advanced Validation

- Market calendars.
- Missing trading-day checks.
- Split/dividend handling.
- Survivorship-bias-aware universes.

### Portfolio Construction

- True rebalance-to-target weights.
- Portfolio-level allocation rules.
- Multi-strategy portfolios.

### Strategy Contract V2

Possible future optional fields:

```python
{
    "entries": entries,
    "exits": exits,
    "metadata": metadata,
}
```

Short-side support should be introduced intentionally, not casually.

---

## Mental Model For Development

When modifying TradeScope, ask:

1. Is there an existing library that should do this?
2. Is this domain logic or orchestration glue?
3. Does this belong in config, strategy, data, runner, results, or CLI?
4. Can this be tested offline without network access?
5. Will this artifact help a future dashboard?
6. Does this preserve the simple custom strategy contract?

If the answer is unclear, prefer the smallest library-backed change.
