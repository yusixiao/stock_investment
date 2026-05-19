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

    @pytest.mark.skip(
        reason="Phase 6.1: 旧 ScreenerStrategy 已删除,统一 Strategy 尚未被 /api/screener/run 接受;待 Phase 5 调整 API 后重新启用"
    )
    @patch("routers.screener.RAW_KLINE_DIR")
    @patch("routers.screener.get_store")
    def test_run_screener_with_mock_data(self, mock_get_store, mock_dir, tmp_path):
        n = 60
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
        pq_path = tmp_path / "TEST.SH.parquet"
        df.to_parquet(pq_path)
        mock_dir.glob = tmp_path.glob
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.query_qfq_kline.return_value = df
        mock_get_store.return_value = mock_store

        from pathlib import Path

        strategies_dir = (
            Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        )
        screener_path = str(strategies_dir / "ma_tangle_value_strategy.py")

        resp = client.post(
            "/api/screener/run",
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
        data = resp.json()
        assert "screened_symbols" in data
        assert "count" in data
