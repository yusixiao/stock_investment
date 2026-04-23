import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestBacktestStrategies:
    def test_list_strategies(self):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_strategies_have_correct_fields(self):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200
        data = resp.json()
        if data:
            s = data[0]
            assert "name" in s
            assert "strategy_type" in s
            assert "params" in s
            assert "filepath" in s


class TestBacktestRun:
    def test_empty_pipeline_returns_400(self):
        resp = client.post("/api/backtest/run", json={"pipeline": []})
        assert resp.status_code == 400

    @patch("routers.backtest._load_stock_data")
    def test_run_returns_task_id(self, mock_load):
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"TEST.SH": df}

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")

        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()


class TestBacktestStatus:
    def test_nonexistent_task(self):
        resp = client.get("/api/backtest/status/nonexistent")
        assert resp.status_code == 404

    def test_nonexistent_result(self):
        resp = client.get("/api/backtest/result/nonexistent")
        assert resp.status_code == 404


class TestTaskManagerSourceTask:
    def setup_method(self):
        from services.backtest.task_manager import TaskManager
        self.tm = TaskManager()

    def test_create_task_with_source_task_id(self):
        tid = self.tm.create_task(
            task_type="screener",
            source_task_id="src123",
        )
        result = self.tm.get_result(tid)
        assert result["source_task_id"] == "src123"

    def test_create_task_without_source_task_id(self):
        tid = self.tm.create_task(task_type="screener")
        result = self.tm.get_result(tid)
        assert result.get("source_task_id") is None

    def test_list_tasks_includes_source_task_id(self):
        tid = self.tm.create_task(
            task_type="screener",
            source_task_id="src456",
        )
        tasks = self.tm.list_tasks()
        task = next(t for t in tasks if t["task_id"] == tid)
        assert task["source_task_id"] == "src456"


class TestChainBacktest:
    def setup_method(self):
        from services.backtest.task_manager import task_manager
        self.tm = task_manager

    def test_source_task_not_found(self):
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
            "source_task_id": "nonexistent",
        })
        assert resp.status_code == 400
        assert "不存在" in resp.json()["detail"]

    def test_source_task_not_success(self):
        tid = self.tm.create_task(task_type="screener")
        self.tm.fail_task(tid, "test error")
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
            "source_task_id": tid,
        })
        assert resp.status_code == 400
        assert "未成功" in resp.json()["detail"]

    def test_source_task_no_screened_symbols(self):
        tid = self.tm.create_task(task_type="backtest")
        self.tm.complete_task(tid, {"metrics": {"total_return": 0.1}})
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
            "source_task_id": tid,
        })
        assert resp.status_code == 400
        assert "选股" in resp.json()["detail"]

    def test_source_task_empty_symbols(self):
        tid = self.tm.create_task(task_type="screener")
        self.tm.complete_task(tid, {"screened_symbols": []})
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
            "source_task_id": tid,
        })
        assert resp.status_code == 400
        assert "未选出" in resp.json()["detail"]

    @patch("routers.backtest._load_stock_data")
    def test_chain_backtest_passes_symbols_and_dates(self, mock_load):
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"000001": df}

        src_tid = self.tm.create_task(
            task_type="screener",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        self.tm.complete_task(src_tid, {
            "screened_symbols": [
                {"symbol": "000001", "match_dates": ["2024-02-01"]},
                {"symbol": "600036", "match_dates": ["2024-03-01"]},
            ]
        })

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
            "source_task_id": src_tid,
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()

        mock_load.assert_called_once_with("2024-01-01", "2024-12-31", ["000001", "600036"])

    @patch("routers.backtest._load_stock_data")
    def test_chain_backtest_flat_symbol_list(self, mock_load):  # noqa: E302
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"000001": df}

        src_tid = self.tm.create_task(task_type="screener")
        self.tm.complete_task(src_tid, {
            "screened_symbols": ["000001", "600036"]
        })

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
            "source_task_id": src_tid,
        })
        assert resp.status_code == 200
        mock_load.assert_called_once_with(None, None, ["000001", "600036"])


class TestJoinModesAPI:
    @patch("routers.backtest._load_stock_data")
    def test_join_modes_passed_to_engine(self, mock_load):
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"TEST.SH": df}

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")

        with patch("routers.backtest.BacktestEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {"screened_symbols": []}
            mock_engine_cls.return_value = mock_engine

            resp = client.post("/api/backtest/run", json={
                "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
                "join_modes": ["AND", "OR"],
            })
            assert resp.status_code == 200

            import time
            time.sleep(0.5)

            mock_engine_cls.assert_called_once()
            call_kwargs = mock_engine_cls.call_args[1]
            assert call_kwargs["join_modes"] == ["AND", "OR"]

    @patch("routers.backtest._load_stock_data")
    def test_join_modes_in_pipeline_info(self, mock_load, isolated_task_manager):
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"TEST.SH": df}

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")

        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
            "join_modes": ["AND"],
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        result = isolated_task_manager.get_result(task_id)
        pi = result["pipeline_info"]
        assert isinstance(pi, dict)
        assert "strategies" in pi
        assert pi["join_modes"] == ["AND"]

    @patch("routers.backtest._load_stock_data")
    def test_join_modes_default_when_missing(self, mock_load, isolated_task_manager):
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"TEST.SH": df}

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")

        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        result = isolated_task_manager.get_result(task_id)
        pi = result["pipeline_info"]
        assert isinstance(pi, dict)
        assert "strategies" in pi
        assert "join_modes" not in pi


class TestSoftDeleteApi:
    def test_delete_task(self, isolated_task_manager):
        task_id = isolated_task_manager.create_task(task_type="screener")
        resp = client.delete(f"/api/backtest/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deleted_task_hidden_by_default(self, isolated_task_manager):
        task_id = isolated_task_manager.create_task(task_type="screener")
        isolated_task_manager.delete_task(task_id)
        resp = client.get("/api/backtest/tasks")
        ids = [t["task_id"] for t in resp.json()]
        assert task_id not in ids

    def test_deleted_task_visible_with_show_deleted(self, isolated_task_manager):
        task_id = isolated_task_manager.create_task(task_type="screener")
        isolated_task_manager.delete_task(task_id)
        resp = client.get("/api/backtest/tasks?show_deleted=true")
        ids = [t["task_id"] for t in resp.json()]
        assert task_id in ids

    def test_deleted_task_has_deleted_flag(self, isolated_task_manager):
        task_id = isolated_task_manager.create_task(task_type="screener")
        isolated_task_manager.delete_task(task_id)
        resp = client.get("/api/backtest/tasks?show_deleted=true")
        match = next(t for t in resp.json() if t["task_id"] == task_id)
        assert match["deleted"] is True
