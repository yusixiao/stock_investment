import sqlite3
from unittest.mock import MagicMock, patch

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
        "routers.portfolio_v1._close_connection"
    ), patch(
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


def test_v1_does_not_expose_unexpected_runtime_errors(client):
    http, _ = client
    account = http.post(
        "/api/v1/portfolio/accounts",
        json={"name": "内部错误", "market": "A", "base_currency": "CNY"},
    ).json()

    def broken_materializer(**kwargs):
        raise RuntimeError("database secret details")

    with patch("routers.portfolio_v1._get_materializer", return_value=broken_materializer):
        with pytest.raises(RuntimeError, match="database secret details"):
            http.post(
                f"/api/v1/portfolio/accounts/{account['id']}/strategy",
                json={"task_id": "task-1"},
            )


def test_v1_core_trade_holdings_and_snapshot_contract(client):
    http, _ = client
    account = http.post(
        "/api/v1/portfolio/accounts",
        json={"name": "核心接口", "market": "A", "base_currency": "CNY"},
    ).json()
    account_id = account["id"]

    with patch("routers.portfolio_v1._get_store") as get_store:
        get_store.return_value.query_latest_closes.return_value = {"600519.SH": (120.0, "2026-08-18")}
        created = http.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": account_id,
                "symbol": "600519",
                "side": "buy",
                "quantity": 2,
                "price": 100,
                "trade_date": "2026-08-19",
            },
        )
        assert created.status_code == 201

        trades = http.get("/api/v1/portfolio/trades", params={"account_id": account_id})
        assert trades.status_code == 200
        assert trades.json()["total"] == 1

        holdings = http.get(f"/api/v1/portfolio/accounts/{account_id}/holdings")
        assert holdings.status_code == 200
        assert holdings.json()[0]["symbol"] == "600519"

        snapshot = http.get("/api/v1/portfolio/snapshot", params={"account_id": account_id, "as_of": "2026-08-19"})
        assert snapshot.status_code == 200
        assert snapshot.json()["accounts"][0]["positions"][0]["last_price"] == 120.0
        assert snapshot.json()["accounts"][0]["positions"][0]["price_date"] == "2026-08-18"
        assert snapshot.json()["accounts"][0]["positions"][0]["price_stale"] is True


def test_v1_normalizes_frontend_market_values(client):
    http, _ = client
    response = http.post(
        "/api/v1/portfolio/accounts",
        json={"name": "前端市场", "market": "cn", "base_currency": "CNY"},
    )

    assert response.status_code == 201
    assert response.json()["market"] == "A"


def test_v1_non_core_endpoints_are_explicitly_unavailable(client):
    http, _ = client
    assert http.get("/api/v1/portfolio/risk").status_code == 501
    assert http.post("/api/v1/portfolio/fx/refresh").status_code == 501
    assert http.get("/api/v1/portfolio/cash-ledger").status_code == 501
    assert http.get("/api/v1/portfolio/corporate-actions").status_code == 501
    assert http.get("/api/v1/portfolio/imports/csv/brokers").status_code == 501


def test_v1_request_scope_closes_connection_on_success_and_error():
    from routers import portfolio_v1

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    closed = []
    original_get = portfolio_v1._get_connection
    original_close = portfolio_v1._close_connection
    portfolio_v1._get_connection = lambda: connection
    portfolio_v1._close_connection = lambda conn: closed.append(conn)
    try:
        with portfolio_v1._connection_scope() as scoped:
            assert scoped is connection
        with pytest.raises(ValueError):
            with portfolio_v1._connection_scope():
                raise ValueError("request failed")
    finally:
        portfolio_v1._get_connection = original_get
        portfolio_v1._close_connection = original_close
        connection.close()

    assert closed == [connection, connection]


def test_get_connection_closes_when_init_db_fails():
    from routers import portfolio_v1

    connection = MagicMock()
    with patch("routers.portfolio_v1.get_connection", return_value=connection), patch(
        "routers.portfolio_v1.init_db", side_effect=RuntimeError("schema init failed")
    ):
        with pytest.raises(RuntimeError, match="schema init failed"):
            portfolio_v1._get_connection()

    connection.close.assert_called_once_with()


def test_delete_trade_requires_owning_account_and_reprojects(client):
    http, _ = client
    first = http.post("/api/v1/portfolio/accounts", json={"name": "一", "market": "A", "base_currency": "CNY"}).json()
    second = http.post("/api/v1/portfolio/accounts", json={"name": "二", "market": "A", "base_currency": "CNY"}).json()
    trade = http.post("/api/v1/portfolio/trades", json={
        "account_id": first["id"], "symbol": "600519", "side": "buy", "quantity": 10,
        "price": 100, "trade_date": "2026-08-18",
    }).json()
    response = http.delete(f"/api/v1/portfolio/trades/{trade['id']}", params={"account_id": second["id"]})
    assert response.status_code == 409
    assert http.get(f"/api/v1/portfolio/accounts/{first['id']}/holdings").json()[0]["actual_shares"] == 10

    response = http.delete(f"/api/v1/portfolio/trades/{trade['id']}", params={"account_id": first["id"]})
    assert response.status_code == 200
    assert http.get(f"/api/v1/portfolio/accounts/{first['id']}/holdings").json() == []
