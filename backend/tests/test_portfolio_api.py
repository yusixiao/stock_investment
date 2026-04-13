import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from services.portfolio.db import get_connection, init_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_db():
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    with patch("routers.portfolio._get_manager") as mock:
        from services.portfolio.manager import PortfolioManager
        mgr = PortfolioManager(conn)
        mock.return_value = mgr
        yield mgr
    conn.close()


class TestCreatePortfolio:
    def test_create(self):
        resp = client.post("/api/portfolio/", json={"name": "test", "initial_capital": 100000})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test"
        assert data["initial_capital"] == 100000
        assert data["source"] == "manual"

    def test_duplicate_returns_400(self):
        client.post("/api/portfolio/", json={"name": "dup", "initial_capital": 100000})
        resp = client.post("/api/portfolio/", json={"name": "dup", "initial_capital": 100000})
        assert resp.status_code == 400


class TestListPortfolios:
    def test_list_empty(self):
        resp = client.get("/api/portfolio/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self):
        client.post("/api/portfolio/", json={"name": "a", "initial_capital": 100000})
        resp = client.get("/api/portfolio/")
        assert len(resp.json()) == 1


class TestGetPortfolio:
    def test_get(self):
        create = client.post("/api/portfolio/", json={"name": "t", "initial_capital": 100000}).json()
        resp = client.get(f"/api/portfolio/{create['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "t"

    def test_404(self):
        resp = client.get("/api/portfolio/999")
        assert resp.status_code == 404


class TestDeletePortfolio:
    def test_delete(self):
        create = client.post("/api/portfolio/", json={"name": "del", "initial_capital": 100000}).json()
        resp = client.delete(f"/api/portfolio/{create['id']}")
        assert resp.status_code == 200
        resp2 = client.get(f"/api/portfolio/{create['id']}")
        assert resp2.status_code == 404


class TestTrades:
    def test_add_trade(self):
        p = client.post("/api/portfolio/", json={"name": "tr", "initial_capital": 100000}).json()
        resp = client.post(f"/api/portfolio/{p['id']}/trades", json={
            "symbol": "600519.SH", "direction": "buy", "price": 1800.0, "shares": 100, "trade_date": "2026-04-10"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "600519.SH"
        assert data["commission"] > 0

    def test_get_trades(self):
        p = client.post("/api/portfolio/", json={"name": "tr2", "initial_capital": 100000}).json()
        client.post(f"/api/portfolio/{p['id']}/trades", json={
            "symbol": "600519.SH", "direction": "buy", "price": 1800.0, "shares": 100, "trade_date": "2026-04-10"
        })
        resp = client.get(f"/api/portfolio/{p['id']}/trades")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestHoldings:
    def test_holdings(self):
        p = client.post("/api/portfolio/", json={"name": "h", "initial_capital": 200000}).json()
        client.post(f"/api/portfolio/{p['id']}/trades", json={
            "symbol": "600519.SH", "direction": "buy", "price": 1800.0, "shares": 100, "trade_date": "2026-04-10"
        })
        resp = client.get(f"/api/portfolio/{p['id']}/holdings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol"] == "600519.SH"
        assert data[0]["shares"] == 100


class TestSnapshots:
    def test_snapshots_empty(self):
        p = client.post("/api/portfolio/", json={"name": "sn", "initial_capital": 100000}).json()
        resp = client.get(f"/api/portfolio/{p['id']}/snapshots")
        assert resp.status_code == 200
        assert resp.json() == []


class TestImport:
    def test_import_nonexistent_task(self):
        resp = client.post("/api/portfolio/import/nonexistent", json={"name": "imp"})
        assert resp.status_code == 404

    @patch("routers.portfolio.task_manager")
    def test_import_success(self, mock_tm):
        mock_tm.get_result.return_value = {
            "task_id": "abc123",
            "status": "success",
            "result": {
                "equity_curve": [
                    {"date": "2026-04-10", "total_value": 1050000, "cash": 900000, "market_value": 150000, "positions": {"600519.SH": {"shares": 100, "cost": 1000.0, "market_price": 1500.0}}},
                ],
                "trades": [],
            },
            "error": None,
        }
        resp = client.post("/api/portfolio/import/abc123", json={"name": "imported"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "backtest"
