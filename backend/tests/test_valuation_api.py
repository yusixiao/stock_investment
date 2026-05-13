import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestValuationAPI:
    @patch("routers.valuation._runner")
    def test_trigger_full_update(self, mock_runner):
        mock_runner.start.return_value = True
        resp = client.post("/api/valuation/update", json={"mode": "full"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "valuation update started"
        assert data["mode"] == "full"

    @patch("routers.valuation._runner")
    def test_trigger_incremental_update(self, mock_runner):
        mock_runner.start.return_value = True
        resp = client.post("/api/valuation/update", json={"mode": "incremental"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "incremental"

    @patch("routers.valuation._runner")
    def test_trigger_with_force(self, mock_runner):
        mock_runner.start.return_value = True
        resp = client.post(
            "/api/valuation/update", json={"mode": "full", "force": True}
        )
        assert resp.status_code == 200

    def test_get_status_idle(self):
        resp = client.get("/api/valuation/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    @patch("routers.valuation._runner")
    def test_get_status_running(self, mock_runner):
        mock_runner.get_status.return_value = {
            "status": "running",
            "progress": {"current": 5, "total": 100, "phase": "拉取估值数据"},
            "result": None,
        }
        resp = client.get("/api/valuation/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["progress"]["current"] == 5
