import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import pandas as pd

from main import app

client = TestClient(app)


class TestStockRoutes:
    def test_list_stocks(self):
        resp = client.get("/api/stocks")
        assert resp.status_code == 200
        data = resp.json()
        assert "stocks" in data
        assert "total" in data

    def test_list_stocks_with_search(self):
        resp = client.get("/api/stocks?search=600028")
        assert resp.status_code == 200

    def test_list_stocks_with_pagination(self):
        resp = client.get("/api/stocks?page=1&page_size=10")
        assert resp.status_code == 200

    def test_get_kline(self):
        resp = client.get("/api/stocks/600028.SH/kline")
        assert resp.status_code in [200, 404]

    def test_get_kline_with_date_range(self):
        resp = client.get("/api/stocks/600028.SH/kline?start_date=2026-04-01&end_date=2026-04-10")
        assert resp.status_code in [200, 404]

    def test_get_indicators(self):
        resp = client.get("/api/stocks/600028.SH/indicators?types=ma,macd")
        assert resp.status_code in [200, 404]

    def test_get_kline_qfq(self):
        resp = client.get("/api/stocks/600028.SH/kline?adjust=qfq")
        assert resp.status_code in [200, 404]

    def test_get_indicators_qfq(self):
        resp = client.get("/api/stocks/600028.SH/indicators?types=ma&adjust=qfq")
        assert resp.status_code in [200, 404]


class TestDataUpdateRoutes:
    @patch("routers.data_update.run_update_task")
    def test_trigger_update(self, mock_task):
        resp = client.post("/api/data/update", json={"date": "2026-04-11"})
        assert resp.status_code == 200
        assert "incremental update started" in resp.json()["message"]

    def test_trigger_update_requires_date(self):
        resp = client.post("/api/data/update", json={})
        assert resp.status_code == 400

    def test_get_update_status(self):
        resp = client.get("/api/data/update/status")
        assert resp.status_code == 200
        assert "status" in resp.json()

    def test_get_update_logs(self):
        resp = client.get("/api/data/update/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
