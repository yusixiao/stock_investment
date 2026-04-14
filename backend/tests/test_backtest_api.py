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
        screener_path = str(strategies_dir / "ma_cross_screener.py")

        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
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
