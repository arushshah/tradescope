from click.testing import CliRunner

from tradingv2.cli import cli


def test_top_level_help_lists_documented_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ["backtest", "clear-data", "data", "fetch", "results", "strategy", "universe"]:
        assert command in result.output


def test_command_group_help_lists_documented_subcommands():
    runner = CliRunner()
    expected = {
        "backtest": ["run", "split", "sweep"],
        "data": ["clear-data", "fetch", "inspect", "validate"],
        "results": ["audit", "best", "compare", "inspect", "show"],
        "strategy": ["describe", "init", "list"],
        "universe": ["list", "show"],
    }

    for group, commands in expected.items():
        result = runner.invoke(cli, [group, "--help"])

        assert result.exit_code == 0
        for command in commands:
            assert command in result.output


def test_top_level_clear_data_matches_documented_execution(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "clear-data",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--processed-dir",
            str(tmp_path / "processed"),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "No data entries found." in result.output


def test_universe_commands_show_presets():
    runner = CliRunner()

    list_result = runner.invoke(cli, ["universe", "list"])
    show_result = runner.invoke(cli, ["universe", "show", "sp500"])

    assert list_result.exit_code == 0
    assert "sp500" in list_result.output
    assert show_result.exit_code == 0
    assert "AAPL" in show_result.output
    assert "BRK-B" in show_result.output
