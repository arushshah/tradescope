# Strategy Research Log

This is the running notebook for TradingV2 strategy research. We will keep it updated as we test ideas, reject weak assumptions, and find patterns worth exploring further.

The goal is not to collect pretty backtests. The goal is to build a repeatable research process that can survive friction: fees, slippage, realistic execution timing, stale symbols, bad data, regime changes, and parameter sensitivity.

## Research Rules

- Every strategy needs a plain-English hypothesis before testing.
- Every strategy needs an invalidation case: what result would make us distrust it?
- Prefer simple, explainable ideas before complex models.
- Compare against `SPY` or an appropriate benchmark.
- Track whether results survive reasonable parameter changes.
- Treat `execution.price: close` as optimistic unless the signal is known before the close.
- Do not trust a run until `tradingv2 results audit` passes.
- Record boring failures. They are useful.

## Strategy 001: Cross-Sectional Momentum With Market Regime

Status: Implemented, first variation pass complete.

Strategy name:

```text
momentum_regime
```

Example config:

```text
configs/examples/momentum_regime_smoke.yaml
```

### Hypothesis

Stocks with strong intermediate-term momentum tend to continue outperforming, especially when the broader equity market is in an uptrend.

### Economic Intuition

This strategy leans on three common market behaviors:

- Momentum: winners often keep winning over intermediate horizons.
- Trend persistence: stocks above their own medium-term trend may have stronger demand.
- Regime dependence: long-only momentum tends to behave better when the broader market is healthy.

### Rules

Regime filter:

```text
SPY close > SPY 200-day moving average
```

Momentum score:

```text
close / close 126 trading days ago - 1
```

Entry:

```text
market regime is healthy
symbol momentum rank is in the top 20%
symbol close > symbol 100-day moving average
```

Exit:

```text
market regime turns unhealthy
OR symbol momentum rank falls below top 40%
OR symbol close < symbol 100-day moving average
```

The entry threshold is stricter than the exit threshold to reduce churn around the cutoff.

### Default Parameters

```yaml
momentum_window: 126
trend_window: 100
regime_symbol: SPY
regime_window: 200
entry_quantile: 0.8
exit_quantile: 0.6
trade_regime_symbol: false
```

### First Test Universe

Use a small liquid universe first:

```yaml
universe:
  presets:
    - liquid_single_names
  symbols:
    - SPY
```

This keeps the first pass fast and debuggable. If the mechanics look right, expand to `sp500`.

### Invalidation Criteria

We should distrust this strategy if:

- returns come from one or two names only
- it underperforms SPY with worse drawdowns
- it collapses with `execution.price: next_open`
- fees/slippage erase most of the edge
- small changes to `momentum_window`, `entry_quantile`, or `exit_quantile` destroy results
- it only works in one market regime
- audit fails or data coverage is poor

### First Commands

```bash
.venv/bin/tradingv2 backtest run --config configs/examples/momentum_regime_smoke.yaml
.venv/bin/tradingv2 results audit results/<run_id>
```

### Results

#### Run 001

```text
Run ID: 20260516T152109Z_momentum_regime_liquid_smoke
Date: 2026-05-16
Universe: liquid_single_names + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: close
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 71.21%
Benchmark total return: 80.40%
Max drawdown: 19.38%
Sharpe: 0.94
Total trades: 124
Audit: PASS
Warnings: same-bar close execution can be optimistic
```

Observations:

- The strategy made money, but underperformed SPY over the same period.
- Drawdown was not obviously superior enough to justify underperformance.
- Trade count was fairly high for a medium-term momentum system on a small liquid universe.
- Fees paid were meaningful, so churn matters.
- The result is not compelling yet.

Decision:

```text
Do not trust this version as an edge. Keep as a baseline implementation and test variations.
```

#### Run 002

```text
Run ID: 20260516T152943Z_momentum_regime_liquid_next_open
Date: 2026-05-16
Universe: liquid_single_names + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 81.95%
Benchmark total return: 80.40%
Excess return: 1.54%
Max drawdown: 18.97%
Sharpe: 1.03
Total trades: 124
Audit: PASS
```

Observations:

- Moving from same-bar close execution to next-open execution did not break the small-universe result.
- This run barely beat SPY, with a slightly lower drawdown.
- The edge is too small to trust because the universe is tiny and may be cherry-picked.

#### Run 003

```text
Run ID: 20260516T155207Z_momentum_regime_sp500_next_open
Date: 2026-05-16
Universe: sp500 + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 32.94%
Benchmark total return: 80.40%
Excess return: -47.47%
Max drawdown: 14.21%
Sharpe: 0.84
Total trades: 3713
Audit: PASS
Skipped unavailable symbols: TRUE, Q
```

Observations:

- The broad S&P 500 version badly underperformed SPY.
- Drawdown improved, but the return sacrifice was too large.
- Trade count became very high, which suggests the strategy is rotating too broadly and too often.

#### Run 004

```text
Run ID: 20260516T162605Z_momentum_regime_sp500_strict
Date: 2026-05-16
Universe: sp500 + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Parameter change: entry_quantile 0.9, exit_quantile 0.6
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 43.35%
Benchmark total return: 80.40%
Excess return: -37.05%
Max drawdown: 14.26%
Sharpe: 0.88
Total trades: 1968
Audit: PASS
Skipped unavailable symbols: TRUE, Q
```

Observations:

- Requiring a stricter top-10% momentum entry helped versus the broad top-20% version.
- It still badly underperformed SPY.
- Lower trade count is directionally good, but this is not enough.

#### Run 005

```text
Run ID: 20260516T170202Z_momentum_regime_sp500_12m
Date: 2026-05-16
Universe: sp500 + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Parameter change: momentum_window 252
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 25.88%
Benchmark total return: 80.40%
Excess return: -54.52%
Max drawdown: 13.64%
Sharpe: 0.69
Total trades: 3281
Audit: PASS
Skipped unavailable symbols: TRUE, Q
```

Observations:

- A 12-month momentum lookback was worse than the 6-month default.
- Lower drawdown did not compensate for weak return.
- This version is not worth pursuing without a construction change.

### Variation Summary

| Run | Universe | Key Change | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 001 | liquid_single_names + SPY | close execution baseline | 71.21% | 80.40% | -9.19% | 19.38% | 0.94 | 124 | PASS |
| 002 | liquid_single_names + SPY | next_open execution | 81.95% | 80.40% | 1.54% | 18.97% | 1.03 | 124 | PASS |
| 003 | sp500 + SPY | broad S&P 500 | 32.94% | 80.40% | -47.47% | 14.21% | 0.84 | 3713 | PASS |
| 004 | sp500 + SPY | stricter top-10% entry | 43.35% | 80.40% | -37.05% | 14.26% | 0.88 | 1968 | PASS |
| 005 | sp500 + SPY | 12-month momentum | 25.88% | 80.40% | -54.52% | 13.64% | 0.69 | 3281 | PASS |

### Decision After Variation Pass

```text
Do not continue tweaking this exact equal-weight active-signal formulation.
```

The small liquid-universe result is interesting enough to keep as a smoke test, but it is not strong enough to trust as a real edge. The S&P 500 tests are more important because they are harder to cherry-pick, and they failed decisively versus SPY.

This does not invalidate momentum as a family. It invalidates the current portfolio construction:

- It buys every symbol above a quantile instead of selecting a fixed number of strongest names.
- It evaluates entries and exits every day, which creates unnecessary churn.
- It uses equal weight across all active signals, so position count can drift based on market conditions.

Next research should change construction before changing more parameters.

### Next Variations To Test

- Add top-N / max-position-count support, such as top 20 or top 50 names.
- Add monthly rebalance cadence instead of daily active-signal churn.
- Re-test S&P 500 momentum with 6-month and 12-month lookbacks.
- Keep `execution.price: next_open` for research runs unless there is a precise reason to use same-bar close.
- If top-N monthly momentum still underperforms badly, pivot to a different simple family: mean reversion, index trend following, or sector rotation.

### Reproducibility Note

After these runs, `momentum_regime` was cleaned up to call `pct_change(..., fill_method=None)` explicitly. Future runs may differ slightly for symbols with missing bars. Before making any production conclusion, rerun the selected variants with the current code.

### Zero-Fee Rerun

Date: 2026-05-16

Commission assumption changed from:

```text
fees: 0.001
```

to:

```text
fees: 0.0
```

Slippage stayed at:

```text
slippage: 0.0005
```

Reason:

```text
Many modern U.S. equity brokers advertise zero-commission online stock/ETF trading. Slippage remains because spread and execution quality still matter even without explicit commissions.
```

| Run | Zero-Fee Run ID | Variant | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 010 | `20260516T224720Z_momentum_regime_liquid_smoke` | liquid, close execution | 78.94% | 80.40% | -1.47% | 18.31% | 1.01 | 124 | PASS |
| 011 | `20260516T224730Z_momentum_regime_liquid_next_open` | liquid, next_open | 90.18% | 80.40% | 9.77% | 17.95% | 1.10 | 124 | PASS |
| 012 | `20260516T224807Z_momentum_regime_sp500_next_open` | S&P 500, daily top 20% | 37.99% | 80.40% | -42.41% | 12.79% | 0.94 | 3713 | PASS |
| 013 | `20260516T224855Z_momentum_regime_sp500_strict` | S&P 500, daily top 10% | 48.48% | 80.40% | -31.93% | 12.90% | 0.96 | 1968 | PASS |
| 014 | `20260516T225029Z_momentum_regime_sp500_12m` | S&P 500, daily 12-month | 30.78% | 80.40% | -49.62% | 12.19% | 0.80 | 3281 | PASS |

Zero-fee observations:

- Removing explicit commissions materially improved the small liquid-universe next-open result.
- It did not rescue the broad S&P 500 daily active-signal variants.
- The broad daily variants still trail SPY by too much to keep tuning as-is.

## Strategy 002: Rebalanced Top-N Momentum

Status: Implemented, ready for first backtest pass.

Strategy name:

```text
rebalance_momentum
```

Example configs:

```text
configs/examples/rebalance_momentum_sp500_top20_6m.yaml
configs/examples/rebalance_momentum_sp500_top50_6m.yaml
configs/examples/rebalance_momentum_sp500_top20_12m.yaml
configs/examples/rebalance_momentum_sp500_top50_12m.yaml
```

### Hypothesis

A fixed-size portfolio of the strongest S&P 500 momentum names, rebalanced monthly and protected by a broad-market regime filter, should behave better than buying every name above a daily momentum threshold.

### Rules

Universe:

```text
S&P 500 constituents + SPY as the regime/benchmark symbol
```

Momentum score:

```text
close / close N trading days ago - 1
```

Selection:

```text
On each rebalance date, rank eligible symbols by momentum and hold the top N.
```

Default filters:

```text
SPY close > SPY 200-day moving average
symbol close > symbol 100-day moving average
```

Execution:

```text
next_open
```

Sizing:

```text
Equal weight across new active entries under the existing entries/exits backtest contract.
```

### Initial Test Matrix

| Config | Lookback | Holdings | Rebalance | Regime Filter | Trend Filter |
| --- | ---: | ---: | --- | --- | --- |
| `rebalance_momentum_sp500_top20_6m.yaml` | 126 days | 20 | monthly | yes | yes |
| `rebalance_momentum_sp500_top50_6m.yaml` | 126 days | 50 | monthly | yes | yes |
| `rebalance_momentum_sp500_top20_12m.yaml` | 252 days | 20 | monthly | yes | yes |
| `rebalance_momentum_sp500_top50_12m.yaml` | 252 days | 50 | monthly | yes | yes |

### Implementation Note

The current engine uses an `entries` / `exits` strategy contract. This version rotates into new top-N names and exits dropped names on rebalance dates, and exits immediately when the regime filter fails. It does not yet force already-held winners back to exact target weights on every rebalance. If this strategy looks promising, add an order-targeting or rebalance-sizing path before treating it as production-grade.

### First Commands

```bash
.venv/bin/tradingv2 backtest run --config configs/examples/rebalance_momentum_sp500_top20_6m.yaml
.venv/bin/tradingv2 results audit results/<run_id>
```

### Results

#### Run 006

```text
Run ID: 20260516T223848Z_rebalance_momentum_sp500_top20_6m
Date: 2026-05-16
Universe: sp500 + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Rebalance: monthly
Momentum window: 126 trading days
Holdings target: top 20
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 69.51%
Benchmark total return: 80.40%
Excess return: -10.89%
Max drawdown: 18.49%
Sharpe: 0.90
Total trades: 405
Audit: PASS
Skipped unavailable symbols: TRUE, Q
```

Observations:

- Monthly top-20 construction was a large improvement over the daily active-signal S&P 500 momentum variants.
- It still underperformed SPY over this test window.
- Trade count fell sharply versus the broad daily variants, which is directionally good.
- Drawdown was worse than the earlier S&P 500 daily variants, but return was much better.
- This is not a production candidate yet, but it is good enough to finish the initial top-N test matrix before pivoting.

#### Run 007

```text
Run ID: 20260516T224139Z_rebalance_momentum_sp500_top50_6m
Date: 2026-05-16
Universe: sp500 + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Rebalance: monthly
Momentum window: 126 trading days
Holdings target: top 50
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 48.71%
Benchmark total return: 80.40%
Excess return: -31.70%
Max drawdown: 16.98%
Sharpe: 0.85
Total trades: 989
Audit: PASS
Skipped unavailable symbols: TRUE, Q
```

Observations:

- Expanding from top 20 to top 50 weakened returns materially.
- Drawdown improved slightly versus top 20, but not enough to justify the return drag.
- Trade count more than doubled.

#### Run 008

```text
Run ID: 20260516T224326Z_rebalance_momentum_sp500_top20_12m
Date: 2026-05-16
Universe: sp500 + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Rebalance: monthly
Momentum window: 252 trading days
Holdings target: top 20
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 81.85%
Benchmark total return: 80.40%
Excess return: 1.44%
Max drawdown: 16.89%
Sharpe: 0.97
Total trades: 364
Audit: PASS
Skipped unavailable symbols: TRUE, Q
```

Observations:

- This was the best result in the initial rebalanced momentum matrix.
- It slightly beat SPY while reducing max drawdown.
- Trade count was the lowest in the matrix.
- The edge is small, so this is not yet enough for production, but it is worth a deeper robustness pass.

#### Run 009

```text
Run ID: 20260516T224443Z_rebalance_momentum_sp500_top50_12m
Date: 2026-05-16
Universe: sp500 + SPY regime symbol
Date range: 2020-01-01 to 2025-01-01
Execution price: next_open
Rebalance: monthly
Momentum window: 252 trading days
Holdings target: top 50
Fees/slippage: 0.10% fees, 0.05% slippage
Total return: 52.24%
Benchmark total return: 80.40%
Excess return: -28.17%
Max drawdown: 16.23%
Sharpe: 0.85
Total trades: 859
Audit: PASS
Skipped unavailable symbols: TRUE, Q
```

Observations:

- The 12-month lookback helped top 20, but did not rescue top 50.
- Broader selection appears to dilute the momentum signal in this framework.
- Top 50 is not attractive in either tested lookback.

### Initial Matrix Summary

| Run | Config | Lookback | Holdings | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 006 | `rebalance_momentum_sp500_top20_6m.yaml` | 126 | 20 | 69.51% | 80.40% | -10.89% | 18.49% | 0.90 | 405 | PASS |
| 007 | `rebalance_momentum_sp500_top50_6m.yaml` | 126 | 50 | 48.71% | 80.40% | -31.70% | 16.98% | 0.85 | 989 | PASS |
| 008 | `rebalance_momentum_sp500_top20_12m.yaml` | 252 | 20 | 81.85% | 80.40% | 1.44% | 16.89% | 0.97 | 364 | PASS |
| 009 | `rebalance_momentum_sp500_top50_12m.yaml` | 252 | 50 | 52.24% | 80.40% | -28.17% | 16.23% | 0.85 | 859 | PASS |

### Initial Decision

```text
Keep researching top-20 12-month rebalanced momentum, but do not treat it as proven.
```

The first useful pattern is clear: concentrated top-20 selection works much better than top-50 selection, and the 12-month lookback works better than the 6-month lookback in this period. The best variant only beat SPY by 1.44 percentage points over five years, so the edge is thin. We need robustness testing before this deserves real capital.

Next tests should focus on top-20 12-month momentum:

- Compare monthly versus weekly rebalance.
- Compare top 10, top 20, and top 30.
- Test with and without the individual-symbol trend filter.
- Test with and without the SPY regime filter.
- Extend the date range if data coverage allows.
- Add exact target-weight rebalancing support before any production interpretation.

### Zero-Fee Rerun

Date: 2026-05-16

Commission assumption changed from:

```text
fees: 0.001
```

to:

```text
fees: 0.0
```

Slippage stayed at:

```text
slippage: 0.0005
```

| Run | Zero-Fee Run ID | Variant | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 015 | `20260516T225315Z_rebalance_momentum_sp500_top20_6m` | top 20, 6-month | 74.14% | 80.40% | -6.27% | 17.96% | 0.94 | 405 | PASS |
| 016 | `20260516T225717Z_rebalance_momentum_sp500_top50_6m` | top 50, 6-month | 52.66% | 80.40% | -27.75% | 16.29% | 0.90 | 989 | PASS |
| 017 | `20260516T225757Z_rebalance_momentum_sp500_top20_12m` | top 20, 12-month | 86.25% | 80.40% | 5.85% | 16.37% | 1.00 | 364 | PASS |
| 018 | `20260516T225838Z_rebalance_momentum_sp500_top50_12m` | top 50, 12-month | 55.76% | 80.40% | -24.65% | 15.53% | 0.89 | 859 | PASS |

Zero-fee observations:

- Top-20 12-month momentum remains the best branch and improved from a thin 1.44% excess return to 5.85% excess return.
- Top-50 remains unattractive for both lookbacks.
- The concentrated top-20 effect is now stronger, but still needs robustness testing before any capital allocation.

### Validation Pass 001

Date: 2026-05-16 / 2026-05-17 UTC run IDs

Summary artifact:

```text
results/rebalance_momentum_top20_12m_validation_v2.csv
```

Important engine note:

```text
During the first attempt at this validation pass, the unavailable-symbol cache was found to be too coarse for cross-period research. A symbol unavailable in an older window could be skipped in a later window. The cache was fixed to be date-range-specific, and this section records only the rerun after that fix. Earlier validation artifacts with no "v2" in the run name should be ignored.
```

#### Time Window Tests

| Run ID | Window | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260516T234333Z_rebalance_momentum_validation_v2_baseline_2020_2025` | 2020-2025 | 86.25% | 80.40% | 5.85% | 16.37% | 1.00 | 364 | PASS |
| `20260516T234607Z_rebalance_momentum_validation_v2_period_2010_2015` | 2010-2015 | 91.03% | 81.36% | 9.67% | 13.13% | 1.32 | 326 | PASS |
| `20260516T234842Z_rebalance_momentum_validation_v2_period_2015_2020` | 2015-2020 | 38.38% | 56.68% | -18.29% | 23.08% | 0.73 | 373 | PASS |
| `20260516T235225Z_rebalance_momentum_validation_v2_period_2010_2025` | 2010-2025 | 328.15% | 417.14% | -88.99% | 22.65% | 0.93 | 1267 | PASS |

Observations:

- The strategy beat SPY in 2010-2015 and 2020-2025.
- It underperformed badly in 2015-2020.
- It underperformed over the full 2010-2025 period.
- The older windows skipped unavailable current S&P 500 names, so they still carry survivorship and constituent-history caveats.

#### Concentration Tests

| Run ID | Variant | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260516T235446Z_rebalance_momentum_validation_v2_top10_2020_2025` | top 10 | 193.89% | 80.40% | 113.49% | 17.14% | 1.33 | 181 | PASS |
| `20260516T234333Z_rebalance_momentum_validation_v2_baseline_2020_2025` | top 20 | 86.25% | 80.40% | 5.85% | 16.37% | 1.00 | 364 | PASS |
| `20260516T235600Z_rebalance_momentum_validation_v2_top30_2020_2025` | top 30 | 73.17% | 80.40% | -7.23% | 16.16% | 0.97 | 527 | PASS |

Observations:

- Top 10 was dramatically better than top 20 and top 30 in 2020-2025.
- This is exciting but also a major concentration warning.
- The next diagnostic should inspect holdings and attribution to see whether the result is mostly a few mega-cap winners.

#### Filter Ablation

| Run ID | Variant | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260516T234333Z_rebalance_momentum_validation_v2_baseline_2020_2025` | regime on, trend on | 86.25% | 80.40% | 5.85% | 16.37% | 1.00 | 364 | PASS |
| `20260516T235712Z_rebalance_momentum_validation_v2_no_regime_2020_2025` | regime off, trend on | 139.12% | 80.40% | 58.72% | 23.40% | 1.15 | 374 | PASS |
| `20260516T235854Z_rebalance_momentum_validation_v2_no_trend_2020_2025` | regime on, trend off | 108.67% | 80.40% | 28.26% | 20.11% | 1.08 | 314 | PASS |
| `20260517T000021Z_rebalance_momentum_validation_v2_no_filters_2020_2025` | regime off, trend off | 165.46% | 80.40% | 85.06% | 25.43% | 1.06 | 273 | PASS |

Observations:

- Both filters hurt 2020-2025 returns.
- Removing the SPY regime filter had the biggest positive effect.
- Removing filters increased drawdown, so this is a return/risk tradeoff rather than a free improvement.
- This strongly suggests the raw 12-month momentum rank is doing more work than the filters in this window.

#### Slippage Sensitivity

| Run ID | Slippage | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260517T000148Z_rebalance_momentum_validation_v2_slippage_0bps_2020_2025` | 0 bps | 88.50% | 80.40% | 8.09% | 16.11% | 1.02 | 364 | PASS |
| `20260516T234333Z_rebalance_momentum_validation_v2_baseline_2020_2025` | 5 bps | 86.25% | 80.40% | 5.85% | 16.37% | 1.00 | 364 | PASS |
| `20260517T000311Z_rebalance_momentum_validation_v2_slippage_10bps_2020_2025` | 10 bps | 84.04% | 80.40% | 3.63% | 16.63% | 0.98 | 364 | PASS |
| `20260517T000448Z_rebalance_momentum_validation_v2_slippage_25bps_2020_2025` | 25 bps | 77.55% | 80.40% | -2.86% | 17.40% | 0.93 | 364 | PASS |

Observations:

- The baseline survives 10 bps slippage, but only barely.
- It fails at 25 bps slippage.
- The edge is cost-sensitive but not instantly erased.

#### Rebalance Frequency

| Run ID | Variant | Total Return | Benchmark | Excess | Max DD | Sharpe | Trades | Audit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260516T234333Z_rebalance_momentum_validation_v2_baseline_2020_2025` | monthly | 86.25% | 80.40% | 5.85% | 16.37% | 1.00 | 364 | PASS |
| `20260517T000610Z_rebalance_momentum_validation_v2_weekly_2020_2025` | weekly | 87.60% | 80.40% | 7.20% | 23.87% | 0.92 | 719 | PASS |

Observations:

- Weekly rebalance improved total return slightly but worsened drawdown, Sharpe, and trade count.
- Monthly remains the cleaner default.

### Validation Decision

```text
Do not call the strategy validated yet. Keep researching momentum, but shift the next pass toward diagnostics and robustness, not parameter chasing.
```

What survived:

- 2020-2025 baseline beat SPY after zero commissions and 5 bps slippage.
- 2010-2015 baseline beat SPY.
- 2020-2025 top 10 was extremely strong.
- 2020-2025 no-filter variants were strong.

What failed:

- 2015-2020 baseline underperformed.
- 2010-2025 baseline underperformed.
- Top 30 underperformed.
- Top 50 already looked weak in the first matrix.
- Baseline failed at 25 bps slippage.

Next diagnostics:

- Holdings and attribution for top 10, top 20, and no-filter variants.
- Calendar-year returns versus SPY.
- Rolling 1-year and 3-year excess returns.
- Exposure by sector if sector metadata is available.
- Survivorship-bias mitigation with historical constituents or an ETF/index proxy universe.
- Exact target-weight rebalancing support before production interpretation.

### Invalidation Criteria

We should distrust this strategy family if:

- all four initial variants underperform SPY badly
- top 20 and top 50 tell completely different stories
- 6-month and 12-month results are extremely unstable
- drawdown improvement is too small to justify lower returns
- fees/slippage erase the benefit of monthly rotation
- audit fails or data coverage is poor
