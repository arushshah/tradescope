# TradeScope Handoff

This is the continuity document for Claude, Codex, or any future agent taking over the TradeScope repo after context loss.

## Current Goal

Build TradeScope into a survivorship-bias-aware equity research and backtesting system.

The near-term objective is not strategy execution. It is a trustworthy historical data pipeline that can support research over:

- active tickers
- delisted tickers
- ticker/name changes
- partial histories from IPOs and delistings
- provider-specific symbol formats
- future historical universe reconstruction

## Current Repository State

Repo path:

```bash
/Users/arush/Documents/tradescope
```

Use the local virtualenv:

```bash
.venv/bin/python
.venv/bin/tradescope
.venv/bin/ruff
.venv/bin/python -m pytest
```

Do not assume global `python`, `pytest`, `ruff`, or `tradescope` are active.

Recent commits:

```text
ee18072 Add provider symbol mapping support
8bb5199 Preserve listing metadata during collection
22a1ca3 Collect data from security master
38e2633 Ignore generated security master data
cd175b8 Add Alpha Vantage security master ingestion
f10abc0 Add data collection manifests
dd88f4e Add security master for bulk data collection
```

At the time this handoff was written:

- `git status --short` was clean before creating this document.
- Full test suite passed after the latest functional changes: `79 passed`.
- Ruff passed: `All checks passed!`.

## Important Local Data State

Generated data is intentionally ignored by Git.

Important ignored files/directories:

```text
data/raw/
data/processed/
data/components/
data/manifests/
data/security_master.parquet
data/symbol_mappings.parquet
results/
```

The local `data/security_master.parquet` was seeded from Alpha Vantage listing status and contained roughly:

```text
total rows: 22237
active:     12861
delisted:   9376
```

Do not delete or overwrite local data unless the user explicitly asks.

The user pasted an Alpha Vantage API key earlier. Do not echo it into source, docs, commits, logs, or final answers. Use the environment variable:

```bash
export ALPHAVANTAGE_API_KEY="..."
```

Recommend rotating the key if appropriate, because it appeared in chat.

## Current Data Pipeline Capabilities

### Security Master

The security master lives at:

```text
data/security_master.parquet
```

It is managed by `src/tradescope/data/security_master.py`.

It stores both canonical listing rows and provider data rows.

Canonical listing rows use:

```text
provider = security_master
```

Provider rows use values such as:

```text
provider = yfinance
```

Fields include:

```text
provider
symbol
status
first_seen
last_seen
history_start
history_end
name
exchange
asset_type
ipo_date
delisting_date
listing_source
listing_as_of_date
reason
```

Current statuses include:

- `active`: canonical listing is currently listed.
- `delisted`: canonical listing is delisted.
- `available`: provider OHLCV covered requested range.
- `historical`: provider OHLCV exists but ends before requested range end.
- `unavailable`: provider returned no rows for the requested provider/symbol/range/interval.

Alpha Vantage ingestion:

```bash
.venv/bin/tradescope data securities ingest-alpha-vantage --api-key "$ALPHAVANTAGE_API_KEY"
.venv/bin/tradescope data securities ingest-alpha-vantage --api-key "$ALPHAVANTAGE_API_KEY" --state delisted --date 2026-05-17
```

Inspect:

```bash
.venv/bin/tradescope data securities
.venv/bin/tradescope data securities --status delisted
.venv/bin/tradescope data securities --status historical
.venv/bin/tradescope data securities --status unavailable
```

### Collection From Security Master

Collect based on security-master filters:

```bash
.venv/bin/tradescope data collect-securities
.venv/bin/tradescope data collect-securities --status delisted --asset-type Stock --component ohlcv --limit 100 --offset 0 --start 2010-01-01 --end 2026-01-01
.venv/bin/tradescope data collect-securities --status active --exchange NASDAQ --asset-type Stock
```

Important options:

- `--status` repeatable, default `active`
- `--exchange` repeatable
- `--asset-type` repeatable, default `Stock`
- `--source` default `alpha_vantage_listing_status`
- `--start`, `--end`, `--interval`
- `--component` repeatable, default `ohlcv` and `research_bundle`
- `--offset` for paging/resume
- `--limit`
- `--refresh`

Every fetch/update writes a JSON manifest under:

```text
data/manifests/
```

### Provider Symbol Mapping

Alpha Vantage symbols and yfinance symbols do not always match.

Provider mappings live at:

```text
data/symbol_mappings.parquet
```

Managed by:

```text
src/tradescope/data/symbol_mapping.py
```

Current deterministic yfinance candidate examples:

```text
BRK.B  -> BRK-B
AAC-W  -> AAC-WT
AAC-WS -> AAC-WT
AAC-U  -> AAC-UN
AAC-R  -> AAC-RT
```

Successful mappings are persisted. Processed OHLCV remains keyed by the original research/security-master symbol.

Inspect mappings:

```bash
.venv/bin/tradescope data securities mappings
```

## Important Implementation Files

Core CLI:

```text
src/tradescope/cli.py
```

Backtest data loading:

```text
src/tradescope/backtesting/runner.py
```

Data store:

```text
src/tradescope/data/store.py
```

Security master:

```text
src/tradescope/data/security_master.py
```

Symbol mapping:

```text
src/tradescope/data/symbol_mapping.py
```

Maintenance jobs:

```text
src/tradescope/data/maintenance.py
```

yfinance provider and supported components:

```text
src/tradescope/data/yfinance_provider.py
```

Tests to check for data pipeline work:

```bash
.venv/bin/python -m pytest tests/test_data.py tests/test_cli.py tests/test_runner.py tests/test_audit.py
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

## Current Known Gaps

These are the next pieces needed to move toward true survivorship-bias mitigation.

### 1. Manual/Importable Symbol Mappings — DONE

Implemented in `src/tradescope/data/symbol_mapping.py` and `src/tradescope/cli.py`.

`SymbolMap` now has:

- `upsert(source_symbol, provider, provider_symbol, status, reason, source)` — generalized upsert with arbitrary status.
- `upsert_active(...)` — backwards-compat wrapper that calls `upsert` with `status="active"`.
- `import_csv(path)` — reads a CSV and upserts each row. Returns count imported.

`read()` now always returns all expected columns (including `reason`) even when all values are null.

CLI:

```bash
.venv/bin/tradescope data securities mappings
.venv/bin/tradescope data securities mappings add --source-symbol BRK.B --provider yfinance --provider-symbol BRK-B --reason "manual verified"
.venv/bin/tradescope data securities mappings import --path mappings.csv
```

CSV columns: `source_symbol`, `provider`, `provider_symbol` (required); `source`, `status`, `reason` (optional, defaults: `security_master`, `active`, null).

### 2. Audit Should Understand IPOs And Delistings

Current audit can mark partial histories as bad even when partial history is expected.

Needed behavior:

- If `ipo_date` is after requested start, missing pre-IPO data is okay.
- If `delisting_date` is before requested end, missing post-delisting data is okay.
- Use actual observed `history_start` / `history_end` plus listing metadata.
- Distinguish:
  - valid partial due to IPO
  - valid partial due to delisting
  - invalid gap inside active listing life
  - provider unavailable

Likely files:

```text
src/tradescope/data/maintenance.py
src/tradescope/data/security_master.py
tests/test_audit.py
tests/test_data.py
```

### 3. Historical Universe Snapshots

The current security master tells us active/delisted securities, but not complete membership of each tradable universe at each historical date.

Needed:

- A historical universe source/table.
- Ability to ask: “what securities were eligible on date X?”
- For backtests, build dynamic universes per rebalance date instead of static current constituents.

Possible table:

```text
data/universe_memberships.parquet
```

Candidate columns:

```text
universe
symbol
start_date
end_date
source
source_as_of_date
notes
```

First useful universes:

- all listed U.S. stocks from security master by listing/delisting date
- S&P 500 historical constituents, once a reliable source is chosen
- NASDAQ/NYSE current/exchange subsets, with clear warnings that current lists are survivorship biased

### 4. Batch Collection Ergonomics

`--offset` and `--limit` exist, but large collection runs still need better ergonomics.

Needed:

- Better progress output.
- Manifest browsing CLI.
- Resume command that can continue from the last manifest.
- Skip known unavailable symbols unless `--refresh-unavailable` or date range differs.

Suggested CLI:

```bash
.venv/bin/tradescope data manifests
.venv/bin/tradescope data manifests show <manifest_id>
.venv/bin/tradescope data collect-securities --resume-last
```

### 5. Component Collection Policy

The user wants a generous data pool, but not everything yfinance exposes.

Current desired components:

- dividends
- splits
- capital gains
- all income statements
- all balance sheets
- all cash flows
- earnings info

Explicitly excluded:

- actions
- estimates

Check `src/tradescope/data/yfinance_provider.py` before adding/removing components.

### 6. Strategy Research Is Paused

Do not continue strategy optimization unless the user asks.

Before strategy work, read:

```text
STRATEGY_RESEARCH_LOG.md
```

The current data-pipeline priority is survivorship-bias mitigation.

## Recommended Next Session Plan

1. Read `AGENTS.md` and this file.
2. Run:

   ```bash
   git status --short
   .venv/bin/tradescope --help
   .venv/bin/tradescope data --help
   .venv/bin/python -m pytest tests/test_data.py tests/test_cli.py tests/test_runner.py tests/test_audit.py
   ```

3. ~~Implement manual/importable symbol mappings.~~ (done)
4. Add audit logic for IPO/delisting-valid partial histories.
5. Add tests.
6. Run full suite and ruff.
7. Update `README.md`, `DEVELOPMENT_GUIDE.md`, `AGENTS.md`, and this handoff when behavior changes.
8. Commit with a small, descriptive message.

## Git Workflow

Use rebase-first workflow:

```bash
git pull --rebase origin main
```

Avoid merge commits for routine sync.

Do not force push or rewrite history unless the user explicitly asks.

## Safety Notes

This is financial research software.

Never imply a strategy is production-safe just because backtests pass.

Preserve:

- raw data
- processed data
- manifests
- result runs
- strategy logs

Prefer transparent, auditable behavior over clever automation.
