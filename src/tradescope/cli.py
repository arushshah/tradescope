from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import click

from tradescope.backtesting.optimization import expand_param_grid
from tradescope.backtesting.runner import BacktestRunner
from tradescope.config import load_config
from tradescope.data.alpha_vantage import fetch_listing_status
from tradescope.data.collection_manifest import (
    write_config_collection_manifest,
    write_store_update_manifest,
)
from tradescope.data.maintenance import (
    audit_dataset,
    audit_stored_dataset,
    default_update_end,
    fetch_configured_components,
    repair_stored_dataset,
    refresh_symbols,
    rows_to_frame,
    stored_rows_needing_repair,
    symbols_needing_repair,
    update_dataset,
    update_symbols_dataset,
    update_stored_dataset,
)
from tradescope.data.quality import build_quality_report, reports_to_frame
from tradescope.data.security_master import SecurityMaster, default_security_master_path
from tradescope.data.symbol_mapping import SymbolMap, default_symbol_map_path
from tradescope.data.universe_memberships import (
    UniverseMembershipStore,
    build_us_listed_from_security_master,
    default_universe_memberships_path,
)
from tradescope.data.sp500 import fetch_sp500_changes, build_sp500_memberships
from tradescope.data.store import MarketDataStore
from tradescope.results.compare import (
    best_run_from_sweep,
    build_run_row,
    display_columns,
    rank_results,
)
from tradescope.results.audit import audit_run
from tradescope.results.store import ResultStore
from tradescope.strategies.registry import describe_strategy, list_strategy_metadata
from tradescope.strategies.template import write_strategy_template
from tradescope.universe import load_universe_presets, resolve_preset_file


@click.group()
def cli() -> None:
    """TradeScope research CLI."""


@cli.command("reference")
def command_reference() -> None:
    """Show the full command reference."""
    click.echo("TradeScope command reference")
    click.echo()
    for row in build_command_reference(cli):
        click.echo(row)


def build_command_reference(root: click.Group) -> list[str]:
    rows = [_format_reference_row(("tradescope",), root)]
    rows.extend(_walk_command_reference(root, ("tradescope",)))
    return rows


def _walk_command_reference(group: click.Group, prefix: tuple[str, ...]) -> Iterable[str]:
    for name, command in group.commands.items():
        if command.hidden:
            continue
        path = (*prefix, name)
        yield _format_reference_row(path, command)
        if isinstance(command, click.Group):
            yield from _walk_command_reference(command, path)


def _format_reference_row(path: tuple[str, ...], command: click.Command) -> str:
    usage = " ".join((*path, *_parameter_labels(command)))
    return f"{usage:<72} {command.get_short_help_str()}"


def _parameter_labels(command: click.Command) -> list[str]:
    labels = []
    for parameter in command.params:
        if isinstance(parameter, click.Option):
            option = parameter.opts[-1]
            if parameter.is_flag:
                labels.append(f"[{option}]")
            elif parameter.required:
                labels.append(f"{option} VALUE")
            else:
                labels.append(f"[{option} VALUE]")
        elif isinstance(parameter, click.Argument):
            labels.append(parameter.human_readable_name.upper())
    return labels


@cli.group()
def backtest() -> None:
    """Run backtests and sweeps."""


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
    """Manage local market data."""


@data.command("fetch")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
def fetch_data(config_path: Path) -> None:
    """Fetch raw data and write processed data from a config."""
    fetch_data_from_config(config_path)


def fetch_data_from_config(config_path: Path) -> None:
    config = load_config(config_path)
    config.data.refresh = True
    runner = BacktestRunner(config)
    loaded = runner._load_data()
    component_files = fetch_configured_components(config)
    counts = {"ohlcv_symbols": len(loaded), "component_files": component_files}
    store = MarketDataStore(config.data.raw_dir, config.data.processed_dir, config.data.component_dir)
    unavailable = [
        entry
        for entry in store.list_unavailable()
        if entry.provider == config.data.provider
        and entry.interval == config.interval
        and entry.symbol in set(config.symbols)
    ]
    manifest_path = write_config_collection_manifest(config, counts, config_path=config_path)
    click.echo(f"Loaded {len(loaded)} symbol(s)")
    if component_files:
        click.echo(f"Loaded {component_files} component file(s)")
    if unavailable:
        click.echo(f"Skipped unavailable symbol(s): {len(unavailable)}")
    click.echo(f"Manifest: {manifest_path}")


@data.command("update")
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path))
@click.option("--all", "all_entries", is_flag=True, help="Update every processed OHLCV dataset already stored locally.")
@click.option("--raw-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("data/raw"), show_default=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--provider", help="Only update datasets from this provider.")
@click.option("--interval", help="Only update datasets with this interval.")
@click.option("--end", "end_date", callback=lambda _ctx, _param, value: date.fromisoformat(value) if value else None)
@click.option(
    "--to-today",
    is_flag=True,
    help="Extend canonical coverage through the current run date instead of config data.coverage_end.",
)
def update_data(
    config_path: Path | None,
    all_entries: bool,
    raw_dir: Path,
    processed_dir: Path,
    provider: str | None,
    interval: str | None,
    end_date: date | None,
    to_today: bool,
) -> None:
    """Update config-scoped or store-wide local data coverage."""
    if all_entries:
        end = end_date or default_update_end()
        counts = update_stored_dataset(raw_dir, processed_dir, provider, interval, end=end)
        manifest_path = write_store_update_manifest(raw_dir, processed_dir, counts, provider, interval, end)
        click.echo(f"Updated OHLCV dataset(s): {counts['ohlcv_symbols']}")
        if counts["skipped_symbols"]:
            click.echo(f"Skipped dataset(s): {counts['skipped_symbols']}")
        click.echo(f"Manifest: {manifest_path}")
        return
    if config_path is None:
        raise click.ClickException("provide --config for config-scoped updates or --all for store-wide updates")
    config = load_config(config_path)
    end = end_date or (default_update_end() if to_today else None)
    counts = update_dataset(config, end=end)
    manifest_path = write_config_collection_manifest(config, counts, config_path=config_path)
    click.echo(f"Updated OHLCV for {counts['ohlcv_symbols']} symbol(s)")
    if counts["component_files"]:
        click.echo(f"Updated {counts['component_files']} component file(s)")
    click.echo(f"Manifest: {manifest_path}")


@data.command("collect-securities")
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--raw-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("data/raw"), show_default=True)
@click.option(
    "--component-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/components"),
    show_default=True,
)
@click.option("--status", multiple=True, default=["active"], show_default=True)
@click.option("--exchange", multiple=True, help="Only collect securities on these exchanges.")
@click.option("--asset-type", multiple=True, default=["Stock"], show_default=True)
@click.option("--source", default="alpha_vantage_listing_status", show_default=True)
@click.option("--start", "start_date", default="2010-01-01", show_default=True)
@click.option("--end", "end_date", default="2026-01-01", show_default=True)
@click.option("--interval", default="1d", show_default=True)
@click.option("--component", "components", multiple=True, default=["ohlcv", "research_bundle"], show_default=True)
@click.option("--offset", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--limit", type=click.IntRange(min=1), help="Collect only the first N matching symbols.")
@click.option("--refresh", is_flag=True, help="Refetch existing data and components.")
def collect_securities(
    processed_dir: Path,
    raw_dir: Path,
    component_dir: Path,
    status: tuple[str, ...],
    exchange: tuple[str, ...],
    asset_type: tuple[str, ...],
    source: str,
    start_date: str,
    end_date: str,
    interval: str,
    components: tuple[str, ...],
    offset: int,
    limit: int | None,
    refresh: bool,
) -> None:
    """Collect market data for securities from the security master."""
    master = SecurityMaster(default_security_master_path(processed_dir))
    symbols = master.symbols(
        statuses=list(status),
        exchanges=list(exchange) or None,
        asset_types=list(asset_type) or None,
        source=source,
        offset=offset,
        limit=limit,
    )
    if not symbols:
        raise click.ClickException("no matching securities found in security master")
    config, counts = update_symbols_dataset(
        symbols=symbols,
        start=date.fromisoformat(start_date),
        end=date.fromisoformat(end_date),
        interval=interval,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        component_dir=component_dir,
        components=list(components),
        refresh=refresh,
    )
    manifest_path = write_config_collection_manifest(config, counts)
    click.echo(f"Matched security master symbol(s): {len(symbols)}")
    click.echo(f"Updated OHLCV for {counts['ohlcv_symbols']} symbol(s)")
    if counts["component_files"]:
        click.echo(f"Updated {counts['component_files']} component file(s)")
    click.echo(f"Manifest: {manifest_path}")


@data.command("audit")
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path))
@click.option("--all", "all_entries", is_flag=True, help="Audit every processed OHLCV dataset already stored locally.")
@click.option("--raw-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("data/raw"), show_default=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--provider", help="Only audit datasets from this provider.")
@click.option("--interval", help="Only audit datasets with this interval.")
@click.option("--fix", is_flag=True, help="Refresh symbols with missing coverage or quality warnings.")
def audit_data(
    config_path: Path | None,
    all_entries: bool,
    raw_dir: Path,
    processed_dir: Path,
    provider: str | None,
    interval: str | None,
    fix: bool,
) -> None:
    """Audit config-scoped or store-wide local data coverage."""
    if all_entries:
        rows = audit_stored_dataset(raw_dir, processed_dir, provider, interval)
        if not rows:
            click.echo("No processed data entries found.")
            return
        frame = rows_to_frame(rows)
        click.echo(frame.to_string(index=False))
        repair_rows = stored_rows_needing_repair(rows)
        if not repair_rows:
            click.echo("Data audit passed.")
            return
        click.echo(f"Dataset(s) needing repair: {len(repair_rows)}")
        if fix:
            repaired = repair_stored_dataset(raw_dir, processed_dir, provider, interval)
            click.echo(f"Repaired {repaired} dataset(s)")
        else:
            raise click.ClickException("data audit found issues")
        return
    if config_path is None:
        raise click.ClickException("provide --config for config-scoped audits or --all for store-wide audits")
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


@data.group("securities", invoke_without_command=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--status", help="Only show one security status.")
@click.pass_context
def securities(ctx: click.Context, processed_dir: Path, status: str | None) -> None:
    """Inspect the local security master."""
    if ctx.invoked_subcommand is not None:
        return
    frame = SecurityMaster(default_security_master_path(processed_dir)).read()
    if status:
        frame = frame[frame["status"] == status]
    if frame.empty:
        click.echo("No security master entries found.")
        return
    click.echo(frame.to_string(index=False))


@securities.command("ingest-alpha-vantage")
@click.option("--api-key", envvar="ALPHAVANTAGE_API_KEY", required=True, help="Alpha Vantage API key.")
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option("--date", "as_of_date", callback=lambda _ctx, _param, value: date.fromisoformat(value) if value else None)
@click.option(
    "--state",
    type=click.Choice(["active", "delisted", "both"]),
    default="both",
    show_default=True,
)
def ingest_alpha_vantage_securities(
    api_key: str,
    processed_dir: Path,
    as_of_date: date | None,
    state: str,
) -> None:
    """Ingest Alpha Vantage active/delisted listing status."""
    states = ["active", "delisted"] if state == "both" else [state]
    master = SecurityMaster(default_security_master_path(processed_dir))
    total = 0
    for current_state in states:
        listings = fetch_listing_status(api_key, current_state, as_of_date=as_of_date)
        count = master.upsert_listing_status(listings)
        total += count
        click.echo(f"Ingested {count} {current_state} listing(s)")
    click.echo(f"Security master: {master.path}")
    click.echo(f"Total listing(s): {total}")


@securities.group("mappings", invoke_without_command=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.pass_context
def security_symbol_mappings(ctx: click.Context, processed_dir: Path) -> None:
    """Inspect and manage provider symbol mappings."""
    if ctx.invoked_subcommand is not None:
        return
    frame = SymbolMap(default_symbol_map_path(processed_dir)).read()
    if frame.empty:
        click.echo("No symbol mappings found.")
        return
    click.echo(frame.to_string(index=False))


@security_symbol_mappings.command("add")
@click.option("--source-symbol", required=True, help="Canonical research symbol (e.g. BRK.B).")
@click.option("--provider", required=True, help="Provider name (e.g. yfinance).")
@click.option("--provider-symbol", required=True, help="Provider-specific symbol (e.g. BRK-B).")
@click.option("--reason", help="Free-text note about this mapping.")
@click.option("--source", default="security_master", show_default=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
def mappings_add(
    source_symbol: str,
    provider: str,
    provider_symbol: str,
    reason: str | None,
    source: str,
    processed_dir: Path,
) -> None:
    """Add or update one provider symbol mapping."""
    SymbolMap(default_symbol_map_path(processed_dir)).upsert(
        source_symbol=source_symbol,
        provider=provider,
        provider_symbol=provider_symbol,
        status="active",
        reason=reason,
        source=source,
    )
    click.echo(f"Mapping upserted: {source_symbol.upper()} -> {provider}:{provider_symbol.upper()}")


@security_symbol_mappings.command("import")
@click.option("--path", "csv_path", required=True, type=click.Path(exists=True, path_type=Path), help="CSV file to import.")
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
def mappings_import(csv_path: Path, processed_dir: Path) -> None:
    """Import provider symbol mappings from a CSV file.

    Required CSV columns: source_symbol, provider, provider_symbol.
    Optional columns: source (default security_master), status (default active), reason.
    """
    try:
        count = SymbolMap(default_symbol_map_path(processed_dir)).import_csv(csv_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Imported {count} mapping(s) from {csv_path}")


@data.command("clear")
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


@data.group("universe", invoke_without_command=True)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.pass_context
def data_universe(ctx: click.Context, processed_dir: Path) -> None:
    """Manage historical universe membership snapshots."""
    if ctx.invoked_subcommand is not None:
        return
    store = UniverseMembershipStore(default_universe_memberships_path(processed_dir))
    frame = store.read()
    if frame.empty:
        click.echo("No universe memberships found.")
        return
    summary = (
        frame.groupby("universe")
        .agg(symbols=("symbol", "count"), source=("source", "first"))
        .reset_index()
    )
    click.echo(summary.to_string(index=False))


@data_universe.command("build")
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
@click.option(
    "--as-of",
    "as_of_date",
    default=None,
    help="Date the security master was current (YYYY-MM-DD). Defaults to today.",
)
def universe_build(processed_dir: Path, as_of_date: str | None) -> None:
    """Build the us_listed universe from the security master."""
    from datetime import date as _date

    effective_as_of = as_of_date or _date.today().isoformat()
    master = SecurityMaster(default_security_master_path(processed_dir))
    memberships = build_us_listed_from_security_master(master, effective_as_of)
    if not memberships:
        raise click.ClickException("no securities found in security master")
    store = UniverseMembershipStore(default_universe_memberships_path(processed_dir))
    count = store.upsert(memberships)
    click.echo(f"Upserted {count} membership(s) into universe 'us_listed'")
    click.echo(f"Path: {store.path}")


@data_universe.command("members")
@click.option("--universe", "universe_name", required=True, help="Universe name (e.g. us_listed).")
@click.option("--as-of", "as_of_date", required=True, help="Query date (YYYY-MM-DD).")
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
def universe_members(universe_name: str, as_of_date: str, processed_dir: Path) -> None:
    """List symbols that were members of a universe on a given date."""
    from datetime import date as _date

    try:
        query_date = _date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise click.ClickException(f"invalid date: {as_of_date}") from exc
    store = UniverseMembershipStore(default_universe_memberships_path(processed_dir))
    symbols = store.members_on(universe_name, query_date)
    if not symbols:
        click.echo(f"No members found for universe '{universe_name}' on {as_of_date}.")
        return
    click.echo(f"Universe: {universe_name}  as-of: {as_of_date}  members: {len(symbols)}")
    for symbol in symbols:
        click.echo(f"  {symbol}")


@data_universe.command("ingest-sp500")
@click.option(
    "--cache-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Local path to cache the downloaded CSV (avoids re-downloading).",
)
@click.option(
    "--as-of",
    "as_of_date",
    default=None,
    help="Source as-of date (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
def universe_ingest_sp500(cache_path: Path | None, as_of_date: str | None, processed_dir: Path) -> None:
    """Ingest S&P 500 historical constituents from fja05680/sp500 on GitHub.

    Downloads a changes CSV (~1996-present) and converts it to universe
    membership records stored in universe_memberships.parquet.

    Use --cache-path to save the CSV locally and avoid re-downloading.
    """
    from datetime import date as _date

    effective_as_of = as_of_date or _date.today().isoformat()
    click.echo("Downloading S&P 500 changes CSV...")
    try:
        changes = fetch_sp500_changes(cache_path=cache_path)
    except Exception as exc:
        raise click.ClickException(f"failed to fetch S&P 500 changes: {exc}") from exc
    click.echo(f"Loaded {len(changes)} change row(s)")
    memberships = build_sp500_memberships(changes, source_as_of_date=effective_as_of)
    store = UniverseMembershipStore(default_universe_memberships_path(processed_dir))
    count = store.upsert(memberships)
    click.echo(f"Upserted {count} membership record(s) into universe 'sp500'")
    click.echo(f"Path: {store.path}")


@data_universe.command("show")
@click.option("--universe", "universe_name", default=None, help="Filter to one universe.")
@click.option(
    "--processed-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data/processed"),
    show_default=True,
)
def universe_show(universe_name: str | None, processed_dir: Path) -> None:
    """Show raw universe membership rows."""
    store = UniverseMembershipStore(default_universe_memberships_path(processed_dir))
    frame = store.read(universe=universe_name)
    if frame.empty:
        click.echo("No universe memberships found.")
        return
    click.echo(frame.to_string(index=False))


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
    """Inspect, compare, and audit saved results."""


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
    from tradescope.results.compare import apply_filters, read_sweep

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
    """Inspect and scaffold custom strategies."""


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
