import pandas as pd

from tradingv2.results.compare import apply_filters, best_run_from_sweep
from tradingv2.results.store import ResultStore
from tradingv2.results.compare import display_columns, rank_results


def test_rank_results() -> None:
    rows = [
        {"run_id": "a", "Total Return [%]": 1.0, "param.fast": 10},
        {"run_id": "b", "Total Return [%]": 2.0, "param.fast": 20},
    ]

    summary = rank_results(rows, "Total Return [%]")

    assert summary.iloc[0]["run_id"] == "b"
    assert "param.fast" in display_columns(pd.DataFrame(rows))


def test_write_sweep_manifest(tmp_path) -> None:
    path = ResultStore(tmp_path).write_sweep_manifest(
        "demo",
        tmp_path / "demo_sweep.csv",
        [{"run_id": "a", "Total Return [%]": 1.0}],
        "Total Return [%]",
        False,
    )

    assert path.exists()
    assert path.name == "demo_sweep_manifest.json"


def test_best_run_from_sweep_csv(tmp_path) -> None:
    sweep_path = tmp_path / "sweep.csv"
    pd.DataFrame(
        [
            {"run_id": "a", "Total Return [%]": 1.0},
            {"run_id": "b", "Total Return [%]": 2.0},
        ]
    ).to_csv(sweep_path, index=False)

    best = best_run_from_sweep(sweep_path, rank_by="Total Return [%]")

    assert best["run_id"] == "b"


def test_apply_filters() -> None:
    summary = pd.DataFrame(
        [
            {"run_id": "a", "param.fast_window": 10},
            {"run_id": "b", "param.fast_window": 20},
        ]
    )

    filtered = apply_filters(summary, ("param.fast_window=20",))

    assert filtered.iloc[0]["run_id"] == "b"
