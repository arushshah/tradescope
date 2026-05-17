from click.testing import CliRunner

from tradescope.cli import cli


def test_top_level_help_lists_documented_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ["backtest", "data", "reference", "results", "strategy", "universe"]:
        assert command in result.output
    assert "clear-data" not in result.output
    assert "fetch" not in result.output


def test_command_group_help_lists_documented_subcommands():
    runner = CliRunner()
    expected = {
        "backtest": ["run", "split", "sweep"],
        "data": ["audit", "clear", "fetch", "inspect", "update", "validate"],
        "results": ["audit", "best", "compare", "inspect", "show"],
        "strategy": ["describe", "init", "list"],
        "universe": ["list", "show"],
    }

    for group, commands in expected.items():
        result = runner.invoke(cli, [group, "--help"])

        assert result.exit_code == 0
        for command in commands:
            assert command in result.output


def test_data_clear_matches_documented_execution(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "data",
            "clear",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--processed-dir",
            str(tmp_path / "processed"),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "No data entries found." in result.output


def test_removed_top_level_data_shortcuts_are_not_available():
    runner = CliRunner()

    assert runner.invoke(cli, ["fetch", "--help"]).exit_code != 0
    assert runner.invoke(cli, ["clear-data", "--help"]).exit_code != 0


def test_reference_lists_full_command_tree():
    result = CliRunner().invoke(cli, ["reference"])

    assert result.exit_code == 0
    assert "tradescope backtest run --config VALUE" in result.output
    assert "tradescope data fetch --config VALUE" in result.output
    assert "tradescope data clear" in result.output
    assert "tradescope fetch" not in result.output
    assert "tradescope clear-data" not in result.output


def test_universe_commands_show_presets():
    runner = CliRunner()

    list_result = runner.invoke(cli, ["universe", "list"])
    show_result = runner.invoke(cli, ["universe", "show", "sp500"])

    assert list_result.exit_code == 0
    assert "sp500" in list_result.output
    assert show_result.exit_code == 0
    assert "AAPL" in show_result.output
    assert "BRK-B" in show_result.output
