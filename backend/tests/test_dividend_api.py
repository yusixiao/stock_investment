import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestDividendAPI:
    @patch("routers.dividend.run_update_in_background")
    def test_trigger_full_update(self, mock_run):
        resp = client.post("/api/dividend/update", json={"mode": "full"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "dividend update started"
        assert data["mode"] == "full"
        mock_run.assert_called_once_with("full", False)

    @patch("routers.dividend.run_update_in_background")
    def test_trigger_incremental_update(self, mock_run):
        resp = client.post("/api/dividend/update", json={"mode": "incremental"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "incremental"
        mock_run.assert_called_once_with("incremental", False)

    @patch("routers.dividend.run_update_in_background")
    def test_trigger_with_force(self, mock_run):
        resp = client.post("/api/dividend/update", json={"mode": "full", "force": True})
        assert resp.status_code == 200
        mock_run.assert_called_once_with("full", True)

    def test_get_status_idle(self):
        resp = client.get("/api/dividend/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    @patch("routers.dividend._status", {"status": "running", "progress": {"current": 10, "total": 200, "phase": "拉取分红数据"}, "result": None})
    def test_get_status_running(self):
        resp = client.get("/api/dividend/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["progress"]["current"] == 10
