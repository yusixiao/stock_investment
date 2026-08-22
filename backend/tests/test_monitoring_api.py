import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from config import DEPLOYED_STRATEGY_DIR


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with patch("routers.monitoring.get_monitoring_connection", return_value=conn), patch(
        "routers.monitoring._close_connection"
    ):
        yield TestClient(app), conn
    conn.close()


def strategy_payload(**overrides):
    payload = {
        "name": "价值策略",
        "strategy_class": "LynchSlowGrowersStrategy",
        "filepath": str(DEPLOYED_STRATEGY_DIR / "lynch_slow_growers_strategy.py"),
        "params": {},
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
        json=strategy_payload(name="成长策略"),
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


def test_strategy_filepath_must_be_published_and_loadable(client, tmp_path):
    http, conn = client
    outside = tmp_path / "evil.py"
    outside.write_text("raise RuntimeError('executed')")
    rejected = http.post(
        "/api/v1/monitoring/strategy-monitors",
        json=strategy_payload(filepath=str(outside)),
    )
    assert rejected.status_code in {409, 422}
    assert conn.execute("SELECT COUNT(*) FROM monitoring_strategy_monitors").fetchone()[0] == 0


def test_invalid_strategy_update_is_rejected_without_partial_write(client, tmp_path):
    http, conn = client
    monitor = http.post("/api/v1/monitoring/strategy-monitors", json=strategy_payload()).json()
    outside = tmp_path / "evil.py"
    outside.write_text("raise RuntimeError('executed')")

    response = http.patch(
        f"/api/v1/monitoring/strategy-monitors/{monitor['id']}",
        json={"filepath": str(outside), "name": "should not persist"},
    )

    assert response.status_code in {409, 422}
    stored = conn.execute(
        "SELECT filepath, name FROM monitoring_strategy_monitors WHERE id = ?", (monitor["id"],)
    ).fetchone()
    assert tuple(stored) == (monitor["filepath"], monitor["name"])


def test_strategy_monitor_defaults_next_run_date_from_trading_calendar(client):
    http, _ = client
    with patch("routers.monitoring.get_monitoring_store") as get_store:
        get_store.return_value.get_trading_dates.return_value = [
            "2026-08-21", "2026-08-24", "2026-08-25"
        ]
        response = http.post(
            "/api/v1/monitoring/strategy-monitors",
            json=strategy_payload(next_run_date=None),
        )
    assert response.status_code == 201
    assert response.json()["next_run_date"] == "2026-08-24"


def test_stock_monitor_patch_forbids_unknown_fields(client):
    http, _ = client
    monitor = http.post(
        "/api/v1/monitoring/stock-monitors",
        json={"market": "HK", "symbol": "00005", "threshold_price": 100},
    ).json()
    response = http.patch(
        f"/api/v1/monitoring/stock-monitors/{monitor['id']}",
        json={"unknown": "field"},
    )
    assert response.status_code == 422
    assert http.get("/api/v1/monitoring/stock-monitors", params={"limit": 0}).status_code == 422


@pytest.mark.parametrize("symbols", [[""], ["600000", "  "], ["00005"]])
def test_strategy_symbols_are_validated_against_strategy_market(client, symbols):
    http, _ = client
    response = http.post(
        "/api/v1/monitoring/strategy-monitors",
        json=strategy_payload(symbols=symbols),
    )
    assert response.status_code == 422

    created = http.post("/api/v1/monitoring/strategy-monitors", json=strategy_payload()).json()
    updated = http.patch(
        f"/api/v1/monitoring/strategy-monitors/{created['id']}",
        json={"symbols": ["00005"]},
    )
    assert updated.status_code == 422


def test_pause_and_resume_require_expected_state(client):
    http, _ = client
    monitor = http.post(
        "/api/v1/monitoring/stock-monitors",
        json={"market": "HK", "symbol": "00005", "threshold_price": 100},
    ).json()

    assert http.post(f"/api/v1/monitoring/stock-monitors/{monitor['id']}/resume").status_code == 409
    assert http.post(f"/api/v1/monitoring/stock-monitors/{monitor['id']}/pause").status_code == 200
    assert http.post(f"/api/v1/monitoring/stock-monitors/{monitor['id']}/pause").status_code == 409
    assert http.post(f"/api/v1/monitoring/stock-monitors/{monitor['id']}/resume").status_code == 200
    assert http.post(f"/api/v1/monitoring/stock-monitors/{monitor['id']}/resume").status_code == 409


def test_monitoring_routes_publish_typed_response_contracts(client):
    http, _ = client
    schema = http.get("/openapi.json").json()
    paths = schema["paths"]
    assert paths["/api/v1/monitoring/strategy-monitors"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert paths["/api/v1/monitoring/stock-monitors/{monitor_id}/events"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    components = schema["components"]["schemas"]
    assert "StrategyMonitorResponse" in components
    assert "StockMonitorResponse" in components
    assert "StrategyRunPage" in components
    assert "StockEventPage" in components


def test_manual_strategy_run_persists_run_and_strategy_endpoint_has_no_stock_import(client):
    http, conn = client
    monitor = http.post("/api/v1/monitoring/strategy-monitors", json=strategy_payload()).json()
    with patch("routers.monitoring.submit_strategy_run") as submit:
        response = http.post(
            f"/api/v1/monitoring/strategy-monitors/{monitor['id']}/run",
            json={"as_of_date": "2026-08-21"},
        )
    assert response.status_code == 201
    assert response.json()["status"] == "running"
    assert response.json()["monitor_id"] == monitor["id"]
    submit.assert_called_once()
    assert conn.execute("SELECT COUNT(*) FROM monitoring_strategy_runs").fetchone()[0] == 1
    assert "stock" not in response.json()
    history = http.get(f"/api/v1/monitoring/strategy-monitors/{monitor['id']}/runs")
    assert history.status_code == 200
    assert history.json()["total"] == 1


def test_manual_strategy_run_marks_unexpected_execution_error_as_failed(client):
    http, conn = client
    monitor = http.post("/api/v1/monitoring/strategy-monitors", json=strategy_payload()).json()
    with patch("routers.monitoring.submit_strategy_run", side_effect=RuntimeError("executor down")):
        response = http.post(
            f"/api/v1/monitoring/strategy-monitors/{monitor['id']}/run",
            json={"as_of_date": "2026-08-21"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "strategy execution dispatch failed: executor down"
    run = conn.execute(
        "SELECT status, error FROM monitoring_strategy_runs WHERE monitor_id = ?", (monitor["id"],)
    ).fetchone()
    assert tuple(run) == ("failed", "strategy execution dispatch failed: executor down")


def test_monitoring_writes_are_committed_for_a_new_connection(client):
    http, conn = client
    created = http.post(
        "/api/v1/monitoring/stock-monitors",
        json={"market": "US", "symbol": "AAPL", "threshold_price": 100},
    ).json()
    assert conn.execute(
        "SELECT is_active FROM monitoring_stock_monitors WHERE id = ?", (created["id"],)
    ).fetchone()[0] == 1
