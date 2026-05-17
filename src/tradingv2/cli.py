from __future__ import annotations

from pathlib import Path

import click

from tradingv2.backtesting.optimization import expand_param_grid
from tradingv2.backtesting.runner import BacktestRunner
from tradingv2.config import load_config
from tradingv2.data.maintenance import (
    audit_dataset,
    default_update_end,
    fetch_configured_components,
    refresh_symbols,
    rows_to_frame,
    symbols_needing_repair,
    update_dataset,
)
from tradingv2.data.quality import build_quality_report, reports_to_frame
from tradingv2.data.store import MarketDataStore
from tradingv2.results.compare import (
    best_run_from_sweep,
    build_run_row,
    display_columns,
    rank_results,
)
from tradingv2.results.audit import audit_run
from tradingv2.results.store import ResultStore
from tradingv2.strategies.registry import describe_strategy, list_strategy_metadata
from tradingv2.strategies.template import write_strategy_template
from tradingv2.universe import load_universe_presets, resolve_preset_file


@click.group()
def cli() -> None:
    """TradingV2 research CLI."""


@cli.group()
def backtest() -> None:
    """Run and compare backtests."""


@backtest.command("run")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
def run_backtest(config_path: Path) -> None:
    """Run one backtest from a YAML config."""
    config = load_config(config_path)
    result = BacktestRunner(config).run()
    click.echo(f"Run complete: {result.run_id}")
    click.echo(f"Artifacts: {result.run_dir}")
    click.echo(result.stats.to_string())


@backtest.command("sweep")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--rank-by", default="Total Return [%]", show_default=True)
@click.option("--ascending", is_flag=True, help="Rank smaller values first.")
@click.option("--top-n", default=10, show_default=True, type=click.IntRange(min=1))
def sweep_backtests(config_path: Path, rank_by: str, ascending: bool, top_n: int) -> None:
    """Run a grid sweep from list-valued strategy params."""
    base_config = load_config(config_path)
    configs = expand_param_grid(base_config)
    rows = []
    for config in configs:
        result = BacktestRunner(config).run()
        rows.append(build_run_row(Path(result.run_dir), config.strategy.params))

    summary = rank_results(rows, rank_by, ascending=ascending)
    output_path = base_config.results.output_dir / f"{base_config.name}_sweep.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_path, index=False)
    manifest_path = ResultStore(base_config.results.output_dir).write_sweep_manifest(
        base_config.name,
        output_path,
        summary.to_dict(orient="records"),
        rank_by,
        ascending,
    )
    click.echo(f"Sweep complete: {len(summary)} runs")
    click.echo(f"Summary: {output_path}")
    click.echo(f"Manifest: {manifest_path}")
    click.echo(summary[display_columns(summary)].head(top_n).to_string(index=False))


@backtest.command("split")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--train-start", required=True)
@click.option("--train-end", required=True)
@click.option("--test-start", required=True)
@click.option("--test-end", required=True)
@click.option("--rank-by", default="Total Return [%]", show_default=True)
def split_backtest(
    config_path: Path,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    rank_by: str,
) -> None:
    """Run one config over train and test date ranges."""
    from copy import deepcopy
    from datetime import date

    base_config = load_config(config_path)
    rows = []
    for split_name, start, end in [
        ("train", train_start, train_end),
        ("test", test_start, test_end),
    ]:
        config = deepcopy(base_config)
        config.name = f"{base_config.name}_{split_name}"
        config.start = date.fromisoformat(start)
        config.end = date.fromisoformat(end)
        result = BacktestRunner(config).run()
        row = build_run_row(Path(result.run_dir), config.strategy.params)
        row["split"] = split_name
        rows.append(row)

    summary = rank_results(rows, rank_by, ascending=False)
    output_path = base_config.results.output_dir / f"{base_config.name}_split.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_path, index=False)
    click.echo(f"Split summary: {output_path}")
    columns = ["split", *[column for column in display_columns(summary) if column != "split"]]
    click.echo(summary[columns].to_string(index=False))


@cli.group()
def data() -> None:
    """Fetch and manage market data."""


@data.command("fetch")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
def fetch_data(config_path: Path) -> None:
    """Fetch raw data and write processed data from a config."""
    fetch_data_from_config(config_path)


@cli.command("fetch")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
def fetch_data_alias(config_path: Path) -> None:
    """Fetch raw data and write processed data from a config."""
    fetch_data_from_config(config_path)


def fetch_data_from_config(config_path: Path) -> None:
    config = load_config(config_path)
    config.data.refresh = True
    runner = BacktestRunner(config)
    loaded = runner._load_data()
    component_files = fetch_configured_components(config)
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir, config.data.component_dir)
    unavailable = [
        entry
        for entry in store.list_unavailable()
        if entry.provider == config.data.provider
        and entry.interval == config.interval
        and entry.symbol in set(config.symbols)
    ]
    click.echo(f"Loaded {len(loaded)} symbol(s)")
    if component_files:
        click.echo(f"Loaded {component_files} component file(s)")
    if unavailable:
        click.echo(f"Skipped unavailable symbol(s): {len(unavailable)}")


@data.command("update")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--to-today",
    is_flag=True,
    help="Extend canonical coverage through the current run date instead of config data.coverage_end.",
)
def update_data(config_path: Path, to_today: bool) -> None:
    """Update canonical local data coverage for a config."""
    config = load_config(config_path)
    end = default_update_end() if to_today else None
    counts = update_dataset(config, end=end)
    click.echo(f"Updated OHLCV for {counts['ohlcv_symbols']} symbol(s)")
    if counts["component_files"]:
        click.echo(f"Updated {counts['component_files']} component file(s)")


@data.command("audit")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--fix", is_flag=True, help="Refresh symbols with missing coverage or quality warnings.")
def audit_data(config_path: Path, fix: bool) -> None:
    """Audit canonical local data coverage and optionally repair problem symbols."""
    config = load_config(config_path)
    rows = audit_dataset(config)
    frame = rows_to_frame(rows)
    click.echo(frame.to_string(index=False))

    repair_symbols = symbols_needing_repair(rows)
    if not repair_symbols:
        click.echo("Data audit passed.")
        return

    click.echo(f"Symbols needing repair: {len(repair_symbols)}")
    if fix:
        refresh_symbols(config, repair_symbols)
        click.echo(f"Refreshed {len(repair_symbols)} symbol(s)")
    else:
        raise click.ClickException("data audit found issues")


@data.command("inspect")
@click.option("--raw-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("data/raw"), show_default=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--layer", type=click.Choice(["raw", "processed"]), help="Only show one data layer.")
@click.option("--symbol", help="Only show data for this symbol.")
def inspect_data(
    raw_dir: Path,
    processed_dir: Path,
    layer: str | None,
    symbol: str | None,
) -> None:
    """Inspect local raw and processed market data."""
    entries = MarketDataStore(raw_dir, processed_dir).list_entries(layer=layer, symbol=symbol)
    if not entries:
        click.echo("No data entries found.")
        return

    import pandas as pd

    rows = [
        {
            "layer": entry.layer,
            "provider": entry.provider,
            "symbol": entry.symbol,
            "start": entry.start,
            "end": entry.end,
            "interval": entry.interval,
            "rows": entry.rows,
            "first_timestamp": entry.first_timestamp,
            "last_timestamp": entry.last_timestamp,
            "path": str(entry.path),
        }
        for entry in entries
    ]
    click.echo(pd.DataFrame(rows).to_string(index=False))


@data.command("clear-data")
@click.option("--raw-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("data/raw"), show_default=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--layer", type=click.Choice(["raw", "processed"]), help="Only remove one data layer.")
@click.option("--symbol", help="Only remove data for this symbol.")
@click.option("--yes", is_flag=True, help="Confirm deletion without prompting.")
def clear_data(
    raw_dir: Path,
    processed_dir: Path,
    layer: str | None,
    symbol: str | None,
    yes: bool,
) -> None:
    """Remove local raw and processed market data."""
    clear_data_entries(raw_dir, processed_dir, layer, symbol, yes)


@cli.command("clear-data")
@click.option("--raw-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("data/raw"), show_default=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--layer", type=click.Choice(["raw", "processed"]), help="Only remove one data layer.")
@click.option("--symbol", help="Only remove data for this symbol.")
@click.option("--yes", is_flag=True, help="Confirm deletion without prompting.")
def clear_data_alias(
    raw_dir: Path,
    processed_dir: Path,
    layer: str | None,
    symbol: str | None,
    yes: bool,
) -> None:
    """Remove local raw and processed market data."""
    clear_data_entries(raw_dir, processed_dir, layer, symbol, yes)


def clear_data_entries(
    raw_dir: Path,
    processed_dir: Path,
    layer: str | None,
    symbol: str | None,
    yes: bool,
) -> None:
    store = MarketDataStore(raw_dir, processed_dir)
    entries = store.list_entries(layer=layer, symbol=symbol)
    if not entries:
        click.echo("No data entries found.")
        return
    if not yes:
        target = symbol.upper() if symbol else "all symbols"
        layer_label = layer or "all layers"
        click.confirm(f"Remove {len(entries)} data file(s) from {layer_label} for {target}?", abort=True)
    removed = store.clear(layer=layer, symbol=symbol)
    click.echo(f"Removed {len(removed)} data file(s).")


@data.command("validate")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
def validate_data(config_path: Path) -> None:
    """Validate market data loaded for a config."""
    config = load_config(config_path)
    runner = BacktestRunner(config)
    loaded = runner._load_data()
    reports = [build_quality_report(symbol, frame) for symbol, frame in loaded.items()]
    summary = reports_to_frame(reports)
    click.echo(summary.to_string(index=False))
    if any(report.status != "ok" for report in reports):
        raise click.ClickException("data validation completed with warnings")


@cli.group()
def universe() -> None:
    """Inspect universe presets."""


@universe.command("list")
@click.option(
    "--preset-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("configs/universes.yaml"),
    show_default=True,
)
def list_universes(preset_file: Path) -> None:
    """List configured universe presets."""
    presets = load_universe_presets(preset_file)
    if not presets:
        click.echo("No universe presets found.")
        return

    import pandas as pd

    rows = [
        {
            "name": preset.name,
            "symbols": len(preset.symbols),
            "description": preset.description,
        }
        for preset in presets.values()
    ]
    click.echo(pd.DataFrame(rows).to_string(index=False))


@universe.command("show")
@click.argument("name")
@click.option(
    "--preset-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("configs/universes.yaml"),
    show_default=True,
)
def show_universe(name: str, preset_file: Path) -> None:
    """Show symbols in one universe preset."""
    presets = load_universe_presets(resolve_preset_file(preset_file))
    if name not in presets:
        raise click.ClickException(f"unknown universe preset: {name}")
    preset = presets[name]
    click.echo(f"Name: {preset.name}")
    if preset.description:
        click.echo(f"Description: {preset.description}")
    click.echo(f"Symbols ({len(preset.symbols)}):")
    for symbol in preset.symbols:
        click.echo(f"  {symbol}")


@cli.group()
def results() -> None:
    """Inspect saved results."""


@results.command("show")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def show_results(run_dir: Path) -> None:
    """Show stats for a saved run."""
    stats_path = run_dir / "stats.csv"
    if not stats_path.exists():
        raise click.ClickException(f"missing stats.csv in {run_dir}")

    import pandas as pd

    stats = pd.read_csv(stats_path, index_col=0)
    click.echo(stats.to_string())


@results.command("compare")
@click.argument("run_dirs", nargs=-1, required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--from-sweep", "sweep_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--rank-by", default="Total Return [%]", show_default=True)
@click.option("--ascending", is_flag=True, help="Rank smaller values first.")
@click.option("--output", "output_path", type=click.Path(path_type=Path))
@click.option("--where", "filters", multiple=True, help="Filter rows, for example param.fast_window=20.")
def compare_results(
    run_dirs: tuple[Path, ...],
    sweep_path: Path | None,
    rank_by: str,
    ascending: bool,
    output_path: Path | None,
    filters: tuple[str, ...],
) -> None:
    """Compare saved run directories."""
    from tradingv2.results.compare import apply_filters, read_sweep

    if sweep_path:
        summary = read_sweep(sweep_path, rank_by=rank_by, ascending=ascending)
    else:
        if not run_dirs:
            raise click.ClickException("provide run dirs or --from-sweep")
        rows = [build_run_row(run_dir) for run_dir in run_dirs]
        summary = rank_results(rows, rank_by, ascending=ascending)
    try:
        summary = apply_filters(summary, filters)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(output_path, index=False)
        click.echo(f"Comparison saved: {output_path}")
    click.echo(summary[display_columns(summary)].to_string(index=False))


@results.command("best")
@click.argument("sweep_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--rank-by", default=None, help="Metric to rank by. Defaults to manifest ranking.")
@click.option("--ascending", is_flag=True, help="Rank smaller values first.")
@click.option("--where", "filters", multiple=True, help="Filter rows, for example param.fast_window=20.")
def best_result(sweep_path: Path, rank_by: str | None, ascending: bool, filters: tuple[str, ...]) -> None:
    """Show the best run from a sweep CSV or manifest."""
    try:
        best = best_run_from_sweep(sweep_path, rank_by=rank_by, ascending=ascending, filters=filters)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Best run: {best.get('run_id')}")
    if best.get("run_dir"):
        click.echo(f"Run dir: {best['run_dir']}")
    for key, value in best.items():
        if key.startswith("param.") or key in {
            "Total Return [%]",
            "Benchmark Total Return [%]",
            "Max Drawdown [%]",
            "Sharpe Ratio",
            "Sortino Ratio",
            "Calmar Ratio",
            "Total Trades",
            "Win Rate [%]",
        }:
            click.echo(f"{key}: {value}")


@results.command("inspect")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def inspect_result(run_dir: Path) -> None:
    """Inspect config, key metrics, plots, and trades for one run."""
    config_path = run_dir / "config.yaml"
    stats_path = run_dir / "stats.csv"
    trades_path = run_dir / "trades.csv"
    report_path = run_dir / "report.html"
    benchmark_equity_path = run_dir / "benchmark_equity.csv"
    benchmark_returns_path = run_dir / "benchmark_returns.csv"
    plots_dir = run_dir / "plots"

    if not stats_path.exists():
        raise click.ClickException(f"missing stats.csv in {run_dir}")

    import pandas as pd
    import yaml

    config = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}

    stats = pd.read_csv(stats_path, index_col=0)["value"]
    click.echo(f"Run: {run_dir.name}")
    if config:
        click.echo(f"Name: {config.get('name')}")
        click.echo(f"Symbols: {', '.join(config.get('symbols', []))}")
        strategy = config.get("strategy", {})
        click.echo(f"Strategy: {strategy.get('name') or strategy.get('path') or strategy.get('module')}")

    key_metrics = [
        "Total Return [%]",
        "Benchmark Total Return [%]",
        "Max Drawdown [%]",
        "Sharpe Ratio",
        "Sortino Ratio",
        "Calmar Ratio",
        "Total Trades",
        "Win Rate [%]",
    ]
    click.echo("\nMetrics:")
    for metric in key_metrics:
        if metric in stats:
            click.echo(f"{metric}: {stats[metric]}")

    if trades_path.exists():
        trades = pd.read_csv(trades_path)
        click.echo(f"\nTrades: {len(trades)} rows at {trades_path}")
    else:
        click.echo("\nTrades: not saved")

    if benchmark_equity_path.exists():
        click.echo(f"Benchmark equity: {benchmark_equity_path}")
    if benchmark_returns_path.exists():
        click.echo(f"Benchmark returns: {benchmark_returns_path}")
    if report_path.exists():
        click.echo(f"Report: {report_path}")

    if plots_dir.exists():
        plots = sorted(plots_dir.glob("*.png"))
        click.echo("\nPlots:")
        for plot in plots:
            click.echo(str(plot))


@results.command("audit")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def audit_result(run_dir: Path) -> None:
    """Audit saved run artifacts for common backtest integrity issues."""
    report = audit_run(run_dir)
    status = "PASS" if report.passed else "FAIL"
    click.echo(f"Audit: {status}")
    click.echo(f"Run dir: {run_dir}")
    if report.errors:
        click.echo("\nErrors:")
        for error in report.errors:
            click.echo(f"- {error}")
    if report.warnings:
        click.echo("\nWarnings:")
        for warning in report.warnings:
            click.echo(f"- {warning}")
    if not report.passed:
        raise click.ClickException("audit failed")


@cli.group()
def strategy() -> None:
    """Create and manage custom strategies."""


@strategy.command("list")
def list_strategies() -> None:
    """List built-in strategies."""
    import pandas as pd

    rows = [
        {
            "name": metadata.name,
            "description": metadata.description,
            "params": ", ".join(f"{k}={v}" for k, v in metadata.params.items()),
        }
        for metadata in list_strategy_metadata()
    ]
    click.echo(pd.DataFrame(rows).to_string(index=False))


@strategy.command("describe")
@click.argument("name")
def describe_strategy_command(name: str) -> None:
    """Describe one built-in strategy."""
    metadata = describe_strategy(name)
    if metadata is None:
        raise click.ClickException(f"unknown built-in strategy: {name}")
    click.echo(f"Name: {metadata.name}")
    click.echo(f"Description: {metadata.description}")
    click.echo("Params:")
    if not metadata.params:
        click.echo("  none")
    for key, value in metadata.params.items():
        click.echo(f"  {key}: {value}")


@strategy.command("init")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--force", is_flag=True, help="Overwrite an existing strategy file.")
def init_strategy(path: Path, force: bool) -> None:
    """Create a custom strategy template."""
    try:
        strategy_path = write_strategy_template(path, overwrite=force)
    except FileExistsError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created strategy template: {strategy_path}")
