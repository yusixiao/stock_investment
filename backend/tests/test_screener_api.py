import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
import pandas as pd
import numpy as np

from main import app

client = TestClient(app)


class TestScreenerRoutes:
    def test_empty_pipeline_returns_400(self):
        resp = client.post("/api/screener/run", json={"pipeline": []})
        assert resp.status_code == 400

    def test_get_result_initially_empty(self):
        resp = client.get("/api/screener/result")
        assert resp.status_code == 200
        data = resp.json()
        assert "screened_symbols" in data

    @patch("routers.screener.QFQ_KLINE_DIR")
    def test_run_screener_with_mock_data(self, mock_dir, tmp_path):
        n = 60
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        pq_path = tmp_path / "TEST.SH.parquet"
        df.to_parquet(pq_path)
        mock_dir.glob = tmp_path.glob

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_tangle_breakout_screener.py")

        resp = client.post("/api/screener/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaTangleBreakoutScreener"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "screened_symbols" in data
        assert "count" in data
