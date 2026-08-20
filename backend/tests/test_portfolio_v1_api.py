import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.portfolio.db import init_db
from services.portfolio.account_service import materialize_strategy_targets


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    with patch("routers.portfolio_v1._get_connection", return_value=conn), patch(
        "routers.portfolio_v1._get_task_manager"
    ) as task_manager, patch("routers.portfolio_v1._get_materializer", return_value=lambda **kwargs: None):
        task_manager.return_value.get_result.return_value = {
            "task_id": "task-1", "status": "success", "execution_status": "inactive"
        }
        yield TestClient(app), task_manager
    conn.close()


def test_v1_account_lifecycle(client):
    http, _ = client

    created = http.post("/api/v1/portfolio/accounts", json={"name": "账户", "market": "A", "base_currency": "CNY"})
    assert created.status_code == 201
    account_id = created.json()["id"]
    assert created.json()["strategy_task_id"] is None

    bound = http.post(f"/api/v1/portfolio/accounts/{account_id}/strategy", json={"task_id": "task-1"})
    assert bound.status_code == 200
    assert bound.json()["strategy_task_id"] == "task-1"

    unbound = http.delete(f"/api/v1/portfolio/accounts/{account_id}/strategy")
    assert unbound.status_code == 200
    assert unbound.json()["strategy_task_id"] is None


def test_v1_bind_maps_domain_errors(client):
    http, task_manager = client
    created = http.post("/api/v1/portfolio/accounts", json={"name": "账户", "market": "A", "base_currency": "CNY"}).json()
    task_manager.return_value.get_result.return_value = {"task_id": "task-1", "status": "running"}

    response = http.post(
        f"/api/v1/portfolio/accounts/{created['id']}/strategy", json={"task_id": "task-1"}
    )

    assert response.status_code == 409


def test_v1_rejects_missing_required_fields(client):
    http, _ = client

    assert http.post("/api/v1/portfolio/accounts", json={"name": "缺字段"}).status_code == 422
    assert http.post("/api/v1/portfolio/accounts/1/strategy", json={}).status_code == 422


def test_v1_fails_closed_when_task3_materializer_is_unavailable(client):
    http, _ = client
    with patch("routers.portfolio_v1._get_materializer", return_value=materialize_strategy_targets):
        account = http.post(
            "/api/v1/portfolio/accounts",
            json={"name": "待接入", "market": "A", "base_currency": "CNY"},
        ).json()
        response = http.post(
            f"/api/v1/portfolio/accounts/{account['id']}/strategy",
            json={"task_id": "task-1"},
        )

    assert response.status_code == 503
