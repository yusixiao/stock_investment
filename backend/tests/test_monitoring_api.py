import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.db_schema import init_portfolio_v1_tables


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_portfolio_v1_tables(conn)
    with patch("routers.monitoring.get_monitoring_connection", return_value=conn), patch(
        "routers.monitoring._close_connection"
    ):
        yield TestClient(app), conn
    conn.close()


def strategy_payload(**overrides):
    payload = {
        "name": "价值策略",
        "strategy_class": "ValueStrategy",
        "filepath": "strategies/value.py",
        "params": {"pe": 15},
        "market": "A",
        "frequency": "weekly",
        "symbols": ["600000"],
        "next_run_date": "2026-08-24",
    }
    payload.update(overrides)
    return payload


def test_strategy_monitor_crud_paginates_and_soft_deletes(client):
    http, conn = client
    first = http.post("/api/v1/monitoring/strategy-monitors", json=strategy_payload()).json()
    second = http.post(
        "/api/v1/monitoring/strategy-monitors",
        json=strategy_payload(name="成长策略", strategy_class="GrowthStrategy"),
    ).json()

    listed = http.get("/api/v1/monitoring/strategy-monitors", params={"limit": 1, "offset": 1})
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert [item["id"] for item in listed.json()["items"]] == [first["id"]]

    updated = http.patch(
        f"/api/v1/monitoring/strategy-monitors/{first['id']}",
        json={"name": "价值策略 v2", "frequency": "daily"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "价值策略 v2"

    deleted = http.delete(f"/api/v1/monitoring/strategy-monitors/{first['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False
    assert http.get("/api/v1/monitoring/strategy-monitors").json()["total"] == 1
    assert conn.execute("SELECT COUNT(*) FROM monitoring_strategy_monitors").fetchone()[0] == 2
    assert second["is_active"] is True


def test_stock_monitor_accepts_only_manual_market_symbol_threshold_and_lifecycle(client):
    http, conn = client
    rejected = http.post(
        "/api/v1/monitoring/stock-monitors",
        json={"market": "HK", "symbol": "00005", "threshold_price": 100.5, "strategy_class": "Bad"},
    )
    assert rejected.status_code == 422
    created = http.post(
        "/api/v1/monitoring/stock-monitors",
        json={"market": "HK", "symbol": "00005", "threshold_price": 100.5},
    )
    assert created.status_code == 201
    monitor = created.json()
    assert monitor["market"] == "HK"
    assert "strategy_class" not in monitor
    assert "account_id" not in monitor

    paused = http.post(f"/api/v1/monitoring/stock-monitors/{monitor['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    resumed = http.post(f"/api/v1/monitoring/stock-monitors/{monitor['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "armed"

    updated = http.patch(
        f"/api/v1/monitoring/stock-monitors/{monitor['id']}",
        json={"threshold_price": 99.0, "name": "腾讯"},
    )
    assert updated.status_code == 200
    assert updated.json()["threshold_price"] == 99.0

    conn.execute(
        "INSERT INTO monitoring_stock_events "
        "(monitor_id, market, symbol, observed_price, threshold_price, observed_date, triggered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (monitor["id"], "HK", "00005", 98.0, 99.0, "2026-08-21", "2026-08-21T16:00:00"),
    )
    conn.commit()
    events = http.get(
        f"/api/v1/monitoring/stock-monitors/{monitor['id']}/events",
        params={"limit": 1, "offset": 0},
    )
    assert events.status_code == 200
    assert events.json()["total"] == 1
    assert events.json()["items"][0]["symbol"] == "00005"

    deleted = http.delete(f"/api/v1/monitoring/stock-monitors/{monitor['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["is_active"] is False
    assert http.get("/api/v1/monitoring/stock-monitors").json()["total"] == 0
    assert conn.execute("SELECT COUNT(*) FROM monitoring_stock_events").fetchone()[0] == 1


def test_monitoring_validation_and_missing_entities_map_to_http_errors(client):
    http, _ = client
    invalid_stock = http.post(
        "/api/v1/monitoring/stock-monitors",
        json={"market": "CN", "symbol": "", "threshold_price": 0},
    )
    assert invalid_stock.status_code == 422
    assert {error["loc"][-1] for error in invalid_stock.json()["detail"]} >= {
        "market", "symbol", "threshold_price"
    }

    invalid_strategy = http.post(
        "/api/v1/monitoring/strategy-monitors",
        json=strategy_payload(strategy_class="", filepath="", frequency="yearly"),
    )
    assert invalid_strategy.status_code == 422

    assert http.get("/api/v1/monitoring/stock-monitors/999/events").status_code == 404
    assert http.post("/api/v1/monitoring/stock-monitors/999/pause").status_code == 404
    assert http.post(
        "/api/v1/monitoring/strategy-monitors/999/run", json={"as_of_date": "2026-08-21"}
    ).status_code == 404
    assert http.get("/api/v1/monitoring/stock-monitors", params={"limit": 0}).status_code == 422


def test_manual_strategy_run_persists_run_and_strategy_endpoint_has_no_stock_import(client):
    http, conn = client
    monitor = http.post("/api/v1/monitoring/strategy-monitors", json=strategy_payload()).json()
    with patch(
        "routers.monitoring.execute_strategy_current_date",
        return_value={"status": "unexecuted", "reason": "test", "as_of_date": "2026-08-21"},
    ):
        response = http.post(
            f"/api/v1/monitoring/strategy-monitors/{monitor['id']}/run",
            json={"as_of_date": "2026-08-21"},
        )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["monitor_id"] == monitor["id"]
    assert conn.execute("SELECT COUNT(*) FROM monitoring_strategy_runs").fetchone()[0] == 1
    assert "stock" not in response.json()
    history = http.get(f"/api/v1/monitoring/strategy-monitors/{monitor['id']}/runs")
    assert history.status_code == 200
    assert history.json()["total"] == 1


def test_monitoring_writes_are_committed_for_a_new_connection(client):
    http, conn = client
    created = http.post(
        "/api/v1/monitoring/stock-monitors",
        json={"market": "US", "symbol": "AAPL", "threshold_price": 100},
    ).json()
    assert conn.execute(
        "SELECT is_active FROM monitoring_stock_monitors WHERE id = ?", (created["id"],)
    ).fetchone()[0] == 1
