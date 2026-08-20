import json
import sqlite3

import pytest

from services.db_schema import init_backtest_tables
from services.portfolio.db import init_db
from services.portfolio.repository import AccountRepository
from services.portfolio.account_service import AccountService
from services.portfolio.strategy_targets import (
    TargetRecommendationUnavailable,
    get_current_targets,
    get_target_history,
    is_buy_allowed,
    materialize_targets,
)


TASK_ID = "2baab97c"
TARGETS = [
    {"symbol": "000001.SZ", "target_quantity": 100, "reference_price": 10.0, "status": "active"},
    {"symbol": "000002.SZ", "target_quantity": 200, "reference_price": 20.0, "status": "active"},
    {"symbol": "600000.SH", "target_quantity": 300, "reference_price": 30.0, "status": "active"},
    {"symbol": "600519.SH", "target_quantity": 400, "reference_price": 40.0, "status": "active"},
    {"symbol": "601318.SH", "target_quantity": 500, "reference_price": 50.0, "status": "active"},
]


@pytest.fixture
def target_context(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    init_backtest_tables(conn)
    account = AccountRepository(conn).create_account("策略账户", "A", "CNY")
    result = {
        "strategy_targets": [
            {"effective_date": "2026-06-02", "targets": TARGETS},
            {
                "effective_date": "2026-09-01",
                "targets": [
                    *TARGETS[:4],
                    {"symbol": "601318.SH", "target_quantity": 0, "reference_price": 50.0, "status": "exited"},
                ],
            },
        ]
    }
    conn.execute(
        "INSERT INTO backtest_tasks (task_id, status, result, task_type, pipeline_info, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (TASK_ID, "success", json.dumps(result), "screener", "{}", "2026-08-20T00:00:00"),
    )
    conn.commit()

    from services.portfolio import strategy_targets

    yield conn, account
    conn.close()


def test_materializer_persists_five_targets_and_history(target_context):
    conn, account = target_context

    assert materialize_targets(account.id, TASK_ID, connection=conn) == 5

    targets = get_current_targets(account.id, "2026-08-20", connection=conn)
    assert [(t.symbol, t.target_quantity, t.reference_price) for t in targets] == [
        (item["symbol"], item["target_quantity"], item["reference_price"]) for item in TARGETS
    ]
    history = get_target_history(account.id, connection=conn)
    assert len(history) == 2
    assert history[0].effective_date == "2026-06-02"
    assert history[1].effective_date == "2026-09-01"


def test_current_targets_ignore_future_revision_and_zero_quantity_disallows_buy(target_context):
    conn, account = target_context
    materialize_targets(account.id, TASK_ID, connection=conn)

    assert [t.symbol for t in get_current_targets(account.id, "2026-08-20", connection=conn)] == [
        item["symbol"] for item in TARGETS
    ]
    assert is_buy_allowed(account.id, "601318.SH", "2026-08-20", connection=conn)
    assert not is_buy_allowed(account.id, "601318.SH", "2026-09-01", connection=conn)
    assert not is_buy_allowed(account.id, "999999.SZ", "2026-08-20", connection=conn)


def test_materializer_rejects_result_without_explicit_recommendations(target_context):
    conn, account = target_context
    conn.execute("UPDATE backtest_tasks SET result = ? WHERE task_id = ?", (json.dumps({"trades": []}), TASK_ID))
    conn.commit()

    with pytest.raises(TargetRecommendationUnavailable):
        materialize_targets(account.id, TASK_ID, connection=conn)


def test_account_binding_uses_production_materializer(target_context):
    conn, account = target_context

    class TaskManager:
        def get_result(self, task_id):
            return {"task_id": task_id, "status": "success", "execution_status": "inactive"}

        def set_execution_account(self, task_id, account_id, connection=None):
            return None

    from routers.portfolio_v1 import _get_materializer

    service = AccountService(AccountRepository(conn), TaskManager(), _get_materializer())
    bound = service.bind_strategy(account.id, TASK_ID)

    assert bound.strategy_task_id == TASK_ID
    assert len(get_current_targets(account.id, "2026-08-20", connection=conn)) == 5
