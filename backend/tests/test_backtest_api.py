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
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n, freq="B")
                .strftime("%Y-%m-%d")
                .tolist(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": [1e6] * n,
                "amount": [1e7] * n,
            }
        )
        mock_load.return_value = {"TEST.SH": df}

        from pathlib import Path

        strategies_dir = (
            Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        )
        screener_path = str(strategies_dir / "ma_tangle_value_strategy.py")

        resp = client.post(
            "/api/backtest/run",
            json={
                "pipeline": [
                    {
                        "filepath": screener_path,
                        "class_name": "MaTangleValueStrategy",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert "task_id" in resp.json()

    @patch("routers.backtest._load_stock_data")
    def test_run_writes_decision_logs_to_task_dir(self, mock_load):
        """Phase 7: 路由必须把 LOG_DIR/backtest/{task_id}/ 传给 Engine,
        否则 DecisionLogSink 会被禁用,日志全部丢失。"""
        import time
        import pandas as pd
        import numpy as np
        from pathlib import Path
        from config import LOG_DIR

        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n, freq="B")
                .strftime("%Y-%m-%d")
                .tolist(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": [1e6] * n,
                "amount": [1e7] * n,
            }
        )
        mock_load.return_value = {"TEST.SH": df}

        strategies_dir = (
            Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        )
        screener_path = str(strategies_dir / "ma_tangle_value_strategy.py")

        resp = client.post(
            "/api/backtest/run",
            json={
                "strategy_class": "MaTangleValueStrategy",
                "filepath": screener_path,
                "params": {},
            },
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # 等待后台线程跑完(数据小,通常 < 2s)
        from services.backtest.task_manager import task_manager

        for _ in range(40):
            status = task_manager.get_status(task_id)
            if status and status["status"] != "running":
                break
            time.sleep(0.1)

        log_dir = LOG_DIR / "backtest" / task_id
        # flow.jsonl 应至少含 engine.run.start
        flow_path = log_dir / "flow.jsonl"
        assert flow_path.exists(), f"flow.jsonl not written under {log_dir}"
        content = flow_path.read_text()
        assert "engine.run.start" in content

    @patch("routers.backtest._load_stock_data")
    def test_run_accepts_flat_payload(self, mock_load):
        """Phase 5: 新扁平 payload {strategy_class, filepath, params}。"""
        import pandas as pd
        import numpy as np

        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n, freq="B")
                .strftime("%Y-%m-%d")
                .tolist(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": [1e6] * n,
                "amount": [1e7] * n,
            }
        )
        mock_load.return_value = {"TEST.SH": df}

        from pathlib import Path

        strategies_dir = (
            Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        )
        screener_path = str(strategies_dir / "ma_tangle_value_strategy.py")

        resp = client.post(
            "/api/backtest/run",
            json={
                "strategy_class": "MaTangleValueStrategy",
                "filepath": screener_path,
                "params": {},
            },
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # 验证 pipeline_info 存为扁平结构
        from services.backtest.task_manager import task_manager

        result = task_manager.get_result(task_id)
        pi = result["pipeline_info"]
        assert pi["strategy_class"] == "MaTangleValueStrategy"
        assert "params" in pi
        # 不应再嵌套
        assert "strategies" not in pi


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
