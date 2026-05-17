# AGENTS.md

This file is the operating manual for AI coding agents working on TradeScope.

TradeScope is a CLI-first equity backtesting and strategy research toolkit built around `vectorbt`, `pandas`, `yfinance`, `pydantic`, and `click`. The project is currently optimized for fast personal research, but architecture decisions should keep future production use, dashboards, richer experiment tracking, and broader market support in mind.

## Mission

Help build a trustworthy research system for systematic trading.

The priority is not pretty backtests. The priority is a repeatable process that can survive:

- realistic execution assumptions
- slippage and trading costs
- bad or missing data
- stale symbols and delistings
- survivorship bias
- parameter overfitting
- different market regimes
- auditability and reproducibility

When in doubt, choose boring correctness over cleverness.

## Project Layout

```text
configs/
  examples/                 Example run, data, and strategy configs
  universes.yaml            Universe presets

data/
  raw/                      Ignored local provider data
  processed/                Ignored normalized OHLCV parquet data
  components/               Ignored non-OHLCV provider components
  manifests/                Ignored JSON collection/update manifests
  security_master.parquet   Ignored local listing/provider inventory
  symbol_mappings.parquet   Ignored local research-symbol to provider-symbol mappings

results/                    Ignored backtest outputs

src/tradescope/
  cli.py                    Click CLI
  config/                   Pydantic config models
  data/                     Providers, parquet store, quality, maintenance
  backtesting/              vectorbt runner and optimization
  strategies/               Built-ins, registry, custom strategy loading
  results/                  Result storage, comparison, audit
  visualization/            Plot helpers
  analytics/                Optional reports

strategies/                 User custom strategy examples
tests/                      Pytest suite
```

## Environment

Use the project virtualenv:

```bash
.venv/bin/python
.venv/bin/tradescope
.venv/bin/pytest
.venv/bin/ruff
```

Do not assume `python`, `pytest`, or `ruff` are on PATH.

Useful checks:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests strategies
```

## Git And Artifacts

Commit source, docs, configs, tests, and reference materials.

Do not commit:

- `.venv/`
- `data/raw/`
- `data/processed/`
- `data/components/`
- `data/manifests/`
- `data/security_master.parquet`
- `data/symbol_mappings.parquet`
- `results/`
- cache directories
- generated reports
- egg-info/build artifacts

The file `trading-strategies-list.pdf` is intentionally tracked as a reference document.

The file `HANDOFF.md` is intentionally tracked. Update it before ending a long session or after major pipeline changes so future Claude/Codex sessions can resume with low context.

Never delete local data or results unless the user explicitly asks.

Use a rebase-first Git workflow:

- Prefer `git pull --rebase` instead of merge pulls.
- Prefer rebasing local work onto `origin/main` before pushing.
- Avoid merge commits for routine synchronization.
- Do not run force-pushes or history rewrites unless the user explicitly asks.

## Engineering Principles

- Prefer existing libraries over custom implementations.
- Use `vectorbt` for portfolio simulation and indicators where practical.
- Use `pandas` for time-series alignment and transformations.
- Use `pydantic` for config validation.
- Use `click` for CLI surface.
- Use Parquet for persisted local data.
- Keep code small, explicit, and testable.
- Avoid adding abstractions until they remove real duplication or risk.
- Preserve existing command behavior unless the user asked for a breaking change.
- Keep CLI help text aligned exactly with executable commands.

## Data Pipeline Rules

The data layer should maintain canonical local coverage and serve backtests by slicing from that broader dataset.

Current intended behavior:

- Configs can request a narrow backtest window.
- `data.coverage_start` and `data.coverage_end` define the broader local collection window.
- Backtests should load/fetch the canonical range, then pass only the requested `start`/`end` slice to strategies.
- `tradescope data update` updates canonical local data.
- `tradescope data audit --fix` repairs missing coverage or quality issues.

Be careful with unavailable-symbol caching. A symbol unavailable in one date range must not automatically be treated as unavailable in all ranges.

The current S&P 500 universe is based on current constituents. Treat long historical tests as potentially survivorship-biased until historical constituents are supported.

The security master has Alpha Vantage active/delisted listing ingestion. Provider rows should preserve canonical listing metadata such as `name`, `exchange`, `asset_type`, `ipo_date`, `delisting_date`, `listing_source`, and `listing_as_of_date`.

Provider symbol mappings live in `data/symbol_mappings.parquet`. Keep canonical research symbols separate from provider fetch symbols. For example, yfinance may fetch `BRK-B`, but processed data and strategy inputs should remain keyed by `BRK.B` if that is the security-master symbol.

Large security-master collection runs should be resumable and auditable. Prefer batch options such as `--offset`, `--limit`, manifests, and unavailable-symbol records over ad hoc one-off scripts.

Current survivorship-bias pipeline priorities:

1. Add manual/importable provider symbol mappings.
2. Teach audit that partial history is valid when bounded by IPO or delisting dates.
3. Add historical universe membership snapshots.
4. Improve batch collection resume/progress tools.
5. Keep all generated data ignored but inspectable through CLI commands.

## Strategy Contract

Built-in and custom strategies expose:

```python
def generate_signals(data, params):
    return {
        "entries": entries,
        "exits": exits,
    }
```

Where:

- `data` is a `dict[str, pandas.DataFrame]` keyed by symbol.
- each frame contains normalized OHLCV columns.
- `entries` and `exits` are pandas Series/DataFrames aligned to close prices.
- optional `short_entries` and `short_exits` may exist, but long-only is the current primary path.

Strategy code should not hardcode symbol universes. Universes belong in config.

Strategies should be explainable. Every serious strategy should have:

- hypothesis
- rules
- parameters
- invalidation criteria
- benchmark comparison
- audit result
- notes in `STRATEGY_RESEARCH_LOG.md`

## Research Discipline

Do not optimize until something looks good and then declare victory.

For any promising strategy, test:

- multiple time periods
- nearby parameter values
- filter ablations
- slippage sensitivity
- execution timing sensitivity
- universe sensitivity
- holdings/concentration diagnostics
- benchmark comparisons

Important benchmarks:

- SPY for broad U.S. equity
- QQQ for growth/tech-heavy momentum behavior
- sector ETFs for sector-rotation ideas

Use `execution.price: next_open` unless there is a clear reason to use same-bar close. Same-bar close is optimistic unless the signal is known before the close.

## Existing Strategy Notes

`momentum_regime`:

- daily active-signal cross-sectional momentum with market regime filter
- small liquid next-open result was strong
- broad S&P 500 variants underperformed
- keep as baseline, not production candidate

`rebalance_momentum`:

- monthly or weekly top-N cross-sectional momentum
- top-20 12-month S&P 500 branch is the best broad-universe candidate so far
- validation is mixed: good in 2010-2015 and 2020-2025, weak in 2015-2020 and full 2010-2025 versus SPY
- top-10 2020-2025 was very strong but likely concentration-sensitive
- needs holdings attribution, rolling excess returns, and survivorship-bias mitigation

Always read `STRATEGY_RESEARCH_LOG.md` before continuing strategy research.

## Testing Expectations

For code changes, run focused tests first, then the full suite when feasible:

```bash
.venv/bin/python -m pytest tests/test_runner.py
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests strategies
```

For CLI changes, verify help and actual execution:

```bash
.venv/bin/tradescope --help
.venv/bin/tradescope data --help
.venv/bin/tradescope strategy list
```

For backtest-affecting changes, audit generated runs:

```bash
.venv/bin/tradescope results audit results/<run_id>
```

## Documentation Expectations

Update docs when behavior changes:

- `README.md` for user-facing commands and workflows
- `DEVELOPMENT_GUIDE.md` for architecture and deep implementation details
- `STRATEGY_RESEARCH_LOG.md` for strategy experiments and conclusions
- `AGENTS.md` for instructions future agents must follow
- `HANDOFF.md` for current state, known gaps, and next-session continuity

Do not let docs drift from CLI behavior.

## Safety

This is financial research software. Bugs can create false confidence.

Agents must:

- state uncertainty clearly
- avoid overstating strategy validity
- preserve raw research results
- prefer auditability over convenience
- avoid deleting local artifacts
- avoid force-pushing or rewriting history unless explicitly requested

Nothing in this repo should be treated as financial advice.
