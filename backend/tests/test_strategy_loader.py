import pytest
from pathlib import Path
from services.backtest.strategy_loader import (
    load_strategy_from_file,
    scan_strategies,
)
from services.backtest.base import ScreenerStrategy


EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"


class TestLoadStrategyFromFile:
    def test_load_screener(self):
        filepath = EXAMPLES_DIR / "ma_tangle_breakout_screener.py"
        strategies = load_strategy_from_file(filepath)
        assert len(strategies) >= 1
        s = strategies[0]
        assert isinstance(s, type)
        assert issubclass(s, ScreenerStrategy)
        assert s.name == "月线均线缠绕"

    def test_load_another_screener(self):
        filepath = EXAMPLES_DIR / "roe_screener.py"
        strategies = load_strategy_from_file(filepath)
        assert len(strategies) >= 1
        s = strategies[0]
        assert issubclass(s, ScreenerStrategy)

    def test_load_nonexistent_file(self):
        filepath = Path("/nonexistent/file.py")
        with pytest.raises(FileNotFoundError):
            load_strategy_from_file(filepath)

    def test_load_bad_syntax_file(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n")
        with pytest.raises(SyntaxError):
            load_strategy_from_file(bad)


class TestScanStrategies:
    def test_scan_examples_dir(self):
        results = scan_strategies(EXAMPLES_DIR)
        assert len(results) >= 2
        names = [r["name"] for r in results]
        assert "月线均线缠绕" in names

    def test_scan_returns_correct_structure(self):
        results = scan_strategies(EXAMPLES_DIR)
        for r in results:
            assert "name" in r
            assert "description" in r
            assert "strategy_type" in r
            assert "params" in r
            assert "filepath" in r
            assert r["strategy_type"] in ("screener", "trader", "buy", "sell")

    def test_scan_empty_dir(self, tmp_path):
        results = scan_strategies(tmp_path)
        assert results == []

    def test_scan_skips_bad_files(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n")
        results = scan_strategies(tmp_path)
        assert results == []
