import pytest

from tradingv2.strategies.template import write_strategy_template


def test_write_strategy_template(tmp_path) -> None:
    path = write_strategy_template(tmp_path / "my_strategy")

    assert path.name == "my_strategy.py"
    assert "def generate_signals" in path.read_text(encoding="utf-8")


def test_write_strategy_template_requires_force(tmp_path) -> None:
    path = write_strategy_template(tmp_path / "my_strategy.py")

    with pytest.raises(FileExistsError):
        write_strategy_template(path)
