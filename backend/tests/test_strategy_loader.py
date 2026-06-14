import pytest
from pathlib import Path
from services.backtest.strategy_loader import (
    load_strategy_from_file,
    scan_strategies,
)
from services.backtest.strategy_base import Strategy


DEPLOYED_DIR = Path(__file__).resolve().parent.parent / "services" / "backtest" / "strategies" / "deployed"


class TestLoadStrategyFromFile:
    def test_load_strategy(self):
        filepath = DEPLOYED_DIR / "ma_tangle_value_strategy.py"
        strategies = load_strategy_from_file(filepath)
        assert len(strategies) >= 1
        s = strategies[0]
        assert isinstance(s, type)
        assert issubclass(s, Strategy)
        assert s.name == "月线均线缠绕价值策略"

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
    def test_scan_deployed_dir(self):
        results = scan_strategies(DEPLOYED_DIR)
        assert len(results) >= 1
        names = [r["name"] for r in results]
        assert "月线均线缠绕价值策略" in names

    def test_scan_returns_correct_structure(self):
        results = scan_strategies(DEPLOYED_DIR)
        for r in results:
            assert "name" in r
            assert "description" in r
            assert "strategy_type" in r
            assert "params" in r
            assert "filepath" in r
            assert r["strategy_type"] in (
                "screener",
                "trader",
                "buy",
                "sell",
                "strategy",
            )

    def test_scan_empty_dir(self, tmp_path):
        results = scan_strategies(tmp_path)
        assert results == []

    def test_scan_skips_bad_files(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n")
        results = scan_strategies(tmp_path)
        assert results == []

    def test_scan_includes_frequency_overridable(self):
        # 每个返回 dict 都应有 frequency_overridable 字段
        results = scan_strategies(DEPLOYED_DIR)
        for r in results:
            assert "frequency_overridable" in r
            assert isinstance(r["frequency_overridable"], bool)

    def test_scan_finds_new_strategy_subclass(self):
        # 新 Strategy 基类的子类应该被扫描到,且 strategy_type == "strategy"
        results = scan_strategies(DEPLOYED_DIR)
        names = [r["name"] for r in results]
        assert "月线均线缠绕价值策略" in names
        entry = next(r for r in results if r["name"] == "月线均线缠绕价值策略")
        assert entry["strategy_type"] == "strategy"
        assert entry["frequency_overridable"] is False
        assert entry["frequency"] == "monthly"


class TestStrategyBaseExclusion:
    def test_strategy_base_excluded(self, tmp_path):
        # 直接定义一个仅含 Strategy 基类(无子类)的文件,扫描结果应为空
        f = tmp_path / "only_base.py"
        f.write_text(
            "from services.backtest.strategy_base import Strategy\n"
            "X = Strategy  # 仅引用,不创建子类\n"
        )
        results = scan_strategies(tmp_path)
        assert results == []

    def test_new_strategy_subclass_loaded(self, tmp_path):
        # 在临时目录中定义一个 Strategy 子类,应该被加载
        f = tmp_path / "mine.py"
        f.write_text(
            "from services.backtest.strategy_base import Strategy\n"
            "class MyStrat(Strategy):\n"
            "    name = 'mine'\n"
            "    description = 'd'\n"
            "    frequency = 'weekly'\n"
            "    frequency_overridable = True\n"
            "    params = {}\n"
        )
        classes = load_strategy_from_file(f)
        assert len(classes) == 1
        assert classes[0].__name__ == "MyStrat"
        assert issubclass(classes[0], Strategy)

        results = scan_strategies(tmp_path)
        assert len(results) == 1
        r = results[0]
        assert r["name"] == "mine"
        assert r["strategy_type"] == "strategy"
        assert r["frequency"] == "weekly"
        assert r["frequency_overridable"] is True
