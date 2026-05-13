import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestFinancialAPI:
    @patch("routers.financial._runner")
    def test_trigger_full_update(self, mock_runner):
        mock_runner.start.return_value = True
        resp = client.post("/api/financial/update", json={"mode": "full"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "financial update started"
        assert data["mode"] == "full"

    @patch("routers.financial._runner")
    def test_trigger_incremental_update(self, mock_runner):
        mock_runner.start.return_value = True
        resp = client.post("/api/financial/update", json={"mode": "incremental"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "incremental"

    def test_get_status_idle(self):
        resp = client.get("/api/financial/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    @patch("routers.financial._runner")
    def test_get_status_running(self, mock_runner):
        mock_runner.get_status.return_value = {
            "status": "running",
            "progress": {"current": 5, "total": 100, "phase": "拉取财报数据 20241231"},
            "result": None,
        }
        resp = client.get("/api/financial/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["progress"]["current"] == 5

    @patch("routers.financial._runner")
    def test_default_mode_is_full(self, mock_runner):
        mock_runner.start.return_value = True
        resp = client.post("/api/financial/update")
        assert resp.status_code == 200
